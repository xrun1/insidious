#!/usr/bin/env sh
set -e

base="$(dirname "$0")/xrtube/npm"

get() { url_path="$1"
    file="$base/$url_path"
    dir="$(dirname "$file")"
    mkdir -p "$dir"
    wget -nv "https://cdn.jsdelivr.net/npm/$url_path" -O "$file" &
}

rm -rf "$base"
mkdir "$base"

get htmx.org@^1.9.9/dist/htmx.min.js
get modern-normalize@^2.0.0/modern-normalize.min.css
get media-chrome@3.2.0/+esm
get hls-video-element@1.1.3/+esm

# hls-video-element dependencies
get custom-media-element@1.2.3/+esm
get media-tracks@0.3.0/+esm
get hls.js@1.5.4/dist/hls.mjs/+esm

wait
