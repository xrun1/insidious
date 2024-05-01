from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging as log
import threading
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import auto
from pathlib import Path
from typing import (
    Annotated,
    Any,
    ClassVar,
    Literal,
    Self,
    TypeAlias,
    TypeVar,
    overload,
)
from urllib.parse import parse_qs, quote

import appdirs
import backoff
import lz4.frame
import yt_dlp
from fastapi.datastructures import URL
from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    field_validator,
)
from typing_extensions import override
from yt_dlp import YoutubeDL
from yt_dlp.networking.common import (
    Request as YtdlpRequest,
    Response as YtdlpResponse,
)
from yt_dlp.utils import math

from . import NAME
from .utils import AutoStrEnum

T = TypeVar("T")

MAX_CACHE_TIME = 60 * 60
CACHE_DIR = Path(appdirs.user_cache_dir(NAME))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
ExpireIn: TypeAlias = Callable[[float], None]


class NoDataReceived(yt_dlp.utils.ExtractorError):
    def __init__(self) -> None:
        super().__init__("Failed to gather any data from origin site")


class LiveStatus(AutoStrEnum):
    is_upcoming = auto()
    is_live = auto()
    post_live = auto()  # was live, but VOD is not yet processed
    was_live = auto()
    not_live = auto()


class Thumbnail(BaseModel):
    url: str
    id: str | None = None
    width: int | None = None
    height: int | None = None
    preference: int = 0

    @property
    def fixed_url(self) -> str:
        if self.url == "/404":
            return self.url
        url = f"https:{self.url}" if self.url.startswith("//") else self.url
        return f"/proxy/get?url={quote(url)}"

    @property
    def suffix(self) -> str | None:
        if "." not in (path := URL(self.url).path):
            return None
        return path.split(".")[-1]

    @property
    def srcset(self) -> str:
        return f"{self.fixed_url} {self.width or 0}w"


class HasThumbnails(BaseModel):
    has_banner: ClassVar[bool] = False
    thumbnails: list[Thumbnail] = Field(default_factory=list)

    @property
    def best_thumbnail(self) -> Thumbnail:
        return next(iter(self._best_thumbnails()), Thumbnail(url="/404"))

    @property
    def thumbnails_srcset(self) -> str:
        return ", ".join(reversed([t.srcset for t in self._best_thumbnails()]))

    @property
    def banners_srcset(self) -> str:
        return ", ".join([t.srcset for t in self._best_thumbnails(True)][::-1])

    def _best_thumbnails(self, banners: bool = False) -> list[Thumbnail]:
        thumbs = self.thumbnails

        if self.has_banner:
            thumbs = [t for t in thumbs if banners == (t.preference < 0)]

        thumbs = (
            [t for t in thumbs if t.suffix == "webp" and t.width] or
            [t for t in thumbs if t.width] or
            [t for t in thumbs if t.suffix == "webp"] or
            thumbs
        )
        thumbs.sort(key=lambda t: t.width or 0, reverse=True)
        return thumbs


class HasHoverThumbnails(BaseModel):
    id: str

    @property
    def hover_srcsets(self) -> list[str]:
        return [
            ", ".join(quality.srcset for quality in nth)
            for nth in reversed(self._hover_thumbnails())
        ]

    def _hover_thumbnails(self) -> list[list[Thumbnail]]:
        def url(q: str, id: int) -> str:
            return f"https://i.ytimg.com/vi/{self.id}/{q}{id}.jpg"

        return [[
            Thumbnail(url=url("hq", id), width=480, height=360),
            Thumbnail(url=url("mq", id), width=320, height=180),
            Thumbnail(url=url("", id), width=120, height=90),
        ] for id in (1, 2, 3)]


class HasChannel(BaseModel):
    channel_id: str | None = None
    channel_name: str | None = Field(None, alias="channel")
    channel_url: str | None = None
    channel_followers: int | None = \
        Field(default=None, alias="channel_follower_count")
    uploader_id: str | None = None
    uploader_name: str | None = Field(None, alias="uploader")
    uploader_url: str | None = None

    @property
    def shortest_channel_url(self) -> str | None:
        if not self.uploader_url:
            return self.channel_url
        if not self.channel_url:
            return None
        return min((self.channel_url, self.uploader_url), key=len)


class Fragments(BaseModel):
    url: str | None = None
    path: str | None = None
    duration: float | None = None


