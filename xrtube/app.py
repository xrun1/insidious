import re
from dataclasses import dataclass, field
from importlib import resources
from urllib.parse import quote

import httpx
import jinja2
import sass
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.datastructures import URL
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import NAME
from .ytdl import SearchResults, Video, YoutubeClient

LOADER = jinja2.PackageLoader(NAME, "templates")
TEMPLATES = Jinja2Templates(env=jinja2.Environment(loader=LOADER))
SASS = resources.read_text(f"{NAME}.style", "main.sass")
CSS = sass.compile(string=SASS, indented=True)
APP = FastAPI(default_response_class=HTMLResponse)
APP.mount("/static", StaticFiles(packages=[(NAME, "static")]), name="static")

HTTPX = httpx.AsyncClient()
MANIFEST_URL = re.compile(r'(^|")(https?://[^"]+?)($|")', re.MULTILINE)


@dataclass
class Index:
    request: Request
    title: str = NAME
    results: SearchResults = field(default_factory=SearchResults)
    next_page: URL | None = None
    video: Video | None = None

    @property
    def response(self) -> Response:
        return TEMPLATES.TemplateResponse("index.html.jinja", {
            a: getattr(self, a) for a in dir(self)
            if not a.startswith("_") and a != "response"
        })

    @staticmethod
    def local_url(url: str) -> str:
        return str(URL(url).replace(scheme="", netloc=""))


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
    ).response

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
