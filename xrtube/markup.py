import html
import re
from uuid import UUID, uuid4


def build_youtube_markup_regex(symbol: str) -> re.Pattern:
    sym = re.escape(symbol)
    return re.compile(rf"(?:^|(?<=\s)){sym}(.*?){sym}(?=\s|$)")


URL = re.compile(
    r"(https?://(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}"
    r"\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*))"
)
HASHTAGS = re.compile(r"(?:^|(?<=\W))#(\w+)")
YT_MARKUP = {
    "strong": build_youtube_markup_regex("*"),
    "em": build_youtube_markup_regex("_"),
    "del": build_youtube_markup_regex("-"),
}


def yt_to_html(text: str) -> str:
    parts: dict[UUID, str] = {}

    def prepare_url(match: re.Match) -> str:
        parts[(id := uuid4())] = f'<a href="{match[1]}">{match[1]}</a>'
        return str(id)

    def prepare_hashtag(match: re.Match) -> str:
        parts[(id := uuid4())] = f"""<a
            href="/hashtag/{match[1]}"
            hx-get="/hashtag/{match[1]}"
            hx-select="#explore-column"
            hx-target="#explore-column"
            hx-push-url=true
        >#{match[1]}</a>"""
        return str(id)

    # The URLs/etc can contain characters like & which html.escape would break,
    # which is why do their replacements in two steps
    text = URL.sub(prepare_url, text)
    text = HASHTAGS.sub(prepare_hashtag, text)
    for tag, regex in YT_MARKUP.items():
        text = regex.sub(rf"<{tag}>\1</{tag}>", text)

    text = html.escape(text, quote=False)
    # Only after escaping normal text, we can inject our custom HTML
    for uuid, replacement in parts.items():
        text = text.replace(str(uuid), replacement)

    return text