class Format(BaseModel):
    id: str = Field(alias="format_id")
    name: str | None = Field(None, alias="format_note")
    protocol: str
    url: str
    manifest_url: str | None = None
    dash_fragments_base_url: str | None = \
        Field(None, alias="fragment_base_url")
    fragments: list[Fragments] = Field(alias="fragments", default_factory=list)
    rows: int | None = None
    columns: int | None = None
    filesize: int | None = None
    container: str | None = None
    video_codec: str | None = Field(None, alias="vcodec")
    audio_codec: str | None = Field(None, alias="acodec")
    average_bitrate: float | None = Field(None, alias="tbr")  # in KB/s
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    dynamic_range: str | None = None
    audio_channels: int | None = None
    language: str | None = None

    @property
    def has_dash(self) -> bool:
        return self.protocol == "http_dash_segments"

    @property
    def vcodec(self) -> str | None:
        if self.video_codec == "none":
            return None
        return self.video_codec or None

    @property
    def acodec(self) -> str | None:
        if self.audio_codec == "none":
            return None
        return self.audio_codec or None


class Chapter(BaseModel):
    start_sec: float = Field(alias="start_time")
    end_sec: float = Field(alias="end_time")
    title: str


class Entry(HasThumbnails):
    id: str
    url: str
    title: str
    nth: int | None = None


class ShortEntry(Entry, HasHoverThumbnails):
    entry_type: Literal["ShortEntry"]
    views: int = Field(alias="view_count")


class VideoEntry(Entry, HasHoverThumbnails, HasChannel):
    entry_type: Literal["VideoEntry"]
    views: int | None = Field(None, alias="view_count")
    description: str | None = None
    duration: float | None = None
    upload_date: datetime | None = \
        Field(None, validation_alias=AliasChoices("timestamp", "upload_date"))
    live_status: LiveStatus | None = None
    live_release_date: datetime | None = Field(None, alias="release_timestamp")

    @field_validator("upload_date", mode="before")
    @classmethod
    def parse_upload_date(cls, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, int):
            return datetime.fromtimestamp(value)
        return datetime.strptime(value, "%Y%m%d")

    @property
    def release_date(self) -> datetime | None:
        return self.live_release_date or self.upload_date

    @property
    def fully_released(self) -> bool:
        partial = (LiveStatus.is_upcoming, LiveStatus.is_live)
        return self.live_status not in partial

    @property
    def metadata_reload_time(self) -> int | None:
        if not self.release_date:
            return None
        delta = datetime.utcnow() - self.release_date.replace(tzinfo=None)
        if delta.days > 3:  # noqa: PLR2004
            return None
        return max(60, math.ceil(delta.total_seconds() / (60 * 12)))

    @property
    def dislikes_url(self) -> str:
        return "/dislikes?video_id=%s" % self.id


class PartialEntry(VideoEntry):
    entry_type: Literal["PartialEntry"]  # type: ignore
    duration: float | None = None
    views: int | None = Field(None, alias="concurrent_view_count")


class PlaylistEntry(Entry):
    entry_type: Literal["PlaylistEntry"]

    @property
    def load_url(self) -> str | None:
        return "/load_playlist_entry?url=%s" % quote(self.url)


class ChannelEntry(Entry):
    entry_type: Literal["ChannelEntry"]
    uploader: str
    uploader_id: str
    uploader_url: str
    followers: int | None = Field(None, alias="channel_follower_count")

    @property
    def shortest_url(self) -> str | None:
        return min((self.url, self.uploader_url), key=len)


# NOTE: Inherit Sequence first to avoid BaseModel overriding __iter__
class Entries(Sequence[T], BaseModel):
    title: str = ""
    entries: list[T] = Field(default_factory=list)

    @overload
    def __getitem__(self, index: int) -> T: ...
    @overload
    def __getitem__(self, index: slice) -> list[T]: ...
    @override
    def __getitem__(self, index: int | slice) -> T | list[T]:
        return self.entries[index]

    @override
    def __len__(self) -> int:
        return len(self.entries)


class SearchLink(BaseModel):
    entry_type: Literal["SearchLink"]
    url: str
    title: str

    @property
    def load_url(self) -> str:
        params = (quote(self.url), quote(self.title))
        return "/load_search_link?url=%s&title=%s" % params


InSearch: TypeAlias = (
    ShortEntry | VideoEntry | PartialEntry | ChannelEntry | PlaylistEntry |
    SearchLink
)


class Search(Entries[InSearch]):
    url: str = Field(alias="original_url")
    entries: list[Annotated[InSearch, Field(discriminator="entry_type")]] = \
        Field(default_factory=list)


