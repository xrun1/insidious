# Copyright Insidious authors <https://github.com/xrun1/insidious>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Usage: {NAME} [options] [HOST] [PORT]

Start the {NAME} instance on http://localhost:8000 by default.
To make it accessible from outside this machine, use "0.0.0.0" as HOST.

Arguments:
    HOST  Adress to bind the server to, 127.0.0.1 if unspecified.
    PORT  Port to listen on, 8000 if unspecified.

Options:
    -r DIR, --reload DIR  Restart {NAME} when source code files in DIR change.
    -h, --help            Show this help and exit.
    --version             Show the {NAME} version and exit.
"""

import os
from pathlib import Path

import docopt
import uvicorn

from . import DISPLAY_NAME, NAME, __version__


def run() -> None:
    doc = __doc__.format(NAME=DISPLAY_NAME)
    args = docopt.docopt(doc, version=__version__)
    dir = args["--reload"]
    if dir:
        dir = Path(dir).resolve()  # We change the cwd later, "." would break
        os.putenv("UVICORN_RELOAD", dir)

    uvicorn.run(
        f"{NAME}.app:app",
        host = args["HOST"] or "127.0.0.1",
        port = int(args["PORT"] or 8000),
        reload = bool(dir),
        reload_dirs = [str(dir)] if dir else [],
        timeout_graceful_shutdown = 0,
    )


if __name__ == "__main__":
    run()
