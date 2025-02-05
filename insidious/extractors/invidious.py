# Copyright Insidious authors <https://github.com/xrun1/insidious>
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
from dataclasses import dataclass

import backoff
import httpx
from typing_extensions import override

from insidious.net import HTTPX_BACKOFF_ERRORS

from .client import APIClient, APIInstance
from .data import Comments


@dataclass
class InvidiousClient(APIClient):
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

        api = await self._api()
        url = api.url + f"/comments/{video_id}"
        params = {}
        if by_date:
            params["sort_by"] = "new"
        if continuation_id:
            params["continuation"] = continuation_id

        try:
            reply = await self._httpx.get(url, params=params)
            reply.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:  # noqa: PLR2004
                if not continuation_id:
                    return Comments(
                        comments=[], commentCount=0, continuation=None,
                        disabled=True,
                    )
            api.fail()
            raise
        except Exception:
            api.fail()
            raise

        comments = Comments.model_validate(reply.json())
        if not comments.data and not continuation_id:
            comments.total = 0

        return comments

    @override
    @classmethod
    @backoff.on_exception(
        backoff.constant,
        HTTPX_BACKOFF_ERRORS,
        max_tries = 5,
        interval = 0,
        backoff_log_level = logging.WARNING,
    )
    async def _get_api_instances(cls) -> list[APIInstance]:
        url = "https://api.invidious.io/instances.json?sort_by=health"
        reply = await cls._httpx.get(url)
        reply.raise_for_status()
        return [
            APIInstance(site[1]["uri"] + "/api/v1") for site in reply.json()
            if site[1]["type"] == "https" and site[1]["api"]
        ]


INVIDIOUS = InvidiousClient()
