#!/bin/bash
# Copy the app from this folder into the team repository's branch (in its webapp/ folder),
# commit it and push it. Run it whenever you want the team's GitHub to have your latest work:
#
#     tools/publish_to_team.sh "What changed"
#
# The team branch lives in a second folder next to this one (fire-globe-team), created the
# first time. Generated data (data/), your NASA key and local files are never copied.
set -euo pipefail
APP="$(cd "$(dirname "$0")/.." && pwd)"
TEAM="$(dirname "$APP")/fire-globe-team"
BRANCH="lucille-fire-globe-v2"
MESSAGE="${1:-Update Fire Globe web app}"

if [ ! -d "$TEAM" ]; then
  git -C "$APP" fetch -q upstream
  git -C "$APP" worktree add -q "$TEAM" "$BRANCH"
fi
cd "$TEAM"
git fetch -q upstream
git merge -q --ff-only "upstream/$BRANCH" 2>/dev/null || true   # pick up anything teammates pushed

rsync -a --delete \
  --exclude '.git' --exclude 'data/' --exclude '.firms_key' --exclude '.gitignore' \
  --exclude '__pycache__/' --exclude '.DS_Store' --exclude '.wrangler/' \
  "$APP/" "$TEAM/webapp/"

git add -A webapp
if git diff --cached --quiet; then
  echo "Nothing new to publish."
  exit 0
fi
git commit -q -m "$MESSAGE"
git push -u upstream "$BRANCH"
echo "Published to $BRANCH."
