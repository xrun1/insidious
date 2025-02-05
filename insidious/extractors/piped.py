# Copyright Insidious authors <https://github.com/xrun1/insidious>
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import logging
from dataclasses import dataclass

import backoff
from fastapi.datastructures import URL
from typing_extensions import override

from insidious.net import HTTPX_BACKOFF_ERRORS

from .client import APIClient, APIInstance
from .data import Comments, Thumbnail


@dataclass
class PipedClient(APIClient):
    @override
    @backoff.on_exception(
        backoff.constant,
        (OSError, json.JSONDecodeError, *HTTPX_BACKOFF_ERRORS),
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
        if continuation_id:
            url = api.url + f"/nextpage/comments/{video_id}"
            params["nextpage"] = self._make_nextpage(video_id, continuation_id)

        try:
            reply = await self._httpx.get(url, params=params)
            reply.raise_for_status()
            data = reply.json()
        except Exception:
            api.fail()
            raise

        data["continuation"] = self._parse_nextpage(data.pop("nextpage"))

        # NOTE: missing: absolute published date, edited, sponsor
        # NOTE: new: creatorReplied, verified, hearted
        for c in data["comments"]:
            url = URL(c.pop("thumbnail") or "")
            url = url.replace(scheme="https", hostname="yt3.ggpht.com")
            c["authorThumbnails"] = [Thumbnail(url=str(url))]
            c["authorUrl"] = c.pop("commentorUrl") or ""
            c["authorIsChannelOwner"] = c.pop("channelOwner") or False
            c["isPinned"] = c.pop("pinned") or False
            c["replies"] = {
                "replyCount": c.pop("replyCount"),
                "continuation": self._parse_nextpage(c.pop("repliesPage")),
            }

        comments = Comments.model_validate(data)
        if comments.total == -1:
            comments.total = None
        if not comments.data and not continuation_id:  # TODO: really needed?
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
        url = "https://raw.githubusercontent.com/TeamPiped/documentation/refs/heads/main/content/docs/public-instances/index.md"
        reply = await cls._httpx.get(url)
        reply.raise_for_status()

        results = []
        for line in reply.text.splitlines():
            columns = line.split("|")
            if len(columns) > 1:
                if (col := columns[1].strip()).startswith("https://"):
                    if not col.endswith(".onion"):
                        results.append(APIInstance(col))
        return results

    @staticmethod
    def _parse_nextpage(blob: str | None) -> str | None:
        return json.loads(blob or "{}").get("id") or None

    @staticmethod
    def _make_nextpage(video_id: str, continuation_id: str) -> str:
        return json.dumps({
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "id": continuation_id,
            "ids": None,
            "cookies": None,
            "body": None,
        }, separators=(",", ":"))


PIPED = PipedClient()
