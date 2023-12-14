import asyncio
import logging as log
import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import islice
from typing import ClassVar, Deque, Generic, Self, TypeVar
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.datastructures import URL

from .utils import report
from .ytdl import (
    NoDataReceived,
    Playlist,
    PlaylistEntry,
    Search,
    SearchLink,
    ShortEntry,
    VideoEntry,
    YoutubeClient,
)

T = TypeVar("T")

@dataclass(slots=True)
class Pagination(Generic[T]):
    _instances: ClassVar[dict[UUID, Self]] = {}

    request: Request
    id: UUID
    page: int = 0
    per_page: int = 12
    done: bool = False

    _data: Deque[T] = field(default_factory=deque)

    def __post_init__(self) -> None:
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
    def next_url(self) -> URL | None:
        if self.done:
            return None
        f = self.request.url.include_query_params
        return f(page=self.page, pagination_id=self.id)

    @property
    def extender(self) -> YoutubeClient:
        return self.extender_with(self.per_page)

    def extender_with(self, per_page: int) -> YoutubeClient:
        return YoutubeClient(page=self.page, per_page=per_page)

    def advance(self) -> Self:
        for _ in range(min(len(self._data), self.per_page)):
            self._data.popleft()
        return self

    def add(self, items: Sequence[T]) -> Self:
        if not items:
            self.done = True
            self._instances.pop(self.id, None)
            return self

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
        return cls._instances.get(id) or cls(request, id, page)


@dataclass(slots=True)
class Related:
    entry: ShortEntry | VideoEntry
    found_times: int = 1
    weight: float = 1

    @property
    def score(self) -> float:
        return self.found_times * self.weight


@dataclass(slots=True)
class RelatedPagination(Pagination[ShortEntry | VideoEntry]):
    vaguer_search: bool = False
    returned_videos_id: set[str] = field(default_factory=set)
    current_batch: dict[str, Related] = field(default_factory=dict)

    @property
    def video_id(self) -> str:
        return self.request.query_params["video_id"]

    @property
    def video_name(self) -> str:
        return self.request.query_params["video_name"]

    @property
    def channel_name(self) -> str:
        return self.request.query_params["channel_name"]

    @property
    def channel_url(self) -> str:
        return self.request.query_params["channel_url"]

    def on_videos(self, entries: Playlist | Search, weight: float = 1) -> None:
        """Process the videos in a playlist or search results."""
        exclude = bump = add = ignore = 0

        for entry in entries.entries:
            if isinstance(entry, SearchLink):
                ignore += 1
            elif entry.id == self.video_id or \
                    entry.id in self.returned_videos_id:
                exclude += 1
            elif entry.id in self.current_batch:
                bump += 1
                result = self.current_batch[entry.id]
                result.found_times += 1
                result.weight = max(result.weight, weight)
            elif isinstance(entry, ShortEntry | VideoEntry):
                add += 1
                self.current_batch[entry.id] = Related(entry)
            else:
                ignore += 1

        log.info("Related: exclude %d, bump %d, add %d, ignore %d from %r",
                 exclude, bump, add, ignore, entries.title)

    async def on_list_entry(self, e: PlaylistEntry, weight: float = 1) -> None:
        """Load details and videos of a playlist found in search results."""
        with report(NoDataReceived):
            playlist = await self.extender_with(per_page=100).playlist(e.url)
            self.on_videos(playlist, weight)

    async def find_playlists(self, explicit_channel: bool) -> None:
        """Search site-wide for playlists related to the watched video."""
        query = self.video_name
        weight = 1
        if explicit_channel:
            query += " " + self.channel_name
            weight *= 2

        url = "https://www.youtube.com/results?search_query={}&sp=EgIQAw%3D%3D"
        url = url.format(quote(query))

        with report(NoDataReceived):
            got = await self.extender_with(per_page=5).search(url)
            log.info("Related: found %d playlists for %r", len(got), url)

            async with asyncio.TaskGroup() as tg:
                for entry in got.entries:
                    if isinstance(entry, PlaylistEntry):
                        tg.create_task(self.on_list_entry(entry, weight))

    async def find_channel_videos(self) -> None:
        """Search the watched video's source channel for similar videos."""
        words = self.video_name.split()  # TODO: handle spaceless languages
        query = " ".join(words[:math.ceil(len(words)/2)])
        url = self.channel_url + "/search?query=" + quote(query)

        # NOTE: Failure on "- Topic" auto-generated channels is expected
        with report(NoDataReceived):
            got = await self.extender.search(url)
            log.info("Related: found %d channel videos for %r", len(got), url)
            self.on_videos(got, weight=2)

    def finish_batch(self) -> Self:
        """Commit all fetched results to data, will remove previous page."""
        log.info("Related: got %d results for %r, page %d",
                 len(self.current_batch), self.video_name, self.page)

        by_score = sorted(self.current_batch.values(), key=lambda r: r.score)
        self.add([related.entry for related in reversed(by_score)])
        self.current_batch.clear()
        return self

    async def find(self) -> Self:
        """Try finding videos related to another video X.

        First try to get a combination of similar videos from the uploader +
        videos from any playlist on the site that *probably* contains X.
        If there are no results or we run out, try to find playlists with a
        less explicit search, which is more likely to return unrelated stuff.
        """
        if not self.needs_more_data:
            return self
        log.info("Related: getting page %d for %r", self.page, self.video_name)

        if self.vaguer_search:
            await self.find_playlists(explicit_channel=False)
            return self.finish_batch()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.find_playlists(explicit_channel=True))
            tg.create_task(self.find_channel_videos())

        if not self.current_batch and not self.vaguer_search:
            log.info("Related: now using vague search for %r", self.video_name)
            self.reset()
            self.vaguer_search = True
            return await self.find()

        return self.finish_batch()
