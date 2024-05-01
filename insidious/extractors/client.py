from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.datastructures import URL

    from .data import (
        Channel,
        Comments,
        Playlist,
        Search,
        Video,
    )


@dataclass
class YoutubeClient:
    async def search(self, url: URL | str) -> Search:
        raise NotImplementedError

    async def channel(self, url: URL | str) -> Channel:
        raise NotImplementedError

    async def playlist(self, url: URL | str) -> Playlist:
        raise NotImplementedError

    async def video(self, url: URL | str) -> Video:
        raise NotImplementedError

    async def comments(self, video_id: str, by_date: bool = False) -> Comments:
        raise NotImplementedError

    @staticmethod
    def convert_url(url: URL) -> URL:
        return url.replace(scheme="https", hostname="youtube.com", port=None)
