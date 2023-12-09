#!/usr/bin/env sh
set -e

dir="$(dirname "$0")/xrtube/static/"
wget -nv https://unpkg.com/htmx.org@^1.9.9 -O "$dir/htmx.min.js"
wget -nv https://unpkg.com/video.js@^8.6.1/dist/video.min.js -O "$dir/video.min.js"
wget -nv https://unpkg.com/video.js@^8.6.1/dist/video-js.min.css -O "$dir/video-js.min.css"
wget -nv https://cdn.jsdelivr.net/npm/modern-normalize/modern-normalize.min.css -O "$dir/modern-normalize.min.css"
