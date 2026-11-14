#!/bin/bash
# Publish the app to Cloudflare Pages as a public website (https://<project>.pages.dev).
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
PROJECT="${CF_PAGES_PROJECT:-fire-globe}"

rm -rf "$SITE"
mkdir -p "$SITE"
cp "$APP/index.html" "$APP/app.js" "$SITE/"
rsync -a "$APP/vendor" "$APP/geo" "$SITE/"
mkdir -p "$SITE/data"
for item in meta.json coarse.bin blocks tiles heat0 heat1; do
  rsync -a --link-dest="$APP/data/" "$APP/data/$item" "$SITE/data/"
done
echo "Staged $(find "$SITE" -type f | wc -l | tr -d ' ') files ($(du -sh "$SITE" | cut -f1)) in $SITE"

npx --yes wrangler@4 pages project create "$PROJECT" --production-branch main 2>/dev/null || true
npx --yes wrangler@4 pages deploy "$SITE" --project-name "$PROJECT" --branch main --commit-dirty=true
