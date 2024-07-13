# Copyright Insidious authors <https://github.com/xrun1/insidious>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import asyncio
import logging as log
import operator
import os
import re
import shutil
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import timedelta
from functools import reduce
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Generic, TypeAlias
from urllib.parse import parse_qs, quote, urlencode

import backoff
import jinja2
from fastapi import BackgroundTasks, FastAPI, Query, Request, WebSocket
from fastapi.datastructures import URL
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing_extensions import override
from watchfiles import awatch

from . import DISPLAY_NAME, NAME
from .extractors.data import (
    Channel,
    Comment,
    Comments,
    InPlaylist,
    InSearch,
    LiveStatus,
    Playlist,
    ShortEntry,
    Video,
    VideoEntry,
)
from .extractors.filters import (
    Date,
    Duration,
    Features,
    SearchFilter,
    Sort,
    Type,
)
from .extractors.invidious import INVIDIOUS
from .extractors.markup import yt_to_html
from .extractors.ytdlp import YTDLP, CachedYoutubeDL
from .net import HTTPX_BACKOFF_ERRORS, HttpClient
from .pagination import Pagination, RelatedPagination, T
from .streaming import (
    HLS_ALT_MIME,
    HLS_MIME,
    dash_variant_playlist,
    master_playlist,
    sort_master_playlist,
    variant_playlist,
)
from .utils import httpx_to_fastapi_errors, report

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def create_background_job(coro: Awaitable[None]) -> asyncio.Task[None]:
    async def task() -> None:
        with report(Exception), suppress(asyncio.CancelledError):
            await coro
    return asyncio.create_task(task())


async def prune_cache() -> None:
    while True:
        CachedYoutubeDL.prune_cache()
        await asyncio.sleep(300)


async def watch_files() -> None:
    if not (dir := os.getenv("UVICORN_RELOAD")):
        return

    async for changes in awatch(dir):
        exts = {Path(p).suffix for _, p in changes}
        if ".jinja" in exts or ".js" in exts:
            RELOAD_PAGE.set()
        elif ".css" in exts:
            RELOAD_STYLE.set()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:  # noqa: RUF029
    lifespan_tasks.append(create_background_job(prune_cache()))
    lifespan_tasks.append(create_background_job(watch_files()))
    yield
    print("─" * shutil.get_terminal_size()[0])


log.basicConfig(level=log.INFO)
log.getLogger("httpx").setLevel(log.WARNING)

CallNext: TypeAlias = Callable[[Request], Awaitable[Response]]

LOADER = jinja2.PackageLoader(NAME, "templates")
ENV = jinja2.Environment(loader=LOADER, autoescape=jinja2.select_autoescape())
TEMPLATES = Jinja2Templates(env=ENV)
lifespan_tasks = []
app = FastAPI(default_response_class=HTMLResponse, lifespan=lifespan)


def mount(name: str) -> None:
    app.mount(f"/{name}", StaticFiles(packages=[(NAME, name)]), name=name)


list(map(mount, ("scripts", "style", "npm", "images")))
if os.getenv("UVICORN_RELOAD"):
    # Fix browser reusing cached files at reload despite disk modifications
    StaticFiles.is_not_modified = lambda *_, **_kws: False  # type: ignore

HTTPX = HttpClient(follow_redirects=True, headers={
    **YTDLP.headers,
    "Referer": "https://www.youtube.com/",
})
MANIFEST_URL = re.compile(r'(^|")(https?://[^"]+?)($|")', re.MULTILINE)
RSS_YT_URL = re.compile(r"https?://(www\.)?youtu(\.be|be\.com)(?!/xml/)")
RSS_YTIMG_URL = re.compile(r"https?://(.*\.)?ytimg.com")
dying = False
RELOAD_PAGE = asyncio.Event()
RELOAD_STYLE = asyncio.Event()


