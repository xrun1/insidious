import asyncio
from collections.abc import Coroutine
from contextlib import suppress
import logging as log
import math
import os
from pathlib import Path
import re
import shutil
import time
from dataclasses import dataclass, field
from importlib import resources
from urllib.parse import quote
from uuid import uuid4

import appdirs
import httpx
import jinja2
import sass
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.datastructures import URL
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from watchfiles import awatch

from xrtube.utils import report

from . import NAME
from .ytdl import (
    NoDataReceived,
    Playlist,
    PlaylistEntry,
    Search,
    ShortEntry,
    Video,
    VideoEntry,
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

HTTPX = httpx.AsyncClient()
MANIFEST_URL = re.compile(r'(^|")(https?://[^"]+?)($|")', re.MULTILINE)
RELOAD = asyncio.Event()
RELOAD_SCSS = asyncio.Event()
UUID = uuid4()

CACHE_DIR = Path(appdirs.user_cache_dir(NAME))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(CACHE_DIR)  # for ytdlp's write/load_pages mechanism


@dataclass
class Index:
    request: Request
    title: str = NAME
    results: Search = field(default_factory=Search)
    next_page: URL | None = None
    get_related: URL | None = None
    video: Video | None = None

    @property
    def response(self) -> Response:
        return TEMPLATES.TemplateResponse("index.html.jinja", {
            a: getattr(self, a) for a in dir(self)
            if not a.startswith("_") and a != "response"
        } | {"UVICORN_RELOAD": os.getenv("UVICORN_RELOAD")})

    @staticmethod
    def local_url(url: str) -> str:
        return str(URL(url).replace(scheme="", netloc=""))

    @staticmethod
    def proxy(url: str, method: str = "get") -> str:
        return f"/proxy/{method}?url={quote(url)}"


@APP.get("/")
async def home(request: Request) -> Response:
    return Index(request).response


@APP.get("/style.css")
async def style() -> Response:
    return Response(content=CSS, media_type="text/css")


@APP.get("/results")
async def results(
    request: Request, search_query: str = "", page: int = 1,
) -> Response:
    client = YoutubeClient(page=page)
    return Index(
        request,
        title = f"{search_query} | {NAME}" if search_query else NAME,
        next_page = request.url.include_query_params(page=page + 1),
        results = await client.search(client.convert_url(request.url)),
    ).response


@APP.get("/watch")
async def watch(request: Request, v: str) -> Response:
    client = YoutubeClient()
    video = await client.video(client.convert_url(request.url))
    return Index(
        request,
        title = f"{video.title} | {NAME}",
        video = video,
        get_related = request.url_for("related").include_query_params(
            video_title = video.title,
            channel_name = video.channel_name,
            channel_url = video.channel_url,
            exclude_video_ids = video.id,
        ),
    ).response


@APP.get("/related")
async def related(
    request: Request,
    video_title: str,
    channel_name: str,
    channel_url: str,
    exclude_video_ids: str,
    page: int = 1,
    low_confidence: bool = False,
) -> Response:
    """Find videos related to one we're watching."""

    @dataclass(slots=True)
    class Result:
        entry: ShortEntry | VideoEntry
        found_times: int = 1
        weight: float = 1

        @property
        def score(self) -> float:
            return self.found_times * self.weight

    by_id: dict[str, Result] = {}
    excluded = set(exclude_video_ids.split())
    start = time.time()
    log.info("Related: starting for %r on page %d, low confidence: %r",
             video_title, page, low_confidence)

    def on_videos(entries: Playlist | Search, weight: float = 1) -> None:
        """Process the videos in a playlist or search results."""

        exclude = bump = add = ignore = 0
        for entry in entries.entries:
            if entry.id in excluded:
                exclude += 1
                continue
            elif entry.id in by_id:
                bump += 1
                result = by_id[entry.id]
                result.found_times += 1
                result.weight = max(result.weight, weight)
            elif isinstance(entry, ShortEntry | VideoEntry):
                add += 1
                by_id[entry.id] = Result(entry)
            else:
                ignore += 1
        log.info("Related: exclude %d, bump %d, add %d, ignore %d from %r",
                 exclude, bump, add, ignore, entries.title)

    async def on_list_entry(entry: PlaylistEntry, weight: float = 1) -> None:
        """Load details and videos of a playlist found in search results."""

        client = YoutubeClient(page=page, per_page=100)
        with report(NoDataReceived):
            playlist = await client.playlist(entry.url)
            on_videos(playlist, weight)

    async def find_playlists(query: str, weight: float = 1) -> None:
        """Search site-wide for playlists related to the watched video."""

        client = YoutubeClient(per_page=5)
        url = "https://www.youtube.com/results?search_query={}&sp=EgIQAw%3D%3D"
        url = url.format(quote(query))

        with report(NoDataReceived):
            got = await client.search(url)
            log.info("Related: found %d playlists for %r", len(got), url)

            async with asyncio.TaskGroup() as tg:
                for entry in got.entries:
                    if isinstance(entry, PlaylistEntry):
                        tg.create_task(on_list_entry(entry, weight))

    async def find_channel_videos(weight: float = 1) -> None:
        """Search the watched video's source channel for similar videos."""

        def halve(title: str) -> str:
            words = title.split()  # TODO: handle spaceless languages
            return " ".join(words[:math.ceil(len(words)/2)])

        # NOTE: Failure on "- Topic" auto-generated channels is expected
        client = YoutubeClient(page=page, per_page=12)
        url = channel_url + "/search?query=" + quote(halve(video_title))
        with report(NoDataReceived):
            got = await client.search(url)
            log.info("Related: found %d channel videos for %r", len(got), url)
            on_videos(got, weight)

    # First try to get a combination of similar videos from the uploader
    # and videos from general playlists that *should* contain the current video
    if not low_confidence:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(find_playlists(video_title + " " + channel_name, 2))
            tg.create_task(find_channel_videos(2))

    # If there were no results or we ran out, try to find playlists with a less
    # explicit search, which is more likely to return unrelated content
    if not by_id:
        if not low_confidence:
            log.info("Related: reached low confidence for %r", video_title)
            low_confidence = True
            page = 1
        await find_playlists(video_title)

    log.info("Related: got %d results for page %d in %ss",
             len(by_id), page, round(time.time() - start, 2))

    if not by_id:
        return Index(request).response

    ordered = sorted(by_id.values(), key=lambda r: r.score, reverse=True)
    results = Search(entries=[r.entry for r in ordered])
    next_page = request.url.include_query_params(
        page = page + 1,
        exclude_video_ids = " ".join(excluded | by_id.keys()),
        low_confidence = low_confidence,
    )
    return Index(request, results=results, next_page=next_page).response


@APP.get("/proxy/get", response_class=Response)
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
    reply = await HTTPX.send(req, stream=True)
    mime = reply.headers.get("content-type")

    if mime == "application/vnd.apple.mpegurl":
        data = await reply.aread()
        data = patch_hls_manifest(data.decode())
        return Response(content=data, media_type=mime)

    background_tasks.add_task(reply.aclose)
    return StreamingResponse(reply.aiter_raw())


@APP.get("/instance_id")
def instance_id() -> Response:
    return Response(str(UUID))


@APP.get("/wait_reload", response_class=Response)
async def wait_reload() -> Response:
    try:
        await RELOAD.wait()
    except asyncio.CancelledError:
        return instance_id()
    else:
        RELOAD.clear()
        return Response("direct")


@APP.get("/wait_reload_scss", response_class=Response)
async def wait_reload_scss() -> Response:
    global CSS
    with suppress(asyncio.CancelledError):
        await RELOAD_SCSS.wait()
        RELOAD_SCSS.clear()
        CSS = resources.read_text(f"{NAME}.style", "main.scss")
        return Response("reload")
    return Response()


def create_background_job(coro: Coroutine) -> asyncio.Task:
    async def task() -> None:
        with report(Exception):
            with suppress(asyncio.CancelledError):
                await coro
    return asyncio.create_task(task())


@APP.on_event("startup")
async def watch_files() -> None:
    async def job() -> None:
        if not (dir := os.getenv("UVICORN_RELOAD")):
            return

        async for changes in awatch(dir):
            exts = {Path(p).suffix for _, p in changes}
            if ".scss" in exts or ".css" in exts:
                RELOAD_SCSS.set()
            elif ".jinja" in exts or ".js" in exts:
                RELOAD.set()

    create_background_job(job())


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


@APP.on_event("shutdown")
async def separate_log() -> None:
    print("─" * shutil.get_terminal_size()[0]  )
