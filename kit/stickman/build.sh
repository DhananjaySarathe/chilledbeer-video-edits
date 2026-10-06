#!/bin/sh
# Copy the rig + gsap + fonts into the sheet and demo projects (HyperFrames serves only the project folder).
#   sh build.sh && (cd sheet && npx hyperframes snapshot --at 0.5 --no-end --describe false -o out)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
KIT="$HERE/.."
GSAP="$KIT/../node_modules/gsap/dist/gsap.min.js"          # the repo root's npm install (./setup.sh)
for d in sheet demo demo2; do
  mkdir -p "$HERE/$d/vendor" "$HERE/$d/assets/fonts"
  cp "$HERE/stickman.js" "$GSAP" "$HERE/$d/vendor/"
  cp "$KIT/fonts/InstrumentSerif-Regular.ttf" "$KIT/fonts/InstrumentSerif-Italic.ttf" "$KIT/fonts/Inter-600.ttf" "$KIT/fonts/Inter-800.ttf" "$HERE/$d/assets/fonts/"
  printf '{ "paths": { "assets": "assets" } }\n' > "$HERE/$d/hyperframes.json"
done
echo "stickman: vendor files copied"