@dataclass(slots=True)
class Page:
    template: ClassVar[str]

    request: Request
    title: str | None

    @property
    def full_title(self) -> str:
        return f"{self.title or ''} | {DISPLAY_NAME}".removeprefix(" | ")

    @property
    def response(self) -> Response:
        return self._response_env(self.template)

    @property
    def continuation(self) -> Response:
        return self._response_env("search.html.jinja")

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
        wild = "" if seconds < 60 else "*"  # noqa: PLR2004
        text = re.sub(rf"^0:0{wild}", "", str(timedelta(seconds=seconds)))
        return re.sub(r", 0:00:00", "", text)  # e.g. 1 day, 0:00:00

    def _response_env(self, template: str) -> Response:
        passthrough = {
            LiveStatus, Date, Type, Duration, Features, Sort, SearchFilter,
            type, getattr,
        }
        return TEMPLATES.TemplateResponse(template, {
            a: getattr(self, a) for a in dir(self)
            if not a.startswith("_") and a not in {"response", "continuation"}
        } | {
            x.__name__: x for x in passthrough
        } | {
            "UVICORN_RELOAD": os.getenv("UVICORN_RELOAD"),
            "no_emoji": "&#xFE0E;",
        })


@dataclass(slots=True)
class Paginated(Page, Generic[T]):
    pagination: Pagination[T]


@dataclass(slots=True)
class HomePage(Page):
    template = "index.html.jinja"


@dataclass(slots=True)
class ChannelPage(Paginated[InSearch]):
    template = "channel.html.jinja"
    current_tab: str
    info: Channel | None = None
    search_query: str | None = None

    @property
    def sort(self) -> str:
        return self.request.query_params.get("sort") or ""

    def subpage_path(self, tab: str, sort: str = "") -> str:
        path = self.request.url.path.rstrip("/")
        path = path.removesuffix(f"/{self.current_tab}") + "/" + tab
        return f"{path}?sort={sort}" if sort else path


@dataclass(slots=True)
class PlaylistPage(Paginated[InPlaylist]):
    template = "playlist.html.jinja"
    info: Playlist | None = None


@dataclass(slots=True)
class SearchPage(Paginated[InSearch]):
    template = "search.html.jinja"
    search_query: str | None = None
    search_filter: SearchFilter = field(default_factory=SearchFilter)


@dataclass(slots=True)
class RelatedPage(Paginated[ShortEntry | VideoEntry]):
    template = "search.html.jinja"


@dataclass(slots=True)
class WatchPage(Page):
    template = "watch.html.jinja"
    info: Video
    get_related: URL | None = None
    get_comments: URL | None = None
    get_playlist: URL | None = None
    start: str | float | None = None
    end: str | float | None = None
    loop: bool = False
    autoplay: bool = False
    is_embed: bool = False


@dataclass(slots=True)
class LoadedPlaylistEntry(Page):
    template = "parts/entry.html.jinja"
    entry: Playlist


@dataclass(slots=True)
class FeaturedSection(Paginated[T]):
    template = "parts/featured.html.jinja"
    section_title: str | None = None
    full_view_url: str | None = None


@dataclass(slots=True)
class Dislikes(Page):
    template = "parts/dislikes.html.jinja"
    dislike_count: int | None = None


@dataclass(slots=True)
class CommentsPart(Paginated[Comment]):
    template = "parts/comments.html.jinja"
    info: Comments | None
    video_id: str

    @property
    @override
    def continuation(self) -> Response:
        return self._response_env(self.template)


@app.middleware("http")
async def fix_esm_mime(request: Request, call_next: CallNext) -> Response:
    # Chrome refuses to load ESM modules with the text/plain MIME that
    # FastAPI infers from "+esm" filenames
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/npm/") and path.endswith("/+esm"):
        response.headers["content-type"] = "application/javascript"
    return response


@app.get("/")
def home(request: Request) -> Response:
    return HomePage(request, None).response


@app.get("/results")
async def results(
    request: Request, search_query: str = "", sp: str = "",
) -> Response:
    filter = SearchFilter.parse(sp)
    if (pg := Pagination[InSearch].get(request).advance()).needs_more_data:
        pg.add(await YTDLP.search(search_query, filter, pg.page))

    return SearchPage(request, search_query, pg, search_query, filter).response


