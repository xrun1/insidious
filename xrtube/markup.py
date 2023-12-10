import html
import re


def build_youtube_markup_regex(symbol: str) -> re.Pattern:
    sym = re.escape(symbol)
    return re.compile(rf"(?:^|(?<=\s)){sym}(.*?){sym}(?=\s|$)")


URL = re.compile(
    r"(https?://(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}"
    r"\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*))"
)
YT_MARKUP = {
    "strong": build_youtube_markup_regex("*"),
    "em": build_youtube_markup_regex("_"),
    "del": build_youtube_markup_regex("-"),
}


def yt_to_html(text: str) -> str:
    text = html.escape(text)

    for tag, regex in YT_MARKUP.items():
        text = regex.sub(rf"<{tag}>\1</{tag}>", text)

    return URL.sub(r'<a href="\1">\1</a>', text)
