# Copyright Insidious authors <https://github.com/xrun1/insidious>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from abc import abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from insidious.net import HTTPX_BACKOFF_ERRORS, HttpClient

from .data import Comments

if TYPE_CHECKING:
    import httpx

    from .data import (
        Channel,
        Comments,
        Playlist,
        Search,
        Video,
    )
    from .filters import SearchFilter


class ClientUnavailable(RuntimeError):
    pass


@dataclass
class YoutubeClient:
    async def search(
        self, query: str, filter: SearchFilter | None = None, page: int = 1,
    ) -> Search:
        raise NotImplementedError

    async def channel(
        self, id: str, tab: str = "featured", search: str = "", page: int = 1,
    ) -> Channel:
        raise NotImplementedError

    async def named_channel(
        self,
        name: str, tab: str = "featured", search: str = "", page: int = 1,
    ) -> Channel:
        raise NotImplementedError

    async def user(
        self, id: str, tab: str = "featured", search: str = "", page: int = 1,
    ) -> Channel:
        raise NotImplementedError

    async def playlist(self, id: str, page: int = 1) -> Playlist:
        raise NotImplementedError

    async def hashtag(self, tag: str, page: int = 1) -> Playlist:
        raise NotImplementedError

    async def video(self, id: str) -> Video:
        raise NotImplementedError

    async def comments(self, video_id: str, by_date: bool = False) -> Comments:
        raise NotImplementedError


@dataclass
class APIInstance:
    url: str
    last_error: datetime = \
        field(default_factory=lambda: datetime.fromtimestamp(0))

    def fail(self) -> None:
        self.last_error = datetime.now()

    @property
    def has_recent_error(self) -> bool:
        return self.last_error >= datetime.now() - timedelta(hours=1)


@dataclass
class APIClient(YoutubeClient):
    _sites_check: ClassVar[datetime] = datetime.fromtimestamp(0)
    _sites: ClassVar[deque[APIInstance]] = deque()
    _httpx: ClassVar[httpx.AsyncClient] = HttpClient(follow_redirects=True)

    @classmethod
    @abstractmethod
    async def _get_api_instances(cls) -> list[APIInstance]:
        ...

    @classmethod
    async def _api(cls) -> APIInstance:
        now = datetime.now()

        if cls._sites_check < now - timedelta(hours=6):
            try:
                cls._sites = deque(await cls._get_api_instances())
            except Exception as e:
                raise ClientUnavailable("Couldn't get instances") from e

            cls._sites_check = datetime.now()

        if not cls._sites:
            raise ClientUnavailable("No usable instances found")

        i = 0
        while cls._sites[0].has_recent_error:
            cls._sites.append(cls._sites.popleft())
            if i >= len(cls._sites):
                raise ClientUnavailable("All instances are failing")
            i += 1

        return cls._sites[0]
