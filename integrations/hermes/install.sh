#!/usr/bin/env bash
# Install the IntelliInventory pack into Hermes Agent (~/.hermes): plugin, gateway hook and skill.
# Usage: ./integrations/hermes/install.sh [--http]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

mkdir -p "$HERMES_HOME/plugins" "$HERMES_HOME/hooks" "$HERMES_HOME/skills/productivity"
cp -R "$HERE/plugins/intelliinventory" "$HERMES_HOME/plugins/"
cp -R "$HERE/hooks/intelliinventory-audit" "$HERMES_HOME/hooks/"
cp -R "$HERE/skills/intelliinventory" "$HERMES_HOME/skills/productivity/"
echo "✔ Installed plugin, gateway hook and skill into $HERMES_HOME"

echo
echo "Add this to $HERMES_HOME/config.yaml (mcp_servers section):"
echo
if [[ "${1:-}" == "--http" ]]; then
cat <<YAML
mcp_servers:
  intelliinventory:
    url: "http://localhost:8000/mcp/"
    headers:
      Authorization: "Bearer \${INTELLIINVENTORY_TOKEN:-hermes-dev-token}"
    timeout: 60
YAML
else
cat <<YAML
mcp_servers:
  intelliinventory:
    command: "uv"
    args: ["run", "--directory", "$REPO/backend", "python", "-m", "app.mcp_server"]
    timeout: 60
    connect_timeout: 20
YAML
fi
echo
echo "Then restart Hermes and try:  hermes  →  \"What should I reorder today?\""
