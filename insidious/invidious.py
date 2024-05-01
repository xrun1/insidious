# Can't have a "click to view replies" feature if we rely only on yt-dlp for
# comments because it doesn't provide any way to work with continuation IDs

import logging
from collections import deque
from datetime import datetime
from typing import ClassVar
from urllib.parse import quote

import backoff
import httpx
from pydantic import AliasPath, BaseModel, Field

from insidious.ytdl import HasThumbnails, Thumbnail


class Comment(HasThumbnails):
    id: str = Field(alias="commentId")
    thumbnails: list[Thumbnail] = Field(alias="authorThumbnails")
    author_name: str = Field(alias="author")
    author_id: str = Field(alias="authorId")
    author_uri: str = Field(alias="authorUrl")
    text: str = Field(alias="content")
    date: datetime = Field(alias="published")
    likes: int = Field(alias="likeCount")
    by_uploader: bool = Field(alias="authorIsChannelOwner")
    edited: bool = Field(alias="isEdited")
    pinned: bool = Field(alias="isPinned")
    sponsor: bool = Field(alias="isSponsor")
    replies: int | None = \
        Field(None, validation_alias=AliasPath("replies", "replyCount"))
    continuation_id: str | None = \
        Field(None, validation_alias=AliasPath("replies", "continuation"))

    def replies_url(self, video_id: str) -> str | None:
        if not self.continuation_id:
            return None
        args = (video_id, quote(self.continuation_id))
        return "/comments?video_id=%s&by_date=True&continuation_id=%s" % args


class Comments(BaseModel):
    data: list[Comment] = Field(alias="comments")
    total: int | None = Field(None, alias="commentCount")
    continuation_id: str | None = Field(None, alias="continuation")


class InvidiousClient:
    _sites: ClassVar[deque[str]] = deque()

    def __init__(self) -> None:
        super().__init__()
        self._httpx = httpx.AsyncClient(follow_redirects=True)

    @backoff.on_exception(
        backoff.constant,
        (httpx.NetworkError, httpx.TimeoutException, httpx.HTTPStatusError),
        max_tries = 20,
        interval = 0,
        backoff_log_level = logging.WARNING,
    )
    async def comments(
        self,
        video_id: str,
        by_date: bool = False,
        continuation_id: str | None = None,
    ) -> Comments:

        url = (await self._api) + f"/comments/{video_id}"
        params = {}
        if by_date:
            params["sort_by"] = "new"
        if continuation_id:
            params["continuation"] = continuation_id

        reply = await self._httpx.get(url, params=params)
        reply.raise_for_status()
        return Comments.model_validate(reply.json())

    @property
    async def _api(self) -> str:
        if not self._sites:
            url = "https://api.invidious.io/instances.json?sort_by=health"
            reply = await self._httpx.get(url)
            reply.raise_for_status()
            InvidiousClient._sites += (
                site[1]["uri"] for site in reply.json()
                if site[1]["type"] == "https" and site[1]["api"]
            )

        base = InvidiousClient._sites[0] + "/api/v1"
        InvidiousClient._sites.append(InvidiousClient._sites.popleft())
        return base
