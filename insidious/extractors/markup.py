# Copyright Insidious authors <https://github.com/xrun1/insidious>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import html
import re
from urllib.parse import unquote
from uuid import UUID, uuid4

from fastapi.datastructures import URL


def build_youtube_markup_regex(symbol: str) -> re.Pattern[str]:
    sym = re.escape(symbol)
    return re.compile(rf"(?:^|(?<=\s)){sym}(?!\s)(.*?)[^\s]{sym}(?=\s|$)")


URL_RE = re.compile(
    r"(https?://(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}"
    r"\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=!]*))",
)
HASHTAGS_RE = re.compile(r"(?:^|(?<=\W))#([\w#-]+)")
TIME_RE = re.compile(r"(?:^|(?<=\W))((?:(\d+):)?(\d{1,2}):(\d{2}))(?=\W|$)")
MARKUP_RE = {
    "strong": build_youtube_markup_regex("*"),
    "em": build_youtube_markup_regex("_"),
    "del": build_youtube_markup_regex("-"),
}


def yt_to_html(text: str, allow_markup: bool = True, br: bool = False) -> str:
    parts: dict[UUID, str] = {}

    def prepare_url(match: re.Match[str]) -> str:
        url = URL(match[1])
        pretty = html.escape(unquote(str(url)), quote=False)
        host = (url.hostname or "").removeprefix("www.")

        if host in {"youtube.com", "youtube-nocookie.com", "youtu.be"}:
            url = url.replace(scheme="", hostname="")

        parts[(id := uuid4())] = f'<a href="{url}">{pretty}</a>'
        return str(id)

    def prepare_hashtags(match: re.Match[str]) -> str:
        ids = []
        for tag in match[1].split("#"):
            parts[(id := uuid4())] = f"""<a
                href="/hashtag/{tag}"
                hx-get="/hashtag/{tag}"
                hx-select=".page-content"
                hx-target=".page-content"
                hx-push-url=true
            >#{tag}</a>"""
            ids.append(str(id))
        return "".join(ids)

    def prepare_timestamp(match: re.Match[str]) -> str:
        colon_time, h, m, s = match.groups()
        hms_time = f"{h or ''}h{m}m{s}s".lstrip("h")
        # Will be further processed on the JS-side
        parts[(id := uuid4())] = f"<a hms-time='{hms_time}'>{colon_time}</a>"
        return str(id)

    # The URLs/etc can contain characters like & which html.escape would break,
    # which is why do their replacements in two steps
    text = URL_RE.sub(prepare_url, text)
    text = HASHTAGS_RE.sub(prepare_hashtags, text)
    text = TIME_RE.sub(prepare_timestamp, text)
    text = html.escape(text, quote=False)
    
    if br:
        text = text.replace("\n", "<br>")

    # Only after escaping normal text, we can inject our custom HTML
    if allow_markup:
        for tag, regex in MARKUP_RE.items():
            text = regex.sub(rf"<{tag}>\1</{tag}>", text)
    for uuid, replacement in parts.items():
        text = text.replace(str(uuid), replacement)

    return text.rstrip()
