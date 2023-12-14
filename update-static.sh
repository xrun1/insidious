#!/usr/bin/env sh
set -e

get() { wget -nv "$1" -O "$(dirname "$0")/xrtube/static/${1##*/}" & }
get https://unpkg.com/htmx.org@^1.9.9/dist/htmx.min.js
get https://cdn.jsdelivr.net/npm/modern-normalize/modern-normalize.min.css
get https://unpkg.com/video.js@^8.7.0/dist/video.min.js
get https://unpkg.com/video.js@^8.7.0/dist/video-js.min.css
get https://unpkg.com/videojs-contrib-quality-levels@4.0.0/dist/videojs-contrib-quality-levels.js
get https://unpkg.com/jb-videojs-hls-quality-selector@2.0.2/dist/jb-videojs-hls-quality-selector.js
wait
