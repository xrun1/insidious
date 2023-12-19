#!/usr/bin/env sh
set -e

get() {
    file="${2:-$1}"
    wget -nv "$1" -O "$(dirname "$0")/xrtube/static/${file##*/}" &
}
get https://unpkg.com/htmx.org@^1.9.9/dist/htmx.min.js
get https://cdn.jsdelivr.net/npm/modern-normalize/modern-normalize.min.css
get https://unpkg.com/xgplayer@^2.31.8/browser/index.js xgplayer.js
get https://unpkg.com/xgplayer-hls.js@^2.6.4/browser/index.js xgplayer-hlsjs.js
wait
