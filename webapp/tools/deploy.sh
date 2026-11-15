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
# data/factors holds one small file per 1-degree tile (about 16,700), too many for Cloudflare's
# free plan (20,000 files per site). They are bundled here into one file per 10-degree block,
# data/factorpacks/<block>.bin: a 4-byte length, a JSON table {"tile": [offset, length]}, then
# the tiles' files one after the other. tools/worker.js answers the app's usual requests
# (data/factors/<tile>.bin) with the right piece, so the app and data/factors are unchanged.
if [ -d "$APP/data/factors" ]; then
  python3 -I - "$APP/data/factors" "$SITE/data/factorpacks" <<'PY'
import os, sys, json, struct, collections
src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)
packs = collections.defaultdict(list)
for name in sorted(os.listdir(src)):
    if not name.endswith('.bin'):
        continue
    la, lo = (int(v) for v in name[:-4].split('_'))
    packs[f'{la // 10 * 10}_{lo // 10 * 10}'].append(name)
for block, names in packs.items():
    table, parts, off = {}, [], 0
    for name in names:
        with open(os.path.join(src, name), 'rb') as f:
            b = f.read()
        table[name[:-4]] = [off, len(b)]
        parts.append(b)
        off += len(b)
    head = json.dumps(table, separators=(',', ':')).encode()
    with open(os.path.join(dst, block + '.bin'), 'wb') as f:
        f.write(struct.pack('<I', len(head)) + head + b''.join(parts))
print(f'Bundled {sum(map(len, packs.values()))} factor files into {len(packs)} packs')
PY
fi
# Gzip copies of the files the app reads whole (see fetchWhole in app.js): about 3x smaller.
# -n leaves out the time stamp, so unchanged files stay identical and are not uploaded again.
for f in "$SITE/data/coarse.bin" "$SITE/data/countries.bin" "$SITE"/data/heat0/*.bin "$SITE"/data/blocks/*.bin; do
  [ -e "$f" ] && gzip -9 -n -c "$f" > "$f.gz"
done
echo "Staged $(find "$SITE" -type f | wc -l | tr -d ' ') files ($(du -sh "$SITE" | cut -f1)) in $SITE"

# Published as a Cloudflare Worker serving static files (Cloudflare's replacement for Pages),
# using tools/wrangler.jsonc, whose only folder is the staged site above.
cd "$APP"
exec npx --yes wrangler@4 deploy --config "$APP/tools/wrangler.jsonc" "$@"
