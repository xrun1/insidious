from __future__ import annotations

from asyncio import BoundedSemaphore
from collections import defaultdict
from typing import Any

from fastapi.datastructures import URL
from httpx import USE_CLIENT_DEFAULT, AsyncClient, Request, Response
from typing_extensions import override

PARALLEL_REQUESTS_PER_HOST = 16

_GOOGLE_DOMAINS = {
    "ytimg.com", "googlevideo.com", "googleusercontent.com", "ggpht.com",
}
_request_semaphores: defaultdict[str, BoundedSemaphore] = \
    defaultdict(lambda: BoundedSemaphore(PARALLEL_REQUESTS_PER_HOST))


class HttpClient(AsyncClient):
    @override
    async def send(
        self,
        request: Request,
        *,
        stream: bool = False,
        auth: Any = USE_CLIENT_DEFAULT,
        follow_redirects: Any = USE_CLIENT_DEFAULT,
    ) -> Response:
        async with max_parallel_requests(str(request.url)):
            return await super().send(
                request,
                stream=stream, auth=auth, follow_redirects=follow_redirects,
            )


def max_parallel_requests(url: URL | str) -> BoundedSemaphore:
    if not (host := URL(str(url)).hostname):
        raise ValueError(f"{url} has no hostname")
    domain = ".".join(host.split(".")[-2:])
    if domain in _GOOGLE_DOMAINS:
        domain = "youtube.com"
    return _request_semaphores[domain]
