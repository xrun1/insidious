#!/usr/bin/env sh
set -e

dir="$(dirname "$0")/xrtube/static/"
wget -nv https://unpkg.com/htmx.org@^1.9.9 -O "$dir/htmx.min.js"
