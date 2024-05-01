from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging as log
import threading
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
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
from urllib.parse import parse_qs

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

from .data import (
    Channel,
    ChannelEntry,
    PartialEntry,
    PartialVideo,
    Playlist,
    PlaylistEntry,
    Search,
    SearchLink,
    ShortEntry,
    Video,
    VideoEntry,
)

T = TypeVar("T")

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
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.newly_written: list[CacheFile] | None = None

    @override
    def urlopen(
        self, req: str | urllib.request.Request | YtdlpRequest,
    ) -> YtdlpResponse:

        if isinstance(req, str):
            req = YtdlpRequest(req)
        elif isinstance(req, urllib.request.Request):
            req = yt_dlp.compat.urllib_req_to_req(req)

        if (file := CacheFile.from_request(req)):
            if (resp := file.response()):
                return resp
            file.write(resp := super().urlopen(req), MAX_CACHE_TIME)
            if self.newly_written is not None:
                self.newly_written.append(file)
            return resp

        return super().urlopen(req)

    @contextmanager
    def adjust_cache_expiration(self) -> Iterator[ExpireIn]:
        # WARN: not threadsafe
        self.newly_written = batch = []

        def make_expire_in(seconds: float):
            for file in batch:
                file.expire_in(seconds)

        try:
            yield make_expire_in
        finally:
            self.newly_written = None

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
class YoutubeClient:
    _ytdl_instances: ClassVar[dict[tuple[int, int, int], CachedYoutubeDL]] = {}
    _pool: ClassVar[ThreadPoolExecutor] = ThreadPoolExecutor(max_workers=16)

    page: int = 1
    per_page: int = 12

    @property
    def headers(self) -> dict[str, str]:
        return self._ytdl.params["http_headers"]

    async def search(self, url: URL | str) -> Search:
        return Search.model_validate((await self._get(url))[0])

    async def channel(self, url: URL | str) -> Channel:
        return Channel.model_validate((await self._get(url))[0])

    async def playlist(self, url: URL | str) -> Playlist:
        pl = Playlist.model_validate((await self._get(url))[0])
        for i, entry in enumerate(pl, 1):
            entry.nth = self._offset + i
            entry.url = str(URL(entry.url).include_query_params(
                list = pl.id,
                index = entry.nth,
            ))
        return pl

    async def video(self, url: URL | str) -> Video:
        url = URL(str(url)).remove_query_params("list")
        data, expire_in = await self._get(url)

        if "concurrent_view_count" in data:
            video = PartialVideo.model_validate(data)
        else:
            video = Video.model_validate(data)

        limit = MAX_CACHE_TIME
        expire_in(min(video.metadata_reload_time or limit, limit))
        return video

    @backoff.on_exception(backoff.expo, NoDataReceived, max_tries=10)
    async def _get(self, url: URL | str) -> tuple[dict[str, Any], ExpireIn]:
        def task():
            with self._ytdl.adjust_cache_expiration() as expire_in:
                data = self._ytdl.extract_info(str(url), download=False)
                return (data, expire_in)

        data, expire_in = await self._thread(task)
        if data is None:
            raise NoDataReceived
        return (self._extend_entries(data), expire_in)

    @classmethod
    def _thread(cls, fn: Callable[[], T]) -> asyncio.Future[T]:
        return asyncio.get_event_loop().run_in_executor(cls._pool, fn)

    @staticmethod
    def convert_url(url: URL) -> URL:
        return url.replace(scheme="https", hostname="youtube.com", port=None)

    @property
    def _offset(self) -> int:
        return self.per_page * (self.page - 1)

    @property
    def _ytdl(self) -> CachedYoutubeDL:
        thread = threading.current_thread().native_id or -1
        client = self._ytdl_instances.get((self.page, self.per_page, thread))
        client = client or CachedYoutubeDL({
            "quiet": True,
            "playliststart": self._offset + 1,
            "playlistend": self._offset + self.per_page,
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
        self._ytdl_instances[self.page, self.per_page, thread] = client
        return client

    @staticmethod
    def _extend_entries(data: dict[str, Any]) -> dict[str, Any]:
        def extend(entry: dict[str, Any]) -> dict[str, Any]:
            data = {}
            tabs = [f"/{name}?" for name in Channel.tabs]
            if "/shorts/" in entry["url"]:
                etype = ShortEntry.__name__
            elif "/channel/" in entry["url"]:
                etype = ChannelEntry.__name__
            elif "/playlist?" in entry["url"]:
                etype = PlaylistEntry.__name__
                data["id"] = entry.get("id") or \
                    parse_qs(URL(entry["url"]).query)["list"][-1]
            elif any(name in entry["url"] for name in tabs):
                etype = SearchLink.__name__
            elif "concurrent_view_count" in entry:
                etype = PartialEntry.__name__
            else:
                etype = VideoEntry.__name__
            return entry | data | {"entry_type": etype}

        return data | {"entries": [extend(e) for e in data.get("entries", [])]}
