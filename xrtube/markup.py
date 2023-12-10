import html
import re


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
    def format_hashtag(match: re.Match) -> str:
        return f"""<a
            href="/hashtag/{match[1]}"
            hx-get="/hashtag/{match[1]}"
            hx-select="#explore-column"
            hx-target="#explore-column"
            hx-push-url=true
        >#{match[1]}</a>"""

    text = html.escape(text, quote=False)

    for tag, regex in YT_MARKUP.items():
        text = regex.sub(rf"<{tag}>\1</{tag}>", text)

    text = URL.sub(r'<a href="\1">\1</a>', text)
    text = HASHTAGS.sub(format_hashtag, text)
    return text