@app.get("/search")
def form_search(
    request: Request,
    query: str,
    type: str,
    duration: str,
    date: str,
    sort: str,
) -> Response:
    fts = (
        Features[value] for name, value in request.query_params.multi_items()
        if name == "feature[]"
    )
    filter = SearchFilter(
        date = Date[date],
        type = Type[type],
        duration = Duration[duration],
        features = reduce(operator.__or__, fts, Features.Any),
        sort = Sort[sort],
    )
    url = request.url.replace(path="results").replace_query_params(
        search_query=query, sp=filter.url_parameter,
    )
    return RedirectResponse(url)


@app.get("/hashtag/{tag}")
async def hashtag(request: Request, tag: str) -> Response:
    if (pg := Pagination[InSearch].get(request).advance()).needs_more_data:
        pg.add(await YTDLP.hashtag(tag, pg.page))

    return SearchPage(request, f"#{tag}", pg).response


@app.get("/user/{id}")
@app.get("/user/{id}/{tab}")
async def user(
    request: Request, id: str, tab: str = "featured", query: str = "",
    sort: str = "",
) -> Response:
    if (pg := Pagination[InSearch].get(request).advance()).needs_more_data:
        pg.add(channel := await YTDLP.user(id, tab, query, pg.page, sort))
        page = ChannelPage(request, channel.title, pg, tab, channel, query)
        return page.response

    return ChannelPage(request, None, pg, tab).continuation


@app.get("/channel/{id}")
@app.get("/channel/{id}/{tab}")
async def channel(
    request: Request, id: str, tab: str = "featured", query: str = "",
    sort: str = "",
) -> Response:
    if (pg := Pagination[InSearch].get(request).advance()).needs_more_data:
        pg.add(channel := await YTDLP.channel(id, tab, query, pg.page, sort))
        page = ChannelPage(request, channel.title, pg, tab, channel, query)
        return page.response

    return ChannelPage(request, None, pg, tab).continuation


@app.get("/playlist")
async def playlist(request: Request, list: str) -> Response:
    if (pg := Pagination[InPlaylist].get(request).advance()).needs_more_data:
        pg.add(pl := await YTDLP.playlist(list, pg.page))
        return PlaylistPage(request, pl.title, pg, pl).response

    return PlaylistPage(request, None, pg).continuation


@app.get("/watch_videos")
async def make_playlist(video_ids: Annotated[list[str], Query()]) -> Response:
    with httpx_to_fastapi_errors():
        api = "https://youtube.com/watch_videos?video_ids=%s"
        reply = await HTTPX.head(api % ",".join(video_ids))
        reply.raise_for_status()
        return RedirectResponse(str(reply.url))


@app.get("/load_playlist_entry")
async def load_playlist_entry(request: Request, video_id: str) -> Response:
    # We want at least some entries for hover thumbnails preview
    pl = await YTDLP.playlist(video_id)
    return LoadedPlaylistEntry(request, None, pl).response


@app.get("/featured_playlist")
async def featured_playlist(request: Request, id: str) -> Response:
    if (pg := Pagination[InPlaylist].get(request).advance()).needs_more_data:
        pg.add(pl := await YTDLP.playlist(id, pg.page))
        return FeaturedSection(request, None, pg, pl.title, pl.url).response

    return FeaturedSection(request, None, pg).continuation


@app.get("/featured_tab")
async def featured_tab(request: Request, url: str, title: str) -> Response:
    *_, api, id, tab = ([""] * 4) + URL(url).path.split("/")
    sort = next(iter(parse_qs(URL(url).query).get("sort", [])), "")

    if (pg := Pagination[InSearch].get(request).advance()).needs_more_data:
        if api in {"", "c"}:
            vids = await YTDLP.named_channel(id, tab, page=pg.page, sort=sort)
        elif api == "channel":
            vids = await YTDLP.channel(id, tab, page=pg.page, sort=sort)
        elif api == "user":
            vids = await YTDLP.user(id, tab, page=pg.page, sort=sort)
        else:
            raise ValueError(f"Invalid channel tab preview url {url!r}")

        pg.add(vids)
        return FeaturedSection(request, None, pg, title, url).response

    return FeaturedSection(request, None, pg).continuation


