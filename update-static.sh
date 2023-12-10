#!/usr/bin/env sh
set -e

get() { wget -nv "$1" -O "$(dirname "$0")/xrtube/static/${1##*/}" & }
get https://unpkg.com/htmx.org@^1.9.9/dist/htmx.min.js
get https://unpkg.com/video.js@^8.6.1/dist/video.min.js
get https://unpkg.com/video.js@^8.6.1/dist/video-js.min.css
get https://cdn.jsdelivr.net/npm/modern-normalize/modern-normalize.min.css
wait
