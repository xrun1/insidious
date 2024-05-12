from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging as log
import threading
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import (
    Any,
    ClassVar,
    Self,
    TypeAlias,
    TypeVar,
)
from urllib.parse import parse_qs, quote_plus

import appdirs
import backoff
import lz4.frame
import yt_dlp
from fastapi.datastructures import URL
from typing_extensions import override
from yt_dlp import YoutubeDL
from yt_dlp.networking.common import (
    Request as YtdlpRequest,
    Response as YtdlpResponse,
)

from insidious import NAME
from insidious.extractors.filters import SearchFilter
from insidious.net import PARALLEL_REQUESTS_PER_HOST, max_parallel_requests

from .client import YoutubeClient
from .data import (
    Channel,
    ChannelEntry,
    FeaturedChannelPlaylist,
    FeaturedChannelTab,
    PartialEntry,
    PartialVideo,
    Playlist,
    PlaylistEntry,
    Search,
    ShortEntry,
    Video,
    VideoEntry,
)

T = TypeVar("T")
RawData: TypeAlias = dict[str, Any]
RequestCallback: TypeAlias = Callable[[YtdlpRequest], None]

MAX_CACHE_TIME = 60 * 60
CACHE_DIR = Path(appdirs.user_cache_dir(NAME))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
ExpireIn: TypeAlias = Callable[[float], None]


class NoDataReceived(yt_dlp.utils.ExtractorError):
    def __init__(self) -> None:
        super().__init__("Failed to gather any data from origin site")


@dataclass
class CacheFile:
    path: Path

    _locks: ClassVar[defaultdict[Path, threading.Lock]] = \
        defaultdict(threading.Lock)

    class _CompatibleBytesIO(io.BytesIO):
        @override
        def read(self, *_: Any, **__: Any) -> bytes:
            return super().read()

    def dates(self) -> tuple[datetime, datetime]:
        with self._lock:
            raw = self.path.read_bytes()

        access, expire = self._unzip(raw).splitlines()[:2]
        access_date = datetime.fromtimestamp(float(access))
        expire_date = datetime.fromtimestamp(float(expire))
        return access_date, expire_date

    def expire_in(self, seconds: float) -> None:
        with self._lock, self.path.open("rb+") as f:
            access, _, *rest = self._unzip(f.read()).splitlines()
            expire = str(datetime.now(UTC).timestamp() + seconds).encode()
            lines = [access, expire, *rest]
            f.seek(0)
            f.write(self._zip(b"\n".join(lines)))

    def response(self) -> YtdlpResponse | None:
        if not self.path.exists():
            return None

        with self._lock, self.path.open("rb+") as f:
            try:
                dump = self._unzip(f.read())
            except RuntimeError:
                log.exception("%s is corrupted, removing", self.path)
                self.path.unlink()
                return None

            _, *lines = dump.splitlines()
            expire_ts, url, headers, status, reason, *data = lines

            expire_date = datetime.fromtimestamp(float(expire_ts), UTC)
            if datetime.now(UTC) >= expire_date:
                return None

            access_ts = str(datetime.now(UTC).timestamp()).encode()
            f.seek(0)
            f.write(self._zip(b"\n".join((access_ts, *lines))))

        return YtdlpResponse(
            io.BytesIO(b"\n".join(data)),
            url.decode(),
            json.loads(headers),
            int(status),
            reason.decode(),
        )

    def write(self, resp: YtdlpResponse, cache_time: float) -> None:
        now = datetime.now(UTC).timestamp()
        dump = "\n".join((
            str(now),
            str(now + cache_time),
            resp.url,
            json.dumps(dict(resp.headers)),
            str(resp.status),
            resp.reason or "",
            "",
        )).encode() + (data := resp.read())
        resp.fp = self._CompatibleBytesIO(data)
        with self._lock:
            self.path.write_bytes(self._zip(dump))

    @classmethod
    def from_request(cls, req: YtdlpRequest) -> Self | None:
        if not isinstance(req.data, bytes | None):
            return None

        to_hash = (req.method + req.url).encode() + (req.data or b"")
        md5 = hashlib.md5(to_hash, usedforsecurity=False).hexdigest()
        return cls(CACHE_DIR / md5)

    @property
    def _lock(self) -> threading.Lock:
        return self._locks[self.path]

    @staticmethod
    def _zip(data: bytes) -> bytes:
        return lz4.frame.compress(data, compression_level=3)

    @staticmethod
    def _unzip(data: bytes) -> bytes:
        return lz4.frame.decompress(data)


