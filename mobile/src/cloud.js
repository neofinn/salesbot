// Create a MyOps cloud server from the phone: a VPS on the owner's own DigitalOcean or Hetzner account that
// runs OpenClaw and the MyOps server app 24/7 (the team keeps working when the phone is off), reachable only
// through the owner's Tailscale network. The cloud API token stays on the phone; the server reports its setup
// progress to the owner's MyOps account with a one-time secret.
import { SUPABASE_URL } from "./config.js";
import { supabase } from "./session.js";

export const REPORT_URL = `${SUPABASE_URL}/functions/v1/server-report`;
const REPO = "https://github.com/neofinn/salesbot.git";

// OpenClaw can be set up unattended with these platforms (its documented non-interactive auth choices).
export const SERVER_AI = {
  anthropic: { label: "Anthropic Claude", env: "ANTHROPIC_API_KEY", onboard: "--auth-choice apiKey --anthropic-api-key" },
  gemini: { label: "Google Gemini", env: "GEMINI_API_KEY", onboard: "--auth-choice gemini-api-key --gemini-api-key" },
};

const rand = (n = 32) => {
  const a = crypto.getRandomValues(new Uint8Array(n));
  return [...a].map((b) => "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"[b % 62]).join("");
};
async function sha256(text) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
// Single-quote a value for bash.
const q = (v) => `'${String(v).replace(/'/g, `'"'"'`)}'`;

export function bootstrapScript({ id, secret, name, tsKey, ai, aiKey, ocToken, webToken }) {
  const a = SERVER_AI[ai];
  return `#!/bin/bash
# MyOps cloud server setup (runs once at first boot). Log: /var/log/myops-setup.log
set -uo pipefail
exec >>/var/log/myops-setup.log 2>&1
ID=${q(id)}; SECRET=${q(secret)}; NAME=${q(name)}; REPORT=${q(REPORT_URL)}
TS_KEY=${q(tsKey)}; AI_KEY=${q(aiKey)}; OC_TOKEN=${q(ocToken)}; WEB_TOKEN=${q(webToken)}
export DEBIAN_FRONTEND=noninteractive HOME=/root
report() { curl -fsS -m 20 -X POST "$REPORT" -H 'content-type: application/json' \\
  -d "{\\"id\\":\\"$ID\\",\\"secret\\":\\"$SECRET\\",\\"status\\":\\"$1\\",\\"detail\\":\\"$2\\"\${3:-}}" >/dev/null || true; }
fail() { report failed "$1"; exit 1; }

report installing "Installing Tailscale"
apt-get update -qq && apt-get install -y -qq curl git python3-venv python3-pip ca-certificates >/dev/null || fail "Couldn't install system packages"
curl -fsSL https://tailscale.com/install.sh | sh || fail "Tailscale install failed"
tailscale up --authkey="$TS_KEY" --hostname="$NAME" || fail "Tailscale sign-in failed: check the auth key"
HOST="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
[ -n "$HOST" ] || fail "Couldn't read the Tailscale name"

report installing "Installing OpenClaw"
loginctl enable-linger root; export XDG_RUNTIME_DIR=/run/user/0
for _ in $(seq 1 15); do [ -d "$XDG_RUNTIME_DIR" ] && break; sleep 2; done
curl -fsSL --proto '=https' --tlsv1.2 https://openclaw.ai/install.sh | bash -s -- --no-prompt --no-onboard || fail "OpenClaw install failed"
export PATH="/root/.openclaw/bin:/root/.local/bin:/usr/local/bin:$PATH"
command -v openclaw >/dev/null || fail "openclaw command not found after install"
openclaw onboard --non-interactive --accept-risk ${a.onboard} "$AI_KEY" --install-daemon --daemon-runtime node || fail "OpenClaw setup failed: check the ${a.label} key"
openclaw config set gateway.bind loopback
openclaw config set gateway.auth.mode token
openclaw config set gateway.auth.token "$OC_TOKEN"
openclaw config set gateway.http.endpoints.chatCompletions.enabled true
openclaw gateway restart || openclaw gateway install --force || true
tailscale serve --bg --https=443 http://127.0.0.1:18789 || fail "Couldn't publish OpenClaw on the private network"

report installing "Installing the MyOps server app"
rm -rf /opt/myops && git clone --depth 1 ${q(REPO)} /opt/myops || fail "Couldn't download MyOps"
python3 -m venv /opt/myops/.venv && /opt/myops/.venv/bin/pip install -q /opt/myops || fail "Couldn't install MyOps"
mkdir -p /var/lib/myops
cat >/etc/myops.env <<EOF
${a.env}=$AI_KEY
SALESBOT_DATA_DIR=/var/lib/myops
SALESBOT_WEB_HOST=127.0.0.1
PORT=8000
SALESBOT_WEB_TOKEN=$WEB_TOKEN
SALESBOT_PUBLIC_URL=https://$HOST:8443
OPENCLAW_URL=http://127.0.0.1:18789
OPENCLAW_TOKEN=$OC_TOKEN
EOF
chmod 600 /etc/myops.env
cat >/etc/systemd/system/myops.service <<'EOF'
[Unit]
Description=MyOps server app (the team, working in the background)
After=network-online.target
[Service]
EnvironmentFile=/etc/myops.env
WorkingDirectory=/opt/myops
ExecStart=/opt/myops/.venv/bin/python -m salesbot web
Restart=always
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now myops || fail "Couldn't start MyOps"
tailscale serve --bg --https=8443 http://127.0.0.1:8000 || fail "Couldn't publish MyOps on the private network"

report installing "Checking everything works"
ok=""
for _ in $(seq 1 30); do
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:18789/v1/chat/completions \\
    -H "Authorization: Bearer $OC_TOKEN" -H 'Content-Type: application/json' \\
    -d '{"model":"openclaw","messages":[{"role":"user","content":"Reply with OK."}]}')"
  [ "$code" = "200" ] && ok=1 && break
  sleep 5
done
[ -n "$ok" ] || fail "OpenClaw didn't answer (status \${code:-none}); see /var/log/myops-setup.log"
report ready "Ready" ",\\"openclaw_url\\":\\"https://$HOST/v1\\",\\"myops_url\\":\\"https://$HOST:8443\\""
`;
}

