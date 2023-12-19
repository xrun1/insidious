from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
import logging
from fastapi import HTTPException

import httpx

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


@contextmanager
def httpx_to_fastapi_errors() -> Iterator[None]:
    try:
        yield
    except httpx.NetworkError as e:
        raise HTTPException(502, f"Couldn't reach target URL: {e}")
    except httpx.TimeoutException as e:
        raise HTTPException(504, f"Target URL timed out: {e}")
    except httpx.HTTPStatusError as e:
        detail = f"Target URL returned error: {e.response.reason_phrase}"
        raise HTTPException(e.response.status_code, detail)
