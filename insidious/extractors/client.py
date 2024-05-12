# Copyright Insidious authors <https://github.com/xrun1/insidious>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .data import (
        Channel,
        Comments,
        Playlist,
        Search,
        Video,
    )
    from .filters import SearchFilter


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
