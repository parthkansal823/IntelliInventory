#!/usr/bin/env bash
# Update the server to a commit (default: latest main). Run by the Deploy workflow over SSH after CI passes.
#   bash deploy/server/update.sh [commit-sha]
set -euo pipefail
cd "$(dirname "$0")/../.."
git fetch -q origin main
git checkout -q main
git reset -q --hard "${1:-origin/main}"
cd deploy/server
sudo docker compose up -d --build --remove-orphans
sudo docker image prune -f > /dev/null
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${APP_PORT:-8000}/api/health" > /dev/null 2>&1; then
    echo "✅ Deployed $(git rev-parse --short HEAD)"
    exit 0
  fi
  sleep 5
done
echo "❌ App did not become healthy - last logs:"
sudo docker compose logs --tail 80 app
exit 1