@app.get("/watch")
@app.get("/v/{v}")
@app.get("/embed/{v}")
@app.get("/shorts/{v}")
@app.get("/clip/{v}")
@app.get("/live/{v}")
async def watch(
    request: Request,
    v: str,
    list: str | None = None,
    t: str | None = None,
    start: str | None = None,
    # Not recognized by YT from there onwards
    end: str | None = None,
    loop: bool = False,
    autoplay: bool = False,
) -> Response:
    video = await YTDLP.video(v)
    get_rel = get_coms = get_pl = None
    is_embed = True

    if request.url.path.startswith("/clip/"):
        video.id = next(iter(re.findall(
            r"/vi(?:_webp)?/([^/]+)/", video.best_thumbnail.url,
        )), video.id)

    if not request.url.path.startswith("/embed/"):
        is_embed = False
        rel_params = {k: v for k, v in {
            "video_id": video.id,
            "video_name": video.title,
            "uploader_id": video.uploader_id,
            "channel_name": video.channel_name,
            "channel_id": video.channel_id,
        }.items() if v is not None}
        get_rel = request.url_for("related").include_query_params(**rel_params)

        get_coms = request.url_for("comments").include_query_params(
            video_id = video.id,
            by_date = True,
        )

    if list:
        get_pl = request.url_for("playlist").include_query_params(
            list=list, find_attr=f"id:{v}", per_page=100,
        )

    return WatchPage(
        request, video.title, video, get_rel, get_coms, get_pl,
        start or t or video.clip_start, end or video.clip_end,
        loop or (video.clip_start is not None),
        autoplay,
        is_embed,
    ).response


@app.get("/storyboard")
async def storyboard(video_id: str) -> Response:
    text = (await YTDLP.video(video_id)).webvtt_storyboard
    return Response(text, media_type="text/vtt")


@app.get("/chapters")
async def chapters(video_id: str) -> Response:
    text = (await YTDLP.video(video_id)).webvtt_chapters
    return Response(text, media_type="text/vtt")


@app.get("/related")
async def related(request: Request) -> Response:
    if (pg := RelatedPagination.get(request).advance()).needs_more_data:
        await pg.find()

    for entry in pg.items:
        entry.url = str(URL(entry.url).remove_query_params(("list", "index")))

    return RelatedPage(request, None, pg).response


@app.get("/dislikes")
async def dislikes(request: Request, video_id: str):
    with httpx_to_fastapi_errors():
        api = "https://returnyoutubedislikeapi.com/votes"
        reply = await HTTPX.get(api, params={"videoId": video_id})
        reply.raise_for_status()
        count = reply.json().get("dislikes") or 0
        return Dislikes(request, None, count).response


@app.get("/comments")
async def comments(
    request: Request,
    video_id: str,
    by_date: bool = False,
    continuation_id: str | None = None,
) -> Response:
    if (pg := Pagination[Comment].get(request).advance()).needs_more_data:
        with httpx_to_fastapi_errors():
            coms = await INVIDIOUS.comments(video_id, by_date, continuation_id)

        pg.add(coms.data)
        pg.continuation_id = coms.continuation_id
        if not pg.continuation_id:
            pg.done = True

        return CommentsPart(request, None, pg, coms, video_id).response

    return CommentsPart(request, None, pg, None, video_id).continuation


@app.get("/generate_hls/master")
async def make_master_m3u8(request: Request, video_id: str) -> Response:
    api = str(request.base_url)
    api += f"generate_hls/variant?video_id={video_id}&format_id="
    text = master_playlist(api, await YTDLP.video(video_id))
    return Response(text, media_type="application/x-mpegURL")


@app.get("/generate_hls/variant")
async def make_variant_m3u8(
    request: Request, video_id: str, format_id: str,
) -> Response:
    video = await YTDLP.video(video_id)
    format = next(f for f in video.formats if f.id == format_id)
    api = f"{request.base_url}proxy/get?url=%s"

    if format.has_dash:
        text = dash_variant_playlist(api, format)
        return Response(text, media_type=HLS_MIME)

    with httpx_to_fastapi_errors():
        async with HTTPX.stream("GET", format.url) as reply:
            mp4_data = reply.aiter_bytes()
            text = await variant_playlist(api % quote(format.url), mp4_data)
            return Response(text, media_type=HLS_MIME)