class Video(VideoEntry):
    entry_type: Literal["Video"] = "Video"  # type: ignore
    url: str = Field(alias="original_url")
    width: int | None = None
    height: int | None = None
    aspect_ratio: float | None = None
    fps: float | None = None
    likes: int | None = Field(alias="like_count")
    formats: list[Format]
    chapters: list[Chapter] | None = None
    clip_start: float | None = Field(None, alias="section_start")
    clip_end: float | None = Field(None, alias="section_end")

    @property
    def manifest_url(self) -> str:
        for fmt in self.formats:
            if fmt.manifest_url and not fmt.has_dash:
                return "/proxy/get?url=%s" % quote(fmt.manifest_url)
        return "/generate_hls/master?video_url=%s" % quote(self.url)

    @property
    def storyboard_url(self) -> str:
        return "/storyboard?video_url=%s" % quote(self.url)

    @property
    def chapters_url(self) -> str:
        return "/chapters?video_url=%s" % quote(self.url)

    @property
    def webvtt_storyboard(self) -> str:
        return "\n".join(self._webvtt_storyboard())

    @property
    def webvtt_chapters(self) -> str:
        return "\n".join(self._webvtt_chapters())

    @staticmethod
    def _vtt_time(s: float) -> str:
        h = s // 3600
        s -= h * 3600
        m = s // 60
        s -= m * 60
        return f"{h:02.0f}:{m:02.0f}:{s:06.3f}"  # e.g. 00:03:22.067

    def _webvtt_chapters(self) -> Iterator[str]:
        yield "WEBVTT"

        for i, chapter in enumerate(self.chapters or [], 1):
            end = self._vtt_time(chapter.end_sec)
            yield ""
            yield str(i)
            yield self._vtt_time(chapter.start_sec) + " --> " + end
            yield chapter.title

    def _webvtt_storyboard(self) -> Iterator[str]:
        yield "WEBVTT"

        variants = [f for f in self.formats if f.name == "storyboard"]
        sb = max(variants, key=lambda f: f.height or 0, default=None)
        if not sb or not sb.fragments:
            return

        frag_duration = sb.fragments[0].duration or 0
        sec_per_thumb = frag_duration / (sb.columns or 1) / (sb.rows or 1)
        max_sec = sum(f.duration or 0 for f in sb.fragments)
        now = 0

        for frag in sb.fragments:
            for row in range(sb.rows or 0):
                for col in range(sb.columns or 0):
                    end = now + sec_per_thumb
                    yield self._vtt_time(now) + " --> " + self._vtt_time(end)

                    xywh = ",".join(map(str, (
                        (sb.width or 0) * col,
                        (sb.height or 0) * row,
                        sb.width or 0,
                        sb.height or 0,
                    )))
                    yield f"/proxy/get?url={quote(frag.url or '')}#xywh={xywh}"

                    if (now := end) >= max_sec:
                        return


class PartialVideo(Video):
    views: int | None = Field(None, alias="concurrent_view_count")

    @property
    def releases_in(self) -> int | None:
        if self.live_status != LiveStatus.is_upcoming:
            return None
        if not self.live_release_date:
            return None
        delta = self.live_release_date - datetime.utcnow().replace(tzinfo=UTC)
        return math.ceil(max(3, delta.total_seconds()))


InPlaylist: TypeAlias = ShortEntry | VideoEntry | PartialEntry


class Playlist(
    PlaylistEntry, HasHoverThumbnails, HasChannel, Entries[InPlaylist],
):
    entry_type: Literal["Playlist"] = "Playlist"  # type: ignore
    url: str = Field(alias="original_url")
    description: str | None = Field(None)
    last_change: datetime | None = Field(None, alias="modified_date")
    views: int | None = Field(None, alias="view_count")
    total_entries: int | None = Field(None, alias="playlist_count")
    entries: list[Annotated[InPlaylist, Field(discriminator="entry_type")]] = \
        Field(default_factory=list)

    @field_validator("last_change", mode="before")
    @classmethod
    def parse_last_change(cls, value: Any) -> datetime | None:
        return None if value is None else datetime.strptime(value, "%Y%m%d")

    @property
    @override
    def banners_srcset(self) -> str:
        return ""  # this is just gonna be the upscaled first vid's thumbnail

    @property
    @override
    def load_url(self) -> str | None:
        return None

    @property
    @override
    def hover_srcsets(self) -> list[str]:
        if len(self) < 3:  # noqa: PLR2004
            return self[0].hover_srcsets
        return [entry.thumbnails_srcset for entry in self[1:6]]


InChannel: TypeAlias = InSearch


class Channel(Search, HasThumbnails):
    has_banner: ClassVar[bool] = True
    tabs: ClassVar[list[str]] = [
        "featured", "videos", "shorts", "streams", "playlists",
    ]

    id: str
    title: str = Field(alias="channel")
    description: str
    tab: str = Field(alias="webpage_url_basename", default="featured")
    followers: int | None = Field(None, alias="channel_follower_count")

    def tab_url(self, from_url: URL, to_tab: str) -> URL:
        path = from_url.path.rstrip("/")

        for tab in self.tabs:
            path = path.removesuffix(f"/{tab}")

        path = f"{path}/{to_tab}".removesuffix("/featured")
        return from_url.replace(path=path)


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
            expire = str(datetime.utcnow().timestamp() + seconds).encode()
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

            if datetime.utcnow() >= datetime.fromtimestamp(float(expire_ts)):
                return None

            access_ts = str(datetime.utcnow().timestamp()).encode()
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
        now = datetime.utcnow().timestamp()
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
        now = datetime.utcnow()
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
