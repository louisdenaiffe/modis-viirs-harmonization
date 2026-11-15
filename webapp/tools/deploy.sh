#!/bin/bash
# Publish the app as a public website on Cloudflare (https://fire-globe.<your-subdomain>.workers.dev).
#
#     tools/deploy.sh            # first time: run "npx wrangler login" once before this
#
# Only what the website needs is uploaded: the page, its code, the country outlines and the
# converted data. The raw NASA CSVs (data/raw), your NASA key, the git history and the
# tools are left out. Files are staged with hard links, so staging takes no extra disk space.
# Re-run it after every change; Cloudflare only uploads the files that changed.
set -euo pipefail
APP="$(cd "$(dirname "$0")/.." && pwd)"
SITE="$(dirname "$APP")/fire-globe-site"

rm -rf "$SITE"
mkdir -p "$SITE"
cp "$APP/index.html" "$APP/app.js" "$APP/icon.svg" "$SITE/"
rsync -a "$APP/vendor" "$APP/geo" "$SITE/"
mkdir -p "$SITE/data"
for item in meta.json coarse.bin countries.bin blocks tiles heat0 heat1; do
  [ -e "$APP/data/$item" ] || continue
  rsync -a --link-dest="$APP/data/" "$APP/data/$item" "$SITE/data/"
done
# Gzip copies of the files the app reads whole (see fetchWhole in app.js): about 3x smaller.
# -n leaves out the time stamp, so unchanged files stay identical and are not uploaded again.
for f in "$SITE/data/coarse.bin" "$SITE/data/countries.bin" "$SITE"/data/heat0/*.bin; do
  [ -e "$f" ] && gzip -9 -n -c "$f" > "$f.gz"
done
echo "Staged $(find "$SITE" -type f | wc -l | tr -d ' ') files ($(du -sh "$SITE" | cut -f1)) in $SITE"

# Published as a Cloudflare Worker serving static files (Cloudflare's replacement for Pages),
# using tools/wrangler.jsonc, whose only folder is the staged site above.
cd "$APP"
exec npx --yes wrangler@4 deploy --config "$APP/tools/wrangler.jsonc" "$@"