class CachedYoutubeDL(YoutubeDL):
    # WARN: not threadsafe
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._newly_written: list[CacheFile] | None = None
        self._urlopen_callback: RequestCallback | None = None
        self._skip_cache: bool = False

    @override
    def urlopen(
        self, req: str | urllib.request.Request | YtdlpRequest,
    ) -> YtdlpResponse:

        if isinstance(req, str):
            req = YtdlpRequest(req)
        elif isinstance(req, urllib.request.Request):
            req = yt_dlp.compat.urllib_req_to_req(req)

        if self._urlopen_callback:
            self._urlopen_callback(req)

        if (file := CacheFile.from_request(req)):
            if not self._skip_cache and (resp := file.response()):
                return resp

            file.write(resp := super().urlopen(req), MAX_CACHE_TIME)
            if self._newly_written is not None:
                self._newly_written.append(file)
            return resp

        return super().urlopen(req)

    @contextmanager
    def before_requests(self, callback: RequestCallback) -> Iterator[None]:
        self._urlopen_callback = callback
        try:
            yield
        finally:
            self._urlopen_callback = None

    @contextmanager
    def adjust_cache_expiration(self) -> Iterator[ExpireIn]:
        self._newly_written = batch = []

        def make_expire_in(seconds: float):
            for file in batch:
                file.expire_in(seconds)

        try:
            yield make_expire_in
        finally:
            self._newly_written = None

    @contextmanager
    def skip_cache(self, skip: bool = True) -> Iterator[None]:
        self._skip_cache = skip
        try:
            yield
        finally:
            self._skip_cache = False

    @staticmethod
    def prune_cache(size_limit: int = 1024 * 1024 * 512) -> None:
        now = datetime.now(UTC)
        by_access: list[tuple[datetime, Path]] = []
        sizes: dict[Path, int] = {}

        for path in CACHE_DIR.iterdir():
            sizes[path] = path.stat().st_size

        if (total_size := sum(sizes.values())) < size_limit:
            return

        for path in CACHE_DIR.iterdir():
            try:
                access, expire = CacheFile(path).dates()
            except RuntimeError:
                access, expire = None, None
                log.exception("%r is corrupted, removing", path)

            if access is None or expire is None or now >= expire:
                path.unlink()
                total_size -= sizes.pop(path)
            else:
                by_access.append((access, path))

        by_access.sort(key=lambda x: x[0], reverse=True)  # most recent first

        while total_size > size_limit * 0.66 and by_access:
            path = by_access.pop()[1]
            path.unlink()
            total_size -= sizes.pop(path)


