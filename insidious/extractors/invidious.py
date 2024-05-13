# Copyright Insidious authors <https://github.com/xrun1/insidious>
# SPDX-License-Identifier: AGPL-3.0-or-later

# Can't have a "click to view replies" feature if we rely only on yt-dlp for
# comments because it doesn't provide any way to work with continuation IDs

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import ClassVar

import backoff
import httpx
from typing_extensions import override

from insidious.net import HttpClient

from .client import YoutubeClient
from .data import Comments


@dataclass
class InvidiousClient(YoutubeClient):
    _sites: ClassVar[deque[str]] = deque()
    _httpx: httpx.AsyncClient = \
        field(default_factory=lambda: HttpClient(follow_redirects=True))

    @override
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
        try:
            reply.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:  # noqa: PLR2004
                if not continuation_id:
                    return Comments(
                        comments=[], commentCount=0, continuation=None,
                        disabled=True,
                    )
            raise

        comments = Comments.model_validate(reply.json())
        if not comments.data and not continuation_id:
            comments.total = 0

        return comments

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


INVIDIOUS = InvidiousClient()
