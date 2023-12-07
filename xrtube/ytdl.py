import asyncio
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from enum import Enum, auto
from functools import lru_cache, partial
from typing import Annotated, Any, Literal, TypeVar
from fastapi.datastructures import URL

from pydantic import BaseModel, Field
from yt_dlp import YoutubeDL

EntryT = TypeVar("EntryT", bound="Entry")


class LiveStatus(Enum):
    not_live = auto()
    is_upcoming = auto()
    is_live = auto()
    post_live = auto()  # was live, but VOD is not yet processed
    was_live = auto()


class Thumbnail(BaseModel):
    url: str
    width: int
    height: int

    @property
    def fixed_url(self) -> str:
        return f"https://{self.url}" if self.url.startswith("/") else self.url


class Entry(BaseModel):
    id: str
    url: str
    title: str
    thumbnails: list[Thumbnail]

    def thumb_for(self, width: int) -> Thumbnail:
        for thumb in sorted(self.thumbnails, key=lambda t: t.width):
            if thumb.width >= width:
                return thumb
        return self.thumbnails[0]


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
    uploader_id: str
    uploader_name: str = Field(alias="uploader")
    uploader_url: str
    live_status: LiveStatus | None
    live_watching: int | None = \
        Field(alias="concurrent_view_count", default=None)


class ChannelEntry(Entry):
    entry_type: Literal["ChannelEntry"]
    uploader: str
    uploader_id: str
    uploader_url: str
    followers: int = Field(alias="channel_follower_count")


class Video(VideoEntry):
    upload_date: str


class Entries(BaseModel, Sequence[EntryT]):
    entries: list[EntryT]

    def __getitem__(self, index: int) -> EntryT:
        return self.entries[index]

    def __len__(self) -> int:
        return len(self.entries)


class SearchResults(Entries[Entry]):
    entries: list[Annotated[
        ShortEntry | VideoEntry | ChannelEntry,
        Field(discriminator="entry_type")
    ]]


class Playlist(Entries[ShortEntry | VideoEntry]):
    id: str


@lru_cache(64)
class YoutubeClient:
    _executor = ThreadPoolExecutor(max_workers=16)

    def __init__(
        self,
        per_page: int = 12,
        offset: int = 0,
    ) -> None:
        self._ytdl = YoutubeDL({
            "playliststart": offset + 1,
            "playlistend": offset + per_page,
            "extract_flat": "in_playlist",
            "compat_opts": ["no-youtube-unavailable-videos"],
            "extractor_args": {
                "youtube": {
                    "skip": ["hls", "dash"],
                    "player_client": ["web"],
                },
            },
        })

    def convert_url(self, url: URL) -> URL:
        return url.replace(scheme="https", hostname="youtube.com", port=None)

    async def search(self, url: URL | str) -> SearchResults:
        data = self._extend_entries(await self._get(url))
        return SearchResults.parse_obj(data)

    async def playlist(self, url: URL | str) -> Playlist:
        return Playlist.parse_obj(await self._get(url))

    async def video(self, url: URL | str) -> Video:
        return Video.parse_obj(await self._get(url))

    async def _get(self, url: URL | str) -> dict[str, Any]:
        func = partial(self._ytdl.extract_info, str(url), download=False)
        return await self._thread(func)

    def _extend_entries(self, data: dict[str, Any]) -> dict[str, Any]:
        def extend(entry: dict[str, Any]) -> dict[str, Any]:
            if "/shorts/" in entry["url"]:
                etype = ShortEntry.__name__
            elif "/channel/" in entry["url"]:
                etype = ChannelEntry.__name__
            else:
                etype = VideoEntry.__name__

            return entry | {"entry_type": etype}

        return data | {"entries": [extend(e) for e in data["entries"]]}

    @classmethod
    def _thread(cls, *args, **kwargs) -> asyncio.Future:
        exe = cls._executor
        return asyncio.get_event_loop().run_in_executor(exe, *args, **kwargs)
