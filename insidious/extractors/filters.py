import operator
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from enum import IntEnum, IntFlag, auto
from functools import reduce
from typing import (
    TYPE_CHECKING,
    Annotated,
    ClassVar,
    Literal,
    Optional,
    Self,
    TypeAlias,
)
from urllib.parse import quote_plus, unquote_plus

from pure_protobuf.annotations import Field
from pure_protobuf.message import BaseMessage

if TYPE_CHECKING:
    One: TypeAlias = Literal[1]
else:
    One: TypeAlias = int  # pure_probobuf doesn't like Literal


class Date(IntEnum):
    Any = 0
    LastHour = 1
    Today = 2
    ThisWeek  = 3
    ThisMonth = 4
    ThisYear = 5


class Type(IntEnum):
    Any = 0
    Video = 1
    Channel = 2
    Playlist = 3
    Movie = 4


class Duration(IntEnum):
    Any = 0
    Under4Min = 1
    Over20Min = 2
    From4To20Min = 3


class Features(IntFlag):
    Any = 0
    Live = auto()
    In4K  = auto()
    HD = auto()
    Subtitles  = auto()
    CreativeCommons = auto()
    In360 = auto()
    VR180 = auto()
    In3D = auto()
    HDR = auto()
    Location = auto()
    Purchased = auto()


class Sort(IntEnum):
    Relevance = 0
    Rating = 1
    Date = 2
    Views = 3


@dataclass(slots=True)
class SearchFilter:
    date: Date = Date.Any
    type: Type = Type.Any
    duration: Duration = Duration.Any
    features: Features = Features.Any
    sort: Sort = Sort.Relevance
    allow_self_harm_results: bool = True

    _feature_attrs: ClassVar[dict[str, Features]] = {
        "hd": Features.HD,
        "subtitles": Features.Subtitles,
        "creative_commons": Features.CreativeCommons,
        "in_3d": Features.In3D,
        "live": Features.Live,
        "purchased": Features.Purchased,
        "in_4k": Features.In4K,
        "in_360": Features.In360,
        "location": Features.Location,
        "hdr": Features.HDR,
        "vr180": Features.VR180,
    }

    @property
    def url_parameter(self) -> str:
        buffer = _Buffer(
            filters = _Buffer.Filters(
                date = self.date or None,
                type = self.type or None,
                duration = self.duration or None,
                **{  # type: ignore
                    attr: 1 if self.features & feat else None
                    for attr, feat in self._feature_attrs.items()
                },
            ),
            sort = self.sort or None,
            allow_self_harm_results =
                1 if self.allow_self_harm_results else None,
        )
        return quote_plus(urlsafe_b64encode(bytes(buffer)).decode())

    @classmethod
    def parse(cls, url_parameter: str) -> Self:
        buffer = _Buffer.loads(urlsafe_b64decode(unquote_plus(url_parameter)))
        filters = buffer.filters or _Buffer.Filters()
        return cls(
            date = filters.date or Date.Any,
            type = filters.type or Type.Any,
            duration = filters.duration or Duration.Any,
            features = reduce(operator.__or__, (
                feat for attr, feat in cls._feature_attrs.items()
                if getattr(filters, attr)
            ), Features.Any),
            sort = buffer.sort or Sort.Relevance,
            allow_self_harm_results = bool(buffer.allow_self_harm_results),
        )


# ruff: noqa: UP007
@dataclass(slots=True)
class _Buffer(BaseMessage):
    @dataclass(slots=True)
    class Filters(BaseMessage):
        date: Annotated[Optional[Date], Field(1)] = None
        type: Annotated[Optional[Type], Field(2)] = None
        duration: Annotated[Optional[Duration], Field(3)] = None
        hd: Annotated[Optional[One], Field(4)] = None
        subtitles: Annotated[Optional[One], Field(5)] = None
        creative_commons: Annotated[Optional[One], Field(6)] = None
        in_3d: Annotated[Optional[One], Field(7)] = None
        live: Annotated[Optional[One], Field(8)] = None
        purchased: Annotated[Optional[One], Field(9)] = None
        in_4k: Annotated[Optional[One], Field(14)] = None
        in_360: Annotated[Optional[One], Field(15)] = None
        location: Annotated[Optional[One], Field(23)] = None
        hdr: Annotated[Optional[One], Field(25)] = None
        vr180: Annotated[Optional[One], Field(26)] = None

    filters: Annotated[Optional[Filters], Field(2)] = None
    sort: Annotated[Optional[Sort], Field(1)] = None
    allow_self_harm_results: Annotated[Optional[One], Field(9)] = 1
