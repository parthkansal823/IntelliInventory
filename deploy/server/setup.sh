#!/usr/bin/env bash
# One-time setup of your real shop on a fresh Ubuntu server (Oracle Cloud Always Free, any VPS, or your own PC).
#   curl -fsSL https://raw.githubusercontent.com/parthkansal823/IntelliInventory/main/deploy/server/setup.sh | bash
set -euo pipefail
REPO="${REPO:-https://github.com/parthkansal823/IntelliInventory.git}"
DIR="${DIR:-$HOME/IntelliInventory}"

echo "==> Installing Docker + git (if missing)"
command -v git > /dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq git; }
command -v docker > /dev/null || curl -fsSL https://get.docker.com | sudo sh

echo "==> Getting the code into $DIR"
[ -d "$DIR/.git" ] || git clone -q "$REPO" "$DIR"
cd "$DIR/deploy/server"

if [ ! -f .env ]; then
  echo "==> Your shop login (you can change the password later in the app)"
  read -rp "   Admin email: " ADMIN_EMAIL < /dev/tty
  read -rsp "   Admin password (min 8 chars): " ADMIN_PASSWORD < /dev/tty; echo
  IP="$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')"
  DOMAIN="${IP//./-}.sslip.io"
  rnd() { openssl rand -hex 24; }
  cat > .env <<ENV
DEMO_MODE=false
ADMIN_EMAIL=$ADMIN_EMAIL
ADMIN_NAME=Owner
ADMIN_PASSWORD=$ADMIN_PASSWORD
SECRET_KEY=$(rnd)
INTEGRATION_TOKEN=$(rnd)
POSTGRES_PASSWORD=$(rnd)
HERMES_MODEL=hermes3:3b
COMPOSE_PROFILES=https
DOMAIN=$DOMAIN
PUBLIC_URL=https://$DOMAIN
ENV
  chmod 600 .env
fi

echo "==> Opening ports 80/443 in the server firewall (Oracle images block them by default)"
if command -v iptables > /dev/null; then
  for port in 80 443; do
    sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2> /dev/null || sudo iptables -I INPUT 5 -p tcp --dport "$port" -j ACCEPT
  done
  command -v netfilter-persistent > /dev/null && sudo netfilter-persistent save > /dev/null || true
fi

echo "==> Building and starting (first time: 5-15 minutes, the Hermes model is ~2 GB)"
sudo docker compose up -d --build

# shellcheck disable=SC1091
. ./.env
echo
echo "✅ Done. Open: ${PUBLIC_URL:-http://$(hostname -I | awk '{print $1}'):8000}"
echo "   Login: $ADMIN_EMAIL   (Hermes AI becomes available once the model download finishes)"
echo "   Tunnel instead of HTTPS? set COMPOSE_PROFILES=tunnel in .env, then:"
echo "   sudo docker compose up -d && sudo docker compose logs tunnel | grep trycloudflare"
