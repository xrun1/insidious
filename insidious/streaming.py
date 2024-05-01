from __future__ import annotations

import io
import logging as log
import math
import re
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

from construct import Container, StreamError
from pymp4.parser import Box

from insidious.utils import report

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from insidious.ytdl import Format, Video

HLS_MIME = "application/x-mpegURL"
HLS_ALT_MIME = "application/vnd.apple.mpegurl"
STREAM_TAGS_RE = re.compile(r"([A-Z\d_-]+=(?:\".*?\"|'.*?'|.*?))(?:,|$)")


def master_playlist(api: str, video: Video) -> str:
    content = "".join(
        "".join(_master_entry(api, f, *video.formats))
        for f in sorted(video.formats, key=lambda f:
            (f.height or 480, f.fps or 30, f.average_bitrate or 0),
        )
    ).rstrip()
    return f"#EXTM3U\n#EXT-X-VERSION:7\n{content}"


async def variant_playlist(uri: str, mp4_data: AsyncIterator[bytes]) -> str:
    return "".join([x async for x in _variant_playlist(uri, mp4_data)])


def dash_variant_playlist(api: str, format: Format) -> str:
    return "".join(_dash_variant_playlist(api, format))


def sort_master_playlist(content: str) -> str:
    """Sort streams by (height, fps, bandwidth). Required for hls.js."""
    lines = []
    streams = []
    is_stream = False

    for line in content.splitlines():
        if is_stream:
            streams[-1] += "\n" + line
            is_stream = False
        elif line.startswith("#EXT-X-STREAM-INF:"):
            streams.append(line)
            is_stream = True
        else:
            lines.append(line)

    def sort_key(stream: str) -> tuple[float, float, float]:
        tag_line = stream.splitlines()[0]
        parts = (p for p in STREAM_TAGS_RE.split(tag_line) if "=" in p)
        tags = dict(t.split("=", maxsplit=1) for t in parts)

        with report(ValueError, IndexError):
            height = int(tags.get("RESOLUTION", "0,0").split("x")[1])
            fps = float(tags.get("FRAME-RATE", "30"))
            bw = int(tags.get("AVERAGE-BANDWIDTH") or tags.get("BANDWIDTH", 0))
            return (height, fps, bw)

    streams.sort(key=sort_key)
    return "\n".join(lines + streams)


def _master_entry(api: str, format: Format, *all: Format) -> Iterator[str]:
    has_any_dash = any(f.has_dash for f in all)

    def can_use(fmt: Format) -> bool:
        if has_any_dash and not fmt.has_dash:
            return False
        if has_any_dash and not fmt.vcodec and "-dash" not in fmt.id:
            return False
        return fmt.container in {"mp4_dash", "m4a_dash"}

    if not can_use(format):
        return

    if not format.vcodec:
        yield "#EXT-X-MEDIA:"
        yield "TYPE=AUDIO,"
        yield 'NAME="%s",' % (format.name or "default").capitalize().replace(
            ", drc", ", compressed dynamics",
        )
        yield 'GROUP-ID="%s",' % format.id.removesuffix("-drc")
        if format.audio_channels:
            yield 'CHANNELS="%d",' % format.audio_channels
        if format.language:
            yield 'LANGUAGE="%s",' % format.language
        if not format.id.endswith("-drc"):
            yield "DEFAULT=YES,"
            yield "AUTOSELECT=YES,"
        yield 'URI="%s"\n' % (api + format.id)
        return

    def stream(
        audio_group: str | None = None, *audio_formats: Format,
    ) -> Iterator[str]:

        bitrate = format.average_bitrate or 0
        yield "#EXT-X-STREAM-INF:"

        if format.width and format.height:
            yield "RESOLUTION=%dx%d," % (format.width, format.height)
        if format.fps:
            yield "FRAME-RATE=%s," % round(format.fps, 3)
        if format.dynamic_range:
            yield "VIDEO-RANGE=%s," % format.dynamic_range

        if audio_group and audio_formats:
            acodecs = ",".join({cast(str, f.acodec) for f in audio_formats})
            yield 'CODECS="%s,%s",' % (format.vcodec, acodecs)
            yield 'AUDIO="%s",' % audio_group
            bitrate += max(f.average_bitrate or 0 for f in audio_formats)
        else:
            yield 'CODECS="%s",' % format.vcodec

        yield "BANDWIDTH=%d\n" % math.ceil(bitrate * 1000)
        yield (api + format.id) + "\n"

    audio_groups: dict[str, list[Format]] = {}
    for f in all:
        if can_use(f) and not f.vcodec and f.acodec:
            audio_groups.setdefault(f.id.removesuffix("-drc"), []).append(f)

    if format.acodec or not audio_groups:
        yield from stream(None)
    else:
        for group_name, formats in audio_groups.items():
            yield from stream(group_name, *formats)