// ---------- cloud providers (called straight from the phone with the owner's token) ----------
async function api(url, token, init = {}) {
  const res = await fetch(url, { ...init, headers: { authorization: `Bearer ${token}`, "content-type": "application/json", ...(init.headers || {}) } });
  const text = await res.text();
  let body = {}; try { body = text ? JSON.parse(text) : {}; } catch { /* not JSON */ }
  if (!res.ok) throw new Error(body.message || body.error?.message || body.error || `${res.status} ${text.slice(0, 200)}`);
  return body;
}

export const CLOUDS = {
  digitalocean: {
    label: "DigitalOcean", tokenUrl: "https://cloud.digitalocean.com/account/api/tokens",
    async options(token) {
      const [s, r] = await Promise.all([api("https://api.digitalocean.com/v2/sizes?per_page=200", token), api("https://api.digitalocean.com/v2/regions?per_page=200", token)]);
      const sizes = s.sizes.filter((x) => x.available && x.memory >= 2048 && x.memory <= 8192 && x.slug.startsWith("s-"))
        .sort((a, b) => a.price_monthly - b.price_monthly)
        .map((x) => ({ id: x.slug, label: `${x.vcpus} CPU, ${x.memory / 1024} GB RAM · $${x.price_monthly}/month`, regions: x.regions }));
      const regions = r.regions.filter((x) => x.available).map((x) => ({ id: x.slug, label: x.name }));
      return { sizes, regions };
    },
    async create(token, { name, size, region, userData }) {
      const b = await api("https://api.digitalocean.com/v2/droplets", token, { method: "POST",
        body: JSON.stringify({ name, size, region, image: "ubuntu-24-04-x64", user_data: userData, tags: ["myops"] }) });
      return String(b.droplet.id);
    },
    destroy: (token, id) => api(`https://api.digitalocean.com/v2/droplets/${id}`, token, { method: "DELETE" }),
  },
  hetzner: {
    label: "Hetzner", tokenUrl: "https://console.hetzner.cloud/ (Project > Security > API tokens, Read & Write)",
    async options(token) {
      const [t, l] = await Promise.all([api("https://api.hetzner.cloud/v1/server_types?per_page=50", token), api("https://api.hetzner.cloud/v1/locations", token)]);
      const sizes = t.server_types.filter((x) => !x.deprecated && x.architecture === "x86" && x.memory >= 2 && x.memory <= 8)
        .map((x) => ({ id: x.name, price: Number(x.prices?.[0]?.price_monthly?.gross || 0), label: `${x.cores} CPU, ${x.memory} GB RAM · €${Number(x.prices?.[0]?.price_monthly?.gross || 0).toFixed(2)}/month`,
          regions: (x.prices || []).map((p) => p.location) }))
        .sort((a, b) => a.price - b.price);
      const regions = l.locations.map((x) => ({ id: x.name, label: `${x.city}, ${x.country}` }));
      return { sizes, regions };
    },
    async create(token, { name, size, region, userData }) {
      const b = await api("https://api.hetzner.cloud/v1/servers", token, { method: "POST",
        body: JSON.stringify({ name, server_type: size, location: region, image: "ubuntu-24.04", user_data: userData, labels: { app: "myops" } }) });
      return String(b.server.id);
    },
    destroy: (token, id) => api(`https://api.hetzner.cloud/v1/servers/${id}`, token, { method: "DELETE" }),
  },
};

