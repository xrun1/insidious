# Copyright Insidious authors <https://github.com/xrun1/insidious>
# SPDX-License-Identifier: AGPL-3.0-or-later

# Can't have a "click to view replies" feature if we rely only on yt-dlp for
# comments because it doesn't provide any way to work with continuation IDs

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import ClassVar

import backoff
import httpx
from typing_extensions import override

from insidious.net import HTTPX_BACKOFF_ERRORS, HttpClient

from .client import APIInstance, ClientUnavailable, YoutubeClient
from .data import Comments


@dataclass
class InvidiousClient(YoutubeClient):
    _sites_check: ClassVar[datetime] = datetime.fromtimestamp(0)
    _sites: ClassVar[deque[APIInstance]] = deque()

    _httpx: httpx.AsyncClient = \
        field(default_factory=lambda: HttpClient(follow_redirects=True))

    @override
    @backoff.on_exception(
        backoff.constant,
        HTTPX_BACKOFF_ERRORS,
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

        api = await self._api
        url = api.url + f"/api/v1/comments/{video_id}"
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
            api.last_error = datetime.now()
            raise

        comments = Comments.model_validate(reply.json())
        if not comments.data and not continuation_id:
            comments.total = 0

        return comments

    @property
    async def _api(self) -> APIInstance:
        now = datetime.now()

        if self._sites_check < now - timedelta(hours=6):
            url = "https://api.invidious.io/instances.json?sort_by=health"
            reply = await self._httpx.get(url)
            reply.raise_for_status()
            InvidiousClient._sites.clear()
            InvidiousClient._sites += (
                APIInstance(site[1]["uri"]) for site in reply.json()
                if site[1]["type"] == "https" and site[1]["api"]
            )
            InvidiousClient._sites_check = datetime.now()

        if not InvidiousClient._sites:
            raise ClientUnavailable("No usable Invidious instances found")

        i = 0
        while InvidiousClient._sites[0].last_error > now - timedelta(hours=1):
            InvidiousClient._sites.append(InvidiousClient._sites.popleft())
            if i >= len(InvidiousClient._sites):
                raise ClientUnavailable("All Invidious instances are failing")

        return InvidiousClient._sites[0]


INVIDIOUS = InvidiousClient()
