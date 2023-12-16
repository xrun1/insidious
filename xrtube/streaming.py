from __future__ import annotations

import io
import logging as log
import math
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

from construct import Container, StreamError
from pymp4.parser import Box

if TYPE_CHECKING:
    from xrtube.ytdl import Format, Video

HLS_M3U8_MIME = "application/vnd.apple.mpegurl"


def master_playlist(api: str, video: Video) -> str:
    content = "".join(
        "".join(_master_entry(api, f, *video.formats)) for f in video.formats
    ).rstrip()
    return f"#EXTM3U\n#EXT-X-VERSION:7\n{content}"


async def variant_playlist(uri: str, mp4_data: AsyncIterator[bytes]) -> str:
    return "".join([part async for part in _variant_playlist(uri, mp4_data)])


def _master_entry(api: str, format: Format, *all: Format) -> Iterator[str]:
    if format.container not in ("mp4_dash", "m4a_dash"):
        return
    if format.protocol == "http_dash_segments":  # TODO
        return

    if not format.vcodec:
        yield "#EXT-X-MEDIA:"
        yield "TYPE=AUDIO,"
        yield 'NAME="%s",' % (format.name or "default").capitalize()
        yield 'GROUP-ID="%s",' % format.id.removesuffix("-drc")
        if format.audio_channels:
            yield 'CHANNELS="%d",' % format.audio_channels
        if format.language:
            yield 'LANGUAGE="%s",' % format.language
        if not format.id.endswith("-drc"):  # Dynamic Range Compression
            yield "DEFAULT=YES,"
            yield "AUTOSELECT=YES,"
        yield 'URI="%s"\n' % (api % quote(format.url))
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
        yield (api % quote(format.url)) + "\n"


    audio_groups: dict[str, list[Format]] = {}
    for f in all:
        if not f.vcodec and f.acodec and f.container == "m4a_dash" and \
                f.protocol != "http_dash_segments":
            audio_groups.setdefault(f.id.removesuffix("-drc"), []).append(f)

    if format.acodec or not audio_groups:
        yield from stream(None)
    else:
        for group_name, formats in audio_groups.items():
            yield from stream(group_name, *formats)


async def _mp4_boxes(
    mp4_data: AsyncIterator[bytes],
) -> tuple[Container, Container, Container]:
    filetype = movie = segments = None
    buffer = io.BytesIO()

    async for chunk in mp4_data:
        initial = buffer.tell()
        buffer.write(chunk)
        buffer.seek(initial)

        while True:
            try:
                box = cast(Container, Box.parse_stream(buffer))
            except StreamError:
                buffer.seek(initial)
                break
            else:
                if box.type == "ftyp":
                    filetype = box
                elif box.type == "moov":
                    movie = box
                elif box.type == "sidx":
                    segments = box

                if filetype and movie and segments:
                    log.info("Found boxes after %d bytes", buffer.tell())
                    return (filetype, movie, segments)

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
        round(seg.segment_duration / segments.data.timescale)
        for seg in segments.data.references
    ), default=0)

    for seg in segments.data.references:
        yield "#EXTINF:%f,\n" % (seg.segment_duration / segments.data.timescale)
        yield "#EXT-X-BYTERANGE:%d@%d\n" % (seg.referenced_size, offset)
        yield "%s\n" % uri
        offset += seg.referenced_size

    yield "#EXT-X-ENDLIST"
