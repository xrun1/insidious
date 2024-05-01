from __future__ import annotations

import asyncio
import logging as log
import math
import random
import re
from collections import Counter, deque
from dataclasses import dataclass, field
from itertools import islice
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Self, TypeVar
from urllib.parse import quote
from uuid import UUID, uuid4

from typing_extensions import override
from yt_dlp.utils import DownloadError

from .extractors.data import (
    Playlist,
    PlaylistEntry,
    Search,
    SearchLink,
    ShortEntry,
    VideoEntry,
)
from .extractors.ytdlp import (
    YoutubeClient,
)
from .utils import report

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi import Request
    from fastapi.datastructures import URL

T = TypeVar("T")
NON_WORD_CHARS = re.compile(r"\W+")


class Extender(YoutubeClient):
    @override
    @staticmethod
    def convert_url(url: URL) -> URL:
        params = ("page", "pagination_id", "per_page", "find_attr")
        return YoutubeClient.convert_url(url).remove_query_params(params)


@dataclass(slots=True)
class Pagination(Generic[T]):
    _instances: ClassVar[dict[UUID, Self]] = {}

    request: Request
    id: UUID
    page: int = 0
    per_page: int = 12
    find_attr: tuple[str, Any] | None = None
    continuation_id: str | None = None

    found_item: T | None = None

    _data: deque[T] = field(default_factory=deque)
    _done: bool = False

    def __post_init__(self) -> None:
        self._instances[self.id] = self

    @property
    def done(self) -> bool:
        return self._done

    @done.setter
    def done(self, value: bool) -> None:
        self._done = value
        if value:
            self._instances.pop(self.id, None)
        else:
            self._instances[self.id] = self

    @property
    def items(self) -> list[T]:
        return list(islice(self._data, 0, self.per_page))

    @property
    def needs_more_data(self) -> bool:
        return not self._data and not self.done

    @property
    def running_short(self) -> bool:
        return len(self._data) <= self.per_page and not self.done

    @property
    def finding(self) -> bool:
        return bool(self.find_attr and not self.found_item)

    @property
    def next_url(self) -> URL | None:
        if self.done:
            return None
        params = {k: v for k, v in {
            "page": self.page,
            "pagination_id": self.id,
            "continuation_id": self.continuation_id,
        }.items() if v is not None}
        return self.request.url.include_query_params(**params)

    @property
    def extender(self) -> Extender:
        return self.extender_with(self.per_page)

    def extender_with(self, per_page: int) -> Extender:
        return Extender(page=self.page, per_page=per_page)

    def advance(self) -> Self:
        for _ in range(min(len(self._data), self.per_page)):
            self._data.popleft()
        return self

    def add(self, items: Sequence[T]) -> Self:
        if not items:
            self.done = True
            return self

        if self.finding:
            assert self.find_attr
            attr, value = self.find_attr
            for item in items:
                if getattr(item, attr, None) == value:
                    self.found_item = item
                    break

        self._data += items
        self.page += 1
        return self

    def reset(self) -> None:
        self._data.clear()
        self.page = 1
        self.done = False

    @classmethod
    def get(cls, request: Request) -> Self:
        id = UUID(request.query_params.get("pagination_id") or str(uuid4()))
        page = max(1, int(request.query_params.get("page") or 1))
        kws = {}

        if (per_page := request.query_params.get("per_page")):
            kws["per_page"] = max(1, int(per_page))

        if (cid := request.query_params.get("continuation_id")):
            kws["continuation_id"] = cid

        find = request.query_params.get("find_attr") or None
        if isinstance(find, str):
            attr, value = find.split(":", 1)
            find = (attr, value)

        if id in cls._instances:
            return cls._instances[id]

        return cls(request, id, page, **kws, find_attr=find)


@dataclass(slots=True)
class Related:
    entry: ShortEntry | VideoEntry
    found_times: int = 1
    weight: float = 1
    earliest_playlist_position: float = 0  # 0-1 percentage

    def _cmp_key(self, found_times: int) -> tuple[float, int, float]:
        return (self.weight, found_times, random.random())  # noqa: S311

    def __lt__(self, b: Related) -> bool:
        vid_or_channel_somewhere_in_playlist = 3
        if max(self.weight, b.weight) < vid_or_channel_somewhere_in_playlist:
            return self._cmp_key(0) < b._cmp_key(0)
        return self._cmp_key(self.found_times) < b._cmp_key(b.found_times)


