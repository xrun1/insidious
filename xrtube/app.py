from importlib import resources
from typing import Any

import jinja2
import sass
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import NAME
from .ytdl import SearchResults, YoutubeClient

LOADER = jinja2.PackageLoader(NAME, "templates")
TEMPLATES = Jinja2Templates(env=jinja2.Environment(loader=LOADER))
SASS = resources.read_text(f"{NAME}.style", "main.sass")
CSS = sass.compile(string=SASS, indented=True)
APP = FastAPI(default_response_class=HTMLResponse)
APP.mount("/static", StaticFiles(packages=[(NAME, "static")]), name="static")


def jinja(name: str, request: Request, context: dict[str, Any]) -> Response:
    name += ".html.jinja"
    return TEMPLATES.TemplateResponse(name, context | {"request": request})


@APP.get("/")
async def home(request: Request) -> Response:
    entries = SearchResults(entries=[])
    return jinja("index", request, {"title": NAME, "results": entries})


@APP.get("/style.css")
async def style() -> Response:
    return Response(content=CSS, media_type="text/css")


@APP.get("/results")
async def results(
    request: Request, search_query: str = "", page: int = 1,
) -> Response:
    client = YoutubeClient(page=page)
    return jinja("index", request, {
        "title": f"{search_query} | {NAME}" if search_query else NAME,
        "next_page": request.url.include_query_params(page=page + 1),
        "results": await client.search(client.convert_url(request.url)),
    })
