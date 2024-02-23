#!/usr/bin/env sh
set -e

base="$(dirname "$0")/xrtube/npm"

get() { url_path="$1"
    file="$base/$url_path"
    mkdir -p "$(dirname "$file")"
    wget -nv "https://cdn.jsdelivr.net/npm/$url_path" -O "$file" &
}

rm -rf "$base"
mkdir "$base"
get htmx.org@^1.9.9/dist/htmx.min.js
get modern-normalize@^2.0.0/modern-normalize.min.css
get xgplayer@^2.31.8/browser/index.js 
get xgplayer-hls.js@^2.6.4/browser/index.js 
wait