@dataclass
class YtdlpClient(YoutubeClient):
    _ytdl_instances: ClassVar[dict[threading.Thread, CachedYoutubeDL]] = {}
    _pool: ClassVar[ThreadPoolExecutor] = \
        ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS_PER_HOST)

    @property
    def headers(self) -> dict[str, str]:
        return self._ytdl.params["http_headers"]

    @override
    async def search(
        self, query: str, filter: SearchFilter | None = None, page: int = 1,
    ) -> Search:
        sp = (filter or SearchFilter()).url_parameter
        path = f"results?search_query={quote_plus(query)}&sp={sp}"
        return Search.model_validate((await self._get(path, page))[0])

    @override
    async def channel(
        self, id: str, tab: str = "featured", search: str = "", page: int = 1,
    ) -> Channel:
        return await self._channel(f"channel/{id}", tab, search, page)

    @override
    async def named_channel(
        self,
        name: str, tab: str = "featured", search: str = "", page: int = 1,
    ) -> Channel:
        return await self._channel(name, tab, search, page)

    @override
    async def user(
        self, id: str, tab: str = "featured", search: str = "", page: int = 1,
    ) -> Channel:
        return await self._channel(f"user/{id}", tab, search, page)

    @override
    async def playlist(self, id: str, page: int = 1) -> Playlist:
        path = f"playlist?list={id}"
        pl = Playlist.model_validate((await self._get(path, page))[0])
        for entry in pl:
            url = URL(entry.url).include_query_params(list=pl.id)
            if entry.nth not in {None, 1}:
                url = url.include_query_params(index=entry.nth)
            entry.url = str(url)
        return pl

    @override
    async def hashtag(self, tag: str, page: int = 1) -> Playlist:
        path = f"hashtag/{tag}"
        return Playlist.model_validate((await self._get(path, page))[0])

    @override
    async def video(self, id: str, skip_cache: bool = False) -> Video:
        data, expire_in = await self._get(
            f"watch?v={id}", process=True, skip_cache=skip_cache,
        )

        if "concurrent_view_count" in data:
            video = PartialVideo.model_validate(data)
        else:
            video = Video.model_validate(data)

        limit = MAX_CACHE_TIME
        expire_in(min(video.metadata_reload_time or limit, limit))
        return video

    @property
    def _ytdl(self) -> CachedYoutubeDL:
        thread = threading.current_thread()
        client = self._ytdl_instances.get(thread) or CachedYoutubeDL({
            "quiet": True,
            "extract_flat": "in_playlist",
            "ignore_no_formats_error": True,  # Don't fail on premiering vids
            "compat_opts": ["no-youtube-unavailable-videos"],
            "extractor_args": {
                # This client has the HLS manifests, no need for others
                "youtube": {"player_client": ["ios"]},
                # Retrieve upload dates in flat playlists
                "youtubetab": {"approximate_date": ["timestamp"]},
            },
        })
        self._ytdl_instances[thread] = client
        return client

    async def _channel(
        self, path: str, tab: str, search: str, page: int,
    ) -> Channel:
        base_path = path
        path += f"/search?query={quote_plus(search)}" if search else f"/{tab}"
        try:
            # featured tab only returns channel banner with postprocessing
            data, _ = await self._get(path, page, process=tab == "featured")
        except yt_dlp.DownloadError as e:
            log.warning("%s", e)
            path = base_path + "/featured"
            data, _ = await self._get(path, page, process=True)
            channel = Channel.model_validate(data)
            channel.entries.clear()
            return channel
        else:
            return Channel.model_validate(data)

    def _process_entries(self, url: str, data: RawData, page: int) -> RawData:
        tabs = [f"/{name}?" for name in Channel.tabs]
        in_featured = URL(url).path.endswith("/featured")
        entries: Iterable[RawData] = data["entries"]
        gathered: list[RawData] = []
        nth = 1
        page_now = 1
        got_page_data = False

        def process(entry: RawData) -> RawData:
            extra: RawData = {"nth": nth}

            if "/shorts/" in entry["url"]:
                etype = ShortEntry
            elif "/channel/" in entry["url"]:
                etype = ChannelEntry
            elif "/playlist?" in entry["url"]:
                etype = PlaylistEntry
                if in_featured:
                    etype = FeaturedChannelPlaylist
                extra["id"] = entry.get("id") or \
                    parse_qs(URL(entry["url"]).query)["list"][-1]
            elif any(name in entry["url"] for name in tabs):
                etype = FeaturedChannelTab
            elif "concurrent_view_count" in entry:
                etype = PartialEntry
            else:
                etype = VideoEntry

            extra["entry_type"] = etype.__name__
            return entry | extra

        class Interrupt(Exception):
            ...

        def interrupt(_: YtdlpRequest) -> None:
            nonlocal page_now
            nonlocal got_page_data
            if got_page_data:
                page_now += 1
                got_page_data = False
            if page_now > page:
                raise Interrupt

        with suppress(Interrupt), self._ytdl.before_requests(interrupt):
            for entry in entries:
                got_page_data = True
                if page_now == page:
                    gathered.append(process(entry))
                nth += 1

        return data | {"entries": gathered}

    async def _get(
        self,
        path: str,
        page: int = 1,
        process: bool = False,
        skip_cache: bool = False,
    ) -> tuple[RawData, ExpireIn]:

        loop = asyncio.get_event_loop()
        url = f"https://youtube.com/{path}"

        @backoff.on_exception(backoff.expo, NoDataReceived, max_tries=10)
        def task():
            with self._ytdl.adjust_cache_expiration() as expire_in:
                with self._ytdl.skip_cache(skip_cache):
                    if (data := self._ytdl.extract_info(
                        url, process=process, download=False,
                    )) is None:
                        raise NoDataReceived

                if "entries" not in data:
                    return (data, expire_in)
                return (self._process_entries(url, data, page), expire_in)

        async with max_parallel_requests(url):
            return await loop.run_in_executor(self._pool, task)


YTDLP = YtdlpClient()
