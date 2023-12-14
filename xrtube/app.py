import asyncio
import logging as log
import os
import re
import shutil
import time
from collections.abc import Coroutine
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from importlib import resources
from pathlib import Path
from urllib.parse import quote

import appdirs
import backoff
import httpx
import jinja2
import sass
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, WebSocket
from fastapi.datastructures import URL
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from watchfiles import awatch
import yt_dlp

from . import NAME
from .markup import yt_to_html
from .pagination import Pagination, RelatedPagination
from .utils import report
from .ytdl import (
    Channel,
    LiveStatus,
    Playlist,
    Video,
    YoutubeClient,
)

log.basicConfig(level=log.INFO)

LOADER = jinja2.PackageLoader(NAME, "templates")
TEMPLATES = Jinja2Templates(env=jinja2.Environment(loader=LOADER))
SCSS = resources.read_text(f"{NAME}.style", "main.scss")
CSS = sass.compile(string=SCSS, indented=False)
APP = FastAPI(default_response_class=HTMLResponse)

APP.mount("/static", StaticFiles(packages=[(NAME, "static")]), name="static")
if os.getenv("UVICORN_RELOAD"):
    # Fix browser reusing cached files at reload despite disk modifications
    StaticFiles.is_not_modified = lambda *_, **k: [k] and False  # type: ignore

HTTPX = httpx.AsyncClient(follow_redirects=True, headers={
    **YoutubeClient().headers,
    "Referer": "https://www.youtube.com/",
})
MANIFEST_URL = re.compile(r'(^|")(https?://[^"]+?)($|")', re.MULTILINE)
DYING = False
RELOAD_PAGE = asyncio.Event()
RELOAD_STYLE = asyncio.Event()

CACHE_DIR = Path(appdirs.user_cache_dir(NAME))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(CACHE_DIR)  # for ytdlp's write/load_pages mechanism

breakpoint()


@dataclass(slots=True)
class Index:
    request: Request
    title: str | None = None
    pagination: Pagination | None = None
    group: Channel | Playlist | None = None
    video: Video | None = None
    get_related: URL | None = None

    @property
    def full_title(self) -> str:
        return f"{self.title or ''} | {NAME}".removeprefix(" | ")

    @property
    def response(self) -> Response:
        enums = {LiveStatus}
        return TEMPLATES.TemplateResponse("index.html.jinja", {
            a: getattr(self, a) for a in dir(self)
            if not a.startswith("_") and a != "response"
        } | {
            e.__name__: e for e in enums
        } | {
            "UVICORN_RELOAD": os.getenv("UVICORN_RELOAD"),
            "no_emoji": "&#xFE0E;",
        })

    @staticmethod
    def local_url(url: str) -> str:
        return str(URL(url).replace(scheme="", netloc=""))

    @staticmethod
    def proxy(url: str, method: str = "get") -> str:
        return f"/proxy/{method}?url={quote(url)}"

    @staticmethod
    def youtube_format(text: str, allow_markup: bool = True) -> str:
        return yt_to_html(text, allow_markup)

    @staticmethod
    def format_duration(seconds: float) -> str:
        wild = "" if seconds < 60 else "*"
        text = re.sub(rf"^0:0{wild}", "", str(timedelta(seconds=seconds)))
        return re.sub(r", 0:00:00", "", text)  # e.g. 1 day, 0:00:00


def giveup(error: HTTPException) -> bool:
    # Request Timeout, Too Early, Too Many Requests, Internal Server Error,
    # Bad Gateway, Service Unavailable, Gateway Timeout
    return error.status_code not in (408, 425, 429, 500, 502, 503, 504)


@APP.get("/")
async def home(request: Request) -> Response:
    return Index(request).response


@APP.get("/style.css")
async def style() -> Response:
    return Response(content=CSS, media_type="text/css")


@APP.get("/results")
async def results(request: Request, search_query: str = "") -> Response:
    if (pg := Pagination.get(request).advance()).needs_more_data:
        pg.add(await pg.extender.search(pg.extender.convert_url(request.url)))

    return Index(request, search_query, pg).response


@APP.get("/hashtag/{tag}")
async def hashtag(request: Request, tag: str) -> Response:
    if (pg := Pagination.get(request).advance()).needs_more_data:
        pg.add(await pg.extender.playlist(pg.extender.convert_url(request.url)))

    return Index(request, f"#{tag}", pg).response


@APP.get("/@{id}")
@APP.get("/@{id}/{tab}")
@APP.get("/c/{id}")
@APP.get("/c/{id}/{tab}")
@APP.get("/channel/{id}")
@APP.get("/channel/{id}/{tab}")
@APP.get("/user/{id}")
@APP.get("/user/{id}/{tab}")
async def channel(request: Request, tab: str = "featured") -> Response:
    group = None

    if (pg := Pagination.get(request).advance()).needs_more_data:
        url = pg.extender.convert_url(request.url)

        if tab == "featured" and not request.url.path.endswith("/featured"):
            url = url.replace(path=url.path + "/featured")

        try:
            pg.add(group := await pg.extender.channel(url))
        except yt_dlp.DownloadError as e:
            log.warning("%s", e)
            path = url.path.removesuffix(f"/{tab}") + "/featured"
            group = await pg.extender_with(0).channel(url.replace(path=path))
            pg.done = True

    return Index(request, group.title if group else "", pg, group).response


