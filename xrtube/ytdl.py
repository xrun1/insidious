import asyncio
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from enum import auto
from functools import lru_cache, partial
from typing import Annotated, Any, Literal, TypeVar
from urllib.parse import quote

import backoff
from fastapi.datastructures import URL
from pydantic import BaseModel, Field
from yt_dlp import YoutubeDL

from .utils import AutoStrEnum, int_ratio

EntryT = TypeVar("EntryT", bound="Entry")


class LiveStatus(AutoStrEnum):
    not_live = auto()
    is_upcoming = auto()
    is_live = auto()
    post_live = auto()  # was live, but VOD is not yet processed
    was_live = auto()


class Thumbnail(BaseModel):
    url: str
    width: int | None
    height: int | None

    @property
    def fixed_url(self) -> str:
        return f"https://{self.url}" if self.url.startswith("/") else self.url


class Format(BaseModel):
    name: str | None = Field(alias="format_note")
    url: str
    filesize: int | None
    manifest_url: str | None
    width: int | None
    height: int | None
    fps: float | None

    @property
    def fixed_manifest_url(self) -> str | None:
        if self.manifest_url:
            return "/proxy/get?url=" + quote(self.manifest_url)
        return None


class Entry(BaseModel):
    id: str
    url: str
    title: str
    thumbnails: list[Thumbnail] = Field(default_factory=list)

    @property
    def poster(self) -> Thumbnail:
        bad = Thumbnail(url="/404", width=0, height=0)
        return max(self.thumbnails, default=bad, key=lambda t: t.width or 0)

    def thumb_for(self, width: int) -> Thumbnail:
        for thumb in sorted(self.thumbnails, key=lambda t: t.width or 0):
            if thumb.width or 0 >= width:
                return thumb

        bad = Thumbnail(url="/404", width=0, height=0)
        return self.thumbnails[0] if len(self.thumbnails) else bad


class ShortEntry(Entry):
    entry_type: Literal["ShortEntry"]
    views: int = Field(alias="view_count")


class VideoEntry(ShortEntry):
    entry_type: Literal["VideoEntry"]
    description: str | None
    duration: int
    channel_id: str
    channel_name: str = Field(alias="channel")
    channel_url: str
    uploader_id: str | None
    uploader_name: str = Field(alias="uploader")
    uploader_url: str | None
    live_status: LiveStatus | None
    live_watching: int | None = \
        Field(alias="concurrent_view_count", default=None)


class PlaylistEntry(Entry):
    entry_type: Literal["PlaylistEntry"]


class ChannelEntry(Entry):
    entry_type: Literal["ChannelEntry"]
    uploader: str
    uploader_id: str
    uploader_url: str
    followers: int = Field(alias="channel_follower_count")


class Entries(BaseModel, Sequence[EntryT]):
    title: str = ""
    entries: list[EntryT] = Field(default_factory=list)

    def __getitem__(self, index: int) -> EntryT:
        return self.entries[index]

    def __len__(self) -> int:
        return len(self.entries)


class Search(Entries[Entry]):
    entries: list[Annotated[
        ShortEntry | VideoEntry | ChannelEntry | PlaylistEntry,
        Field(discriminator="entry_type")
    ]] = Field(default_factory=list)


class Video(VideoEntry):
    entry_type: Literal["Video"] = "Video"
    url: str = Field(alias="original_url")
    width: int
    height: int
    upload_date: str
    formats: list[Format]

    @property
    def fixed_manifest_url(self) -> str | None:
        gen = (f.fixed_manifest_url for f in self.formats)
        return next((f for f in gen if f), None)

    @property
    def player_ratio(self) -> str:
        w, h = int_ratio(self.width, self.height)
        return f"{w}:{h}"


class Playlist(Entries[ShortEntry | VideoEntry]):
    id: str
    entries: list[Annotated[
        ShortEntry | VideoEntry,
        Field(discriminator="entry_type")
    ]] = Field(default_factory=list)


class NoDataReceived(Exception):
    """ytdlp failed to return any data after retrying"""


@lru_cache(64)
class YoutubeClient:
    _executor = ThreadPoolExecutor(max_workers=16)

    def __init__(
        self,
        page: int = 1,
        per_page: int = 12,
    ) -> None:
        offset = per_page * (page - 1)
        self._ytdl = YoutubeDL({
            "quiet": True,
            "playliststart": offset + 1,
            "playlistend": offset + per_page,
            "extract_flat": "in_playlist",
            "compat_opts": ["no-youtube-unavailable-videos"],
            "extractor_args": {
                "youtube": {
                    "player_client": ["ios"],  # gives HLS format
                },
            },
        })

    def convert_url(self, url: URL) -> URL:
        return url.replace(scheme="https", hostname="youtube.com", port=None)

    async def search(self, url: URL | str) -> Search:
        return Search.parse_obj(await self._get(url))

    async def playlist(self, url: URL | str) -> Playlist:
        return Playlist.parse_obj(await self._get(url))

    async def video(self, url: URL | str) -> Video:
        return Video.parse_obj(await self._get(url))

    @backoff.on_exception(backoff.expo, NoDataReceived, max_tries=10)
    async def _get(self, url: URL | str) -> dict[str, Any]:
        func = partial(self._ytdl.extract_info, str(url), download=False)
        if (data := await self._thread(func)) is None:
            raise NoDataReceived
        return self._extend_entries(data)

    def _extend_entries(self, data: dict[str, Any]) -> dict[str, Any]:
        def extend(entry: dict[str, Any]) -> dict[str, Any]:
            if "/shorts/" in entry["url"]:
                etype = ShortEntry.__name__
            elif "/channel/" in entry["url"]:
                etype = ChannelEntry.__name__
            elif "/playlist?" in entry["url"]:
                etype = PlaylistEntry.__name__
            else:
                etype = VideoEntry.__name__
            return entry | {"entry_type": etype}

        return data | {"entries": [extend(e) for e in data.get("entries", [])]}

    @classmethod
    def _thread(cls, *args, **kwargs) -> asyncio.Future:
        exe = cls._executor
        return asyncio.get_event_loop().run_in_executor(exe, *args, **kwargs)
