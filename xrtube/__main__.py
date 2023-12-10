"""Usage: {NAME} [options] [HOST] [PORT]

Start the {NAME} service on http://localhost:8000 by default.

Options:
    -r DIR, --reload DIR  Restart {NAME} when source code files in DIR change.
    -h, --help            Show this help and exit.
    --version             Show the {NAME} version and exit.
"""

import os
import docopt
import uvicorn

from . import NAME, __version__


def run() -> None:
    args = docopt.docopt(__doc__.format(NAME=NAME), version=__version__)
    dir = args["--reload"]
    if dir:
        os.putenv("UVICORN_RELOAD", "1")

    uvicorn.run(
        f"{NAME}.app:APP",
        host = args["HOST"] or "127.0.0.1",
        port = int(args["PORT"] or 8000),
        reload = bool(dir),
        reload_dirs = [dir] if dir else [],
        reload_includes = ["*.jinja", "*.scss", "*.js"],
        timeout_graceful_shutdown = 0,
    )


if __name__ == "__main__":
    run()