def filter_master_playlist(content: str, height: int, fps: float) -> str:
    skip = False
    lines = []
    for line in content.splitlines():
        if skip:
            skip = False
            continue
        if line.startswith("#EXT-X-STREAM-INF:"):
            parts = (p for p in STREAM_TAGS_RE.split(line) if "=" in p)
            tags = dict(t.split("=", maxsplit=1) for t in parts)
            with report(ValueError, IndexError):
                stream_h = int(tags.get("RESOLUTION", "0,0").split("x")[1])
                stream_fps = float(tags.get("FRAME-RATE", "30"))
                if stream_h != height or stream_fps != fps:
                    skip = True
                    continue
        lines.append(line)
    return "\n".join(lines)


async def _mp4_boxes(
    mp4_data: AsyncIterator[bytes],
) -> tuple[Container, Container, Container]:
    filetype = movie = segments = None
    buffer = io.BytesIO()

    async for chunk in mp4_data:
        buffer.write(chunk)
        buffer.seek(0)

        try:
            while True:
                box = cast(Container, Box.parse_stream(buffer))
                if box.type == "ftyp":
                    filetype = box
                elif box.type == "moov":
                    movie = box
                elif box.type == "sidx":
                    segments = box

                if filetype and movie and segments:
                    log.info("Found boxes after %d bytes", buffer.tell())
                    return (filetype, movie, segments)
        except StreamError:
            pass

    raise ValueError(f"Missing boxes - {filetype=}, {movie=}, {segments=}")


async def _variant_playlist(
    uri: str, mp4_data: AsyncIterator[bytes],
) -> AsyncIterator[str]:
    filetype, movie, segments = await _mp4_boxes(mp4_data)
    segments_end = filetype.end + movie.end + segments.end
    offset = segments_end + segments.data.first_offset

    yield "#EXTM3U\n"
    yield "#EXT-X-VERSION:7\n"
    yield "#EXT-X-INDEPENDENT-SEGMENTS\n"
    yield '#EXT-X-MAP:URI="%s",BYTERANGE="%d@0"\n' % (uri, segments_end)
    yield "#EXT-X-TARGETDURATION:%d\n" % max((
        round(sg.segment_duration / segments.data.timescale)
        for sg in segments.data.references
    ), default=0)

    for sg in segments.data.references:
        yield "#EXTINF:%f,\n" % (sg.segment_duration / segments.data.timescale)
        yield "#EXT-X-BYTERANGE:%d@%d\n" % (sg.referenced_size, offset)
        yield "%s\n" % uri
        offset += sg.referenced_size

    yield "#EXT-X-ENDLIST"


def _dash_variant_playlist(api: str, format: Format) -> Iterator[str]:
    assert format.dash_fragments_base_url
    assert format.fragments
    assert format.fragments[0].path
    assert not format.fragments[0].duration

    base_url = api % quote(format.dash_fragments_base_url)
    init_url = base_url + quote(format.fragments[0].path)

    yield "#EXTM3U\n"
    yield "#EXT-X-VERSION:7\n"
    yield "#EXT-X-INDEPENDENT-SEGMENTS\n"
    yield '#EXT-X-MAP:URI="%s"\n' % init_url
    yield "#EXT-X-TARGETDURATION:%d\n" % max((
        round(f.duration) for f in format.fragments if f.duration
    ), default=0)

    for frag in format.fragments:
        if frag.duration and frag.path:
            yield "#EXTINF:%f,\n" % frag.duration
            yield "%s%s\n" % (base_url, quote(frag.path))

    yield "#EXT-X-ENDLIST"
