#!/usr/bin/env bash
# Local frontend check (human-owned). Replaces Vercel previews for agents.
# Usage, from the task worktree root:  bash .claude/scripts/ui_check.sh <TASK_ID> <PORT> /path [/path ...]
# Builds the app in fixture mode, starts it on PORT, screenshots each path with a fresh headless
# Chromium (never a shared browser), saves PNGs to .claude/tasks/<TASK_ID>/evidence/, stops the server.
set -euo pipefail
ID="$1"; PORT="$2"; shift 2
ROOT="$(pwd)"
OUT="$ROOT/.claude/tasks/$ID/evidence"
mkdir -p "$OUT"
cd "$ROOT/frontend"
npm ci --prefer-offline --no-audit --no-fund >/dev/null
if ! NEXT_PUBLIC_API_MODE="${UI_MODE:-fixtures}" npm run build >"$OUT/build.log" 2>&1; then
  echo "BUILD FAILED (last 40 lines of $OUT/build.log):"; tail -n 40 "$OUT/build.log"; exit 1
fi
echo "build OK"
npx next start -p "$PORT" >"$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for i in $(seq 1 30); do
  curl -s -o /dev/null "http://localhost:$PORT" && break
  sleep 1
done
for P in "$@"; do
  NAME="$(echo "$P" | tr '/' '_' | sed 's/^_//')"; NAME="${NAME:-root}"
  npx playwright screenshot --browser chromium --wait-for-timeout 2000 --full-page \
    "http://localhost:$PORT$P" "$OUT/$NAME.png" >/dev/null
  echo "screenshot: .claude/tasks/$ID/evidence/$NAME.png"
done
echo "UI CHECK OK ($# page(s))"
