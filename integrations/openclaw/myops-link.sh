#!/usr/bin/env bash
# Connect OpenClaw (formerly Clawdbot) to the MyOps phone app, on your own computer or a cloud server.
#   curl -fsSL https://bsvahyfzpfnhkyzgmoow.supabase.co/functions/v1/openclaw-setup | bash
# What it does:
#   1. installs OpenClaw if it is missing (the official installer from openclaw.ai);
#   2. turns on the Gateway's OpenAI-compatible endpoint and sets a strong access token;
#   3. makes the Gateway reachable from your phone privately through Tailscale (never the open internet);
#   4. tests it, then prints a QR code and a pairing code to enter in MyOps (Account > Connect OpenClaw).
# Runs on macOS, Linux and Windows (inside WSL2). Safe to run again: it keeps an existing token.
set -euo pipefail

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1; }

say "MyOps × OpenClaw setup"

# ---- 1. OpenClaw ---------------------------------------------------------------------------------
if ! need openclaw; then
  say "Installing OpenClaw (official installer)…"
  curl -fsSL --proto '=https' --tlsv1.2 https://openclaw.ai/install.sh | bash -s -- --no-prompt --no-onboard
  export PATH="$HOME/.openclaw/bin:$HOME/.local/bin:$PATH"
  hash -r
  need openclaw || die "OpenClaw installed, but the 'openclaw' command is not on your PATH yet. Open a new terminal and run this setup again."
fi
echo "OpenClaw $(openclaw --version 2>/dev/null || echo installed)"

if [ ! -f "${OPENCLAW_CONFIG_PATH:-$HOME/.openclaw/openclaw.json}" ]; then
  say "First run: OpenClaw will ask which AI model it should use (your own key or login)."
  if [ -t 0 ] || [ -e /dev/tty ]; then openclaw onboard --install-daemon </dev/tty; else
    die "Run 'openclaw onboard --install-daemon' once in a terminal, then run this setup again."; fi
fi

# ---- 2. HTTP endpoint and token ------------------------------------------------------------------
TOKEN="$(openclaw config get gateway.auth.token 2>/dev/null | tr -d '"[:space:]' || true)"
if [ -z "$TOKEN" ] || [ "$TOKEN" = "undefined" ] || [ "$TOKEN" = "null" ]; then
  TOKEN="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40)"
fi
openclaw config set gateway.auth.mode token >/dev/null
openclaw config set gateway.auth.token "$TOKEN" >/dev/null
openclaw config set gateway.http.endpoints.chatCompletions.enabled true >/dev/null
echo "Gateway endpoint on, token set."

# ---- 3. Private access from the phone (Tailscale) ------------------------------------------------
URL=""
if need tailscale && tailscale status >/dev/null 2>&1; then
  openclaw config set gateway.bind loopback >/dev/null
  openclaw config set gateway.tailscale.mode serve >/dev/null
  HOST="$(tailscale status --json 2>/dev/null | sed -n 's/.*"DNSName": *"\([^"]*\)".*/\1/p' | head -n1 | sed 's/\.$//')"
  [ -n "$HOST" ] && URL="https://$HOST/v1"
else
  say "Tailscale is not set up on this machine."
  cat <<'EOF'
Your phone needs a private, encrypted way to reach OpenClaw. Tailscale (free for personal use) does that
without opening any port to the internet:
  1. Install it: https://tailscale.com/download (on a Linux server: curl -fsSL https://tailscale.com/install.sh | sh)
  2. Sign in:    sudo tailscale up
  3. Install the Tailscale app on your phone and sign in with the same account.
  4. Run this setup again.
EOF
  exit 1
fi
[ -n "$URL" ] || die "Couldn't read this machine's Tailscale name. Check 'tailscale status', then run this setup again."

# Apply: (re)start the Gateway service with the new settings.
if openclaw gateway status >/dev/null 2>&1; then
  openclaw gateway restart >/dev/null 2>&1 || openclaw gateway install --force >/dev/null 2>&1 || true
else
  openclaw gateway install >/dev/null 2>&1 || true
fi

# ---- 4. Test, then pair ---------------------------------------------------------------------------
say "Testing $URL …"
ok=""
for _ in $(seq 1 20); do
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/chat/completions" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"model":"openclaw","messages":[{"role":"user","content":"Reply with OK."}]}' || true)"
  if [ "$code" = "200" ]; then ok=1; break; fi
  sleep 3
done
[ -n "$ok" ] || die "The Gateway didn't answer at $URL (last status: ${code:-none}). Run 'openclaw doctor', check 'openclaw gateway status', then run this setup again."

b64() { base64 | tr -d '\n=' | tr '+/' '-_'; }
CODE="myops-oc:$(printf '{"u":"%s","t":"%s"}' "$URL" "$TOKEN" | b64)"
LINK="com.myops.app://openclaw?code=${CODE#myops-oc:}"

say "OpenClaw is ready for MyOps."
echo "Address: $URL"
if need qrencode; then
  echo; echo "Scan with your phone's camera (opens MyOps and links it):"; qrencode -t ansiutf8 "$LINK"
fi
echo
echo "Or in MyOps: Account > Connect OpenClaw > Link existing, and paste this pairing code:"
echo
echo "  $CODE"
echo
echo "Keep the code private: it is the key to your OpenClaw."