@app.get("/refresh_hls")
async def refresh_hls(video_id: str) -> PlainTextResponse:
    # googlevideo links have a ~6h lifetime
    video = await YTDLP.video(video_id, skip_cache=True)
    return PlainTextResponse(video.manifest_url)


@app.get("/proxy/get", response_class=Response)
async def proxy(
    request: Request, url: str, background_tasks: BackgroundTasks,
) -> Response:
    """GET request runner, fix some content and bypass Same-Origin Policy."""

    def patch_hls_manifest(data: str) -> str:
        """Sort variant streams and proxy all googlevideo URLs to bypass SOP"""
        return sort_master_playlist(MANIFEST_URL.sub(
            lambda m: m[1] + request.url.path + "?url=" + quote(m[2]) + m[3],
            data,
        ))

    headers = {}
    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]

    req = HTTPX.build_request("GET", url, headers=headers)
    with httpx_to_fastapi_errors():
        reply = await backoff.on_exception(
            backoff.expo, HTTPX_BACKOFF_ERRORS, max_tries=5,
            backoff_log_level=log.WARNING,
        )(HTTPX.send)(req, stream=True)
        reply.raise_for_status()

    mime = reply.headers.get("content-type")
    reply_headers = {k: v for k, v in reply.headers.items() if k in {
        "accept-ranges", "content-length", "x-content-type-options",
        # FIXME: breaks video delivery
        # "date", "expires", "cache-control", "age", "etag",
    }}
    if mime in {HLS_MIME, HLS_ALT_MIME}:
        data = await reply.aread()
        data = patch_hls_manifest(data.decode())
        return Response(content=data, media_type=mime)
    if URL(url).path.endswith(".ts"):
        mime = "video/mp2t"

    async def iter() -> AsyncIterator[bytes]:
        with httpx_to_fastapi_errors():
            async for chunk in reply.aiter_bytes():
                yield chunk

    background_tasks.add_task(reply.aclose)
    return StreamingResponse(iter(), 200, reply_headers, mime)


@app.get("/feeds/videos.xml")
async def rss_feed(request: Request):
    with httpx_to_fastapi_errors():
        url = request.url.replace(scheme="https", netloc="youtube.com")
        reply = await HTTPX.get(str(url))
        reply.raise_for_status()
        new_base = request.url.scheme + "://" + request.url.netloc
        xml = RSS_YT_URL.sub(new_base, reply.text)
        xml = RSS_YTIMG_URL.sub(
            lambda match: f"{new_base}/proxy/get?url={quote(match[0])}",
            xml,
        )
        return Response(content=xml, media_type="application/xml")


@app.websocket("/wait_reload")
async def wait_reload(ws: WebSocket) -> None:
    global dying  # noqa: PLW0603
    if dying:
        return

    async def wait_page() -> None:
        while True:
            await RELOAD_PAGE.wait()
            RELOAD_PAGE.clear()
            await ws.send_text("page")

    async def wait_style() -> None:
        while True:
            await RELOAD_STYLE.wait()
            RELOAD_STYLE.clear()
            await ws.send_text("style")

    await ws.accept()
    with suppress(asyncio.CancelledError):
        await asyncio.gather(wait_page(), wait_style())
    dying = True


@app.websocket("/wait_alive")
async def wait_alive(ws: WebSocket) -> None:
    if not dying:
        await ws.accept()


# Have to declare this last due to the catch-all route below
@app.get("/{name}")
@app.get("/{name}/{tab}")
@app.get("/c/{name}")
@app.get("/c/{name}/{tab}")
async def named_channel(
    request: Request, name: str, tab: str = "featured", query: str = "",
    sort: str = "",
) -> Response:
    if name == "favicon.ico":
        return Response(status_code=404)

    if (pg := Pagination[InSearch].get(request).advance()).needs_more_data:
        channel = await YTDLP.named_channel(name, tab, query, pg.page, sort)
        pg.add(channel)
        page = ChannelPage(request, channel.title, pg, tab, channel, query)
        return page.response

    return ChannelPage(request, None, pg, tab).continuation
