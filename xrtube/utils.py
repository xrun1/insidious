from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
import logging

class AutoStrEnum(Enum):
    """Enum where auto() value gives the name of the member"""
    @staticmethod
    def _generate_next_value_(name: str, *_):
        return name


@contextmanager
def report(
    *types: type[Exception], msg: str | None = None
) -> Iterator[list[Exception]]:
    """On exceptions in `with` block, cancel the rest and log the error."""

    caught: list[Exception] = []
    try:
        yield caught
    except (types or Exception) as e:
        caught.append(e)
        logging.exception(msg or "Caught exception")
