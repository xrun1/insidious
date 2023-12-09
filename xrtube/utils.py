from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
import logging

class AutoStrEnum(Enum):
    """Enum where auto() value gives the name of the member"""
    @staticmethod
    def _generate_next_value_(name: str, *_):
        return name


def int_ratio(width, height) -> tuple[int, int]:
    """Return aspect ratio in int:int form for a width and height."""
    def greatest_common_divisor(a, b):
        while a:
            a, b = b % a, a
        return b
    gcd = greatest_common_divisor(width, height)
    return int(width / gcd), int(height / gcd)


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