// Tokens and per-server secrets stay on this phone.
const LOCAL = "myops.cloud";
export const local = () => { try { return JSON.parse(localStorage.getItem(LOCAL) || "{}"); } catch { return {}; } };
const saveLocal = (v) => localStorage.setItem(LOCAL, JSON.stringify(v));
export const saveToken = (provider, token) => { const l = local(); (l.tokens ||= {})[provider] = token; saveLocal(l); };

export async function createServer({ provider, token, size, region, tsKey, ai, aiKey }) {
  const cloud = CLOUDS[provider];
  const id = `myops-${rand(6).toLowerCase()}`, secret = rand(40), ocToken = rand(40), webToken = rand(32);
  const { error } = await supabase.from("cloud_servers").insert({ id, name: id, provider, region, size, report_hash: await sha256(secret), status: "creating" });
  if (error) throw new Error(`Couldn't register the server: ${error.message}`);
  const l = local(); (l.servers ||= {})[id] = { ocToken, webToken }; saveLocal(l);
  try {
    const providerId = await cloud.create(token, { name: id, size, region, userData: bootstrapScript({ id, secret, name: id, tsKey, ai, aiKey, ocToken, webToken }) });
    await supabase.from("cloud_servers").update({ provider_id: providerId, status: "booting", detail: "Server created, starting up", updated_at: new Date().toISOString() }).eq("id", id);
  } catch (e) {
    await supabase.from("cloud_servers").delete().eq("id", id);
    throw e;
  }
  return id;
}

export async function listServers() {
  const { data, error } = await supabase.from("cloud_servers").select("*").order("created_at", { ascending: false });
  if (error) throw new Error(error.message);
  return data;
}

export async function destroyServer(row) {
  const token = local().tokens?.[row.provider];
  if (row.provider_id) {
    if (!token) throw new Error(`Add your ${CLOUDS[row.provider].label} token first (Create > token) so the app can delete the server.`);
    try { await CLOUDS[row.provider].destroy(token, row.provider_id); }
    catch (e) { if (!/not.?found|404/i.test(e.message)) throw e; }
  }
  await supabase.from("cloud_servers").delete().eq("id", row.id);
  const l = local(); delete l.servers?.[row.id]; saveLocal(l);
}