@APP.get("/watch")
@APP.get("/v/{v}")
@APP.get("/shorts/{v}")
async def watch(request: Request) -> Response:
    client = YoutubeClient()
    video = await client.video(client.convert_url(request.url))
    rel = request.url_for("related").include_query_params(
        video_id = video.id,
        video_name = video.title,
        channel_name = video.channel_name,
        channel_url = video.channel_url,
    )
    return Index(request, video.title, video=video, get_related=rel).response


@APP.get("/related")
async def related(request: Request) -> Response:
    if (pg := RelatedPagination.get(request).advance()).needs_more_data:
        await pg.find()
    return Index(request, pagination=pg).response


@APP.get("/proxy/get", response_class=Response)
@backoff.on_exception(backoff.expo, HTTPException, giveup=giveup, max_tries=10)
async def proxy(
    request: Request, url: str, background_tasks: BackgroundTasks,
) -> Response:
    """GET request runner for browser to bypass the Same-Origin Policy"""

    def patch_hls_manifest(data: str) -> str:
        """Proxy all googlevideo URLs in HLS playlists to defeat SOP."""
        return MANIFEST_URL.sub(
            lambda m: m[1] + request.url.path + "?url=" + quote(m[2]) + m[3],
            data,
        )

    req = HTTPX.build_request("GET", url)
    try:
        reply = await HTTPX.send(req, stream=True)
        reply.raise_for_status()
    except httpx.NetworkError as e:
        raise HTTPException(502, f"Couldn't reach target URL: {e}")
    except httpx.TimeoutException as e:
        raise HTTPException(504, f"Target URL timed out: {e}")
    except httpx.HTTPStatusError as e:
        detail = f"Target URL returned error: {e.response.reason_phrase}"
        raise HTTPException(e.response.status_code, detail)

    mime = reply.headers.get("content-type")
    if mime == "application/vnd.apple.mpegurl":
        data = await reply.aread()
        data = patch_hls_manifest(data.decode())
        return Response(content=data, media_type=mime)

    background_tasks.add_task(reply.aclose)
    return StreamingResponse(reply.aiter_raw())


@APP.get("/{v}", response_class=RedirectResponse)
async def short_url_watch(request: Request, v: str) -> Response:
    if v == "favicon.ico":
        return Response(status_code=404)

    url = request.url.replace(path="/watch").include_query_params(v=v)
    return RedirectResponse(url)


@APP.websocket("/wait_reload")
async def wait_reload(ws: WebSocket) -> None:
    global DYING
    if DYING:
        return

    async def wait_page() -> None:
        while True:
            await RELOAD_PAGE.wait()
            RELOAD_PAGE.clear()
            await ws.send_text("page")

    async def wait_style() -> None:
        global SCSS
        global CSS
        while True:
            await RELOAD_STYLE.wait()
            RELOAD_STYLE.clear()
            SCSS = resources.read_text(f"{NAME}.style", "main.scss")
            CSS = sass.compile(string=SCSS, indented=False)
            await ws.send_text("style")

    await ws.accept()
    with suppress(asyncio.CancelledError):
        await asyncio.gather(wait_page(), wait_style())
    DYING = True


@APP.websocket("/wait_alive")
async def wait_alive(ws: WebSocket) -> None:
    if not DYING:
        await ws.accept()


def create_background_job(coro: Coroutine) -> asyncio.Task:
    async def task() -> None:
        with report(Exception):
            with suppress(asyncio.CancelledError):
                await coro
    return asyncio.create_task(task())


@APP.on_event("startup")
async def prune_cache() -> None:
    async def job() -> None:
        while True:
            freed = 0
            for file in CACHE_DIR.glob("*.dump"):
                stats = file.stat()
                if stats.st_mtime < time.time() - 600:
                    file.unlink()
                    freed += stats.st_size

            if (mib := freed / 1024 / 1024) >= 0.1:
                log.info("Cache: freed %d MiB", round(mib, 1))

            await asyncio.sleep(300)

    create_background_job(job())


@APP.on_event("startup")
async def watch_files() -> None:
    async def job() -> None:
        if not (dir := os.getenv("UVICORN_RELOAD")):
            return

        async for changes in awatch(dir):
            exts = {Path(p).suffix for _, p in changes}
            if ".jinja" in exts or ".js" in exts:
                RELOAD_PAGE.set()
            elif ".scss" in exts or ".css" in exts:
                RELOAD_STYLE.set()

    create_background_job(job())


@APP.on_event("shutdown")
async def separate_log() -> None:
    print("─" * shutil.get_terminal_size()[0]  )