@dataclass(slots=True)
class RelatedPagination(Pagination[ShortEntry | VideoEntry]):
    returned_videos_id: set[str] = field(default_factory=set)
    current_batch: dict[str, Related] = field(default_factory=dict)
    batch_playlists: dict[str, tuple[PlaylistEntry, float]] = \
        field(default_factory=dict)

    @property
    def video_id(self) -> str:
        return self.request.query_params["video_id"]

    @property
    def video_name(self) -> str:
        return self.request.query_params["video_name"]

    @property
    def cleaned_video_name(self) -> str:
        return NON_WORD_CHARS.sub(" ", self.video_name).strip() or \
            self.video_name

    @property
    def uploader_id(self) -> str | None:
        return self.request.query_params.get("uploader_id")

    @property
    def channel_name(self) -> str | None:
        return self.request.query_params.get("channel_name")

    @property
    def channel_url(self) -> str | None:
        return self.request.query_params.get("channel_url")

    def on_videos(self, entries: Playlist | Search, weight: float = 1) -> None:
        """Process the videos in a playlist or search results."""
        exclude = bump = add = ignore = 0
        # Playlists that got their weight slashed for having most of their vids
        # from same uploader are often parts of a series, promote only the 1st
        weight += 1

        for i, entry in enumerate(entries.entries):
            if isinstance(entry, SearchLink):
                ignore += 1
            elif entry.id == self.video_id or \
                    entry.id in self.returned_videos_id:
                exclude += 1
            elif entry.id in self.current_batch:
                bump += 1
                result = self.current_batch[entry.id]
                pos = result.earliest_playlist_position

                result.found_times += 1
                result.weight = max(result.weight, weight)
                result.earliest_playlist_position = min(pos, i / len(entries))
            elif isinstance(entry, ShortEntry | VideoEntry):
                add += 1
                self.current_batch[entry.id] = Related(
                    entry,
                    weight = weight,
                    earliest_playlist_position = i / len(entries),
                )
            else:
                ignore += 1

            if i == 0:
                weight -= 1

        log.info("Related: exclude %d, bump %d, add %d, ignore %d from %r",
                 exclude, bump, add, ignore, entries.title)
        # for r in self.current_batch.values():
            # print("Related:", r.entry.title, r.weight, r.found_times)

    async def on_list_entry(self, e: PlaylistEntry, weight: float = 1) -> None:
        """Load details and videos of a playlist found in search results."""
        with report(DownloadError):
            playlist = await self.extender_with(per_page=100).playlist(e.url)
            common_channels = Counter(
                e.channel_url for e in playlist
                if not isinstance(e, ShortEntry)
            ).most_common()

            if common_channels and common_channels[0][1] > len(playlist) * 0.7:
                msg = "Related: playlist %r has >70%% of its content from %r"
                log.info(msg, playlist.title, common_channels[0][0])
                weight /= 2
            # These 2 elifs are not 100% accurate because the playlist could
            # contain self.video_name, but past the first 100 entries we load
            elif any(e.id == self.video_id for e in playlist):
                msg = "Related: playlist %r has %r"
                log.info(msg, playlist.title, self.video_name)
                weight = 4
            elif any(isinstance(e, VideoEntry) and self.channel_url and
                     e.channel_url == self.channel_url for e in playlist):
                msg = "Related: playlist %r has a video from %r's channel"
                log.info(msg, playlist.title, self.video_name)
                weight = 3

            self.on_videos(playlist, weight)

    async def find_playlists(self, addition: str = "") -> None:
        """Search site-wide for playlists related to the watched video."""
        query = self.cleaned_video_name
        weight = 1
        if addition:
            query += " " + addition
            weight = 2

        url = "https://www.youtube.com/results?search_query={}&sp=EgIQAw%3D%3D"
        url = url.format(quote(query))

        with report(DownloadError):
            got = await self.extender_with(per_page=3).search(url)
            log.info("Related: found %d playlists for %r", len(got), url)

            for entry in got.entries:
                if isinstance(entry, PlaylistEntry):
                    self.batch_playlists[entry.url] = (entry, weight)  # dedup

    async def process_playlists(self) -> None:
        """Register deduplicated by dictionary playlists previously found."""
        async with asyncio.TaskGroup() as tg:
            for entry, weight in self.batch_playlists.values():
                tg.create_task(self.on_list_entry(entry, weight))

    async def find_channel_videos(self) -> None:
        """Search the watched video's source channel for similar videos."""
        if not self.channel_url:
            log.info("Related: no channel URL for %r", self.video_name)
            return

        # TODO: better handle spaceless languages
        words = self.cleaned_video_name.strip().split()
        query = " ".join(words[:math.ceil(len(words) / 2)])
        url = self.channel_url + "/search?query=" + quote(query)

        # NOTE: Failure on "- Topic" auto-generated channels is expected
        with report(DownloadError):
            got = await self.extender.search(url)
            log.info("Related: found %d channel videos for %r", len(got), url)
            self.on_videos(got, weight=3)

    async def find_videos_basic(self) -> None:
        """Search the site for similar videos"""
        query = self.cleaned_video_name
        url = "https://www.youtube.com/results?search_query=%s" % quote(query)

        with report(DownloadError):
            got = await self.extender.search(url)
            log.info("Related: found %d videos from %r", len(got), url)
            self.on_videos(got, weight=0.5)

    def finish_batch(self) -> Self:
        """Commit all fetched results to data, will remove previous page."""
        log.info("Related: got %d results for %r, page %d",
                 len(self.current_batch), self.video_name, self.page)

        by_score = sorted(self.current_batch.values())
        self.add([related.entry for related in reversed(by_score)])
        self.current_batch.clear()
        self.batch_playlists.clear()
        return self

    async def find(self) -> Self:
        """Try finding videos related to another video V.

        Five requests are combined, from most to least promoted:
        - Fuzzy search with half of V's title on the uploader's channel
        - Site-wide search for playlists that *probably* contain V:
          V's title + channel name
        - Same, but V's title + author's user ID
        - Same, but just V's title (fuzzier and less promoted)
        - Basic site-wide search with the video name

        If a playlists's first 100 loaded entries contain a video from V's
        uploader, it gets heavier promotion; and even more if it has V itself.
        Playlists where most of the content is from the same uploader get
        demoted for being lacking variety and often being parts of one series
        with all of the same thubnails.
        """
        if not self.needs_more_data:
            return self
        log.info("Related: getting page %d for %r", self.page, self.video_name)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.find_channel_videos())
            tg.create_task(self.find_videos_basic())

            channel = (self.channel_name or "").strip()
            uploader = (self.uploader_id or "").removeprefix("@").strip()
            if channel.lower() == uploader.lower():
                uploader = channel

            async with asyncio.TaskGroup() as tg2:
                for addition in tuple({channel, uploader, ""}):
                    tg2.create_task(self.find_playlists(addition))

            tg.create_task(self.process_playlists())

        return self.finish_batch()
