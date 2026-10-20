// The two sign-ins: the MyOps account (email + password or Google) and the AI platform (OpenRouter
// sign-in or an API key). Both are required before the team opens.
import { App } from "@capacitor/app";
import { Browser } from "@capacitor/browser";
import { AUTH_REDIRECT, OPENROUTER_REDIRECT } from "./config.js";
import { decodePairing, listModels, openRouterFinish, openRouterStart, PROVIDERS, provider } from "./providers.js";
import { currentUser, isNative, loadAI, saveAI, supabase } from "./session.js";

const $ = (id) => document.getElementById(id);
const say = (id, text, kind = "") => { const m = $(id); m.textContent = text || ""; m.className = `msg ${kind}`; };
let mode = "in", picked = null, verifier = null;

async function show() {
  const user = await currentUser();
  $("account").hidden = !!user; $("ai").hidden = !user;
  $("s1").className = user ? "done" : "on"; $("s2").className = user ? "on" : "";
  if (user) {
    $("whoText").textContent = `Signed in as ${user.email || user.user_metadata?.full_name || "you"}`;
    if (loadAI() && location.hash !== "#ai") return location.replace("app.html");
    renderProviders();
  }
}

// ---------- step 1: account ----------
function setMode(m) {
  mode = m;
  $("tabIn").className = m === "in" ? "" : "ghost"; $("tabUp").className = m === "up" ? "" : "ghost";
  $("emailBtn").textContent = m === "in" ? "Sign in" : "Create account";
  $("password").autocomplete = m === "in" ? "current-password" : "new-password";
  $("forgotBtn").hidden = m !== "in";
}
$("tabIn").onclick = () => setMode("in");
$("tabUp").onclick = () => setMode("up");
$("emailForm").onsubmit = async (e) => {
  e.preventDefault();
  const email = $("email").value.trim(), password = $("password").value;
  $("emailBtn").disabled = true; say("accountMsg", mode === "in" ? "Signing in…" : "Creating your account…");
  try {
    if (mode === "in") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
      say("accountMsg", ""); await show();
    } else {
      const { data, error } = await supabase.auth.signUp({ email, password });
      if (error) throw error;
      if (data.session) { say("accountMsg", ""); await show(); }
      else { say("accountMsg", "Check your email and tap the confirmation link, then come back and sign in.", "good"); setMode("in"); }
    }
  } catch (err) { say("accountMsg", err.message || String(err), "bad"); }
  finally { $("emailBtn").disabled = false; }
};
$("forgotBtn").onclick = async () => {
  const email = $("email").value.trim();
  if (!email) return say("accountMsg", "Type your email first.", "bad");
  const { error } = await supabase.auth.resetPasswordForEmail(email);
  say("accountMsg", error ? error.message : "Password reset email sent.", error ? "bad" : "good");
};
$("googleBtn").onclick = async () => {
  say("accountMsg", "Opening Google…");
  const { data, error } = await supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo: isNative() ? AUTH_REDIRECT : `${location.origin}${location.pathname}`, skipBrowserRedirect: true } });
  if (error) return say("accountMsg", error.message, "bad");
  if (isNative()) await Browser.open({ url: data.url }); else location.href = data.url;
};

// ---------- step 2: AI ----------
function renderProviders() {
  const box = $("providers");
  box.replaceChildren(...PROVIDERS.map((p) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = p.oauth ? `Sign in with ${p.name}` : p.name;
    if (p.oauth) b.className = "wide";
    if (picked?.id === p.id) b.classList.add("sel");
    b.onclick = () => (p.oauth ? openRouterLogin() : pick(p));
    return b;
  }));
}
function pick(p, key = "") {
  picked = p; renderProviders();
  $("keyForm").hidden = false; $("modelWrap").hidden = true; say("aiMsg", "");
  $("key").value = key; $("key").hidden = $("keyLabel").hidden = !!p.noKey;
  $("keyLabel").textContent = p.tokenLabel ? `${p.name} ${p.tokenLabel}` : `${p.name} API key`;
  $("keyHelp").innerHTML = p.noKey ? "Run Ollama on a computer on the same Wi-Fi and enter its address."
    : p.id === "openclaw" ? "Paste the pairing code from the MyOps OpenClaw setup (run <code>curl -fsSL https://bsvahyfzpfnhkyzgmoow.supabase.co/functions/v1/openclaw-setup | bash</code> on your computer or server), or enter its Gateway address and token."
    : `Get one at <a href="${p.keyUrl}" target="_blank" rel="noopener">${new URL(p.keyUrl).host}</a>, then paste it here.`;
  $("baseWrap").hidden = !p.customBase; $("base").value = p.base;
  if (key) connect();
}
async function connect() {
  const cfg = { provider: picked.id, key: $("key").value.trim(), base: picked.customBase ? $("base").value.trim() : undefined };
  const paired = picked.id === "openclaw" && cfg.key.startsWith("myops-oc:") ? decodePairing(cfg.key) : null;
  if (paired) { cfg.key = paired.token; cfg.base = paired.url; $("base").value = paired.url; }
  if (!picked.noKey && !cfg.key) return say("aiMsg", "Paste your API key first.", "bad");
  $("connectBtn").disabled = true; say("aiMsg", "Checking the key…");
  try {
    const models = await listModels(cfg);
    if (!models.length) throw new Error("This key has no chat models available.");
    $("model").replaceChildren(...models.map((m) => Object.assign(document.createElement("option"), { value: m, textContent: m })));
    $("modelWrap").hidden = false; picked.cfg = cfg;
    say("aiMsg", `Connected to ${picked.name}. Pick the model your team should use.`, "good");
  } catch (err) {
    say("aiMsg", err.code === "bad_key" ? `${picked.name} rejected that key. Check it and try again.` : err.message || String(err), "bad");
  } finally { $("connectBtn").disabled = false; }
}
$("keyForm").onsubmit = (e) => { e.preventDefault(); connect(); };
$("startBtn").onclick = () => {
  saveAI({ ...picked.cfg, model: $("model").value });
  location.replace("app.html");
};
$("signOutBtn").onclick = async () => { await supabase.auth.signOut(); location.hash = ""; show(); };

async function openRouterLogin() {
  const start = await openRouterStart(isNative() ? OPENROUTER_REDIRECT : `${location.origin}${location.pathname}?or=1`);
  verifier = start.verifier; sessionStorage.setItem("myops.or", verifier);
  say("aiMsg", "Opening OpenRouter…");
  if (isNative()) await Browser.open({ url: start.url }); else location.href = start.url;
}
async function finishOpenRouter(code) {
  say("aiMsg", "Finishing OpenRouter sign-in…");
  try {
    const key = await openRouterFinish(code, verifier || sessionStorage.getItem("myops.or"));
    pick(provider("openrouter"), key);
  } catch (err) { say("aiMsg", err.message || String(err), "bad"); }
}

// ---------- coming back from the system browser ----------
async function handleReturn(url) {
  const u = new URL(url.replace(/^com\.myops\.app:\/\//, "https://x/"));
  const code = u.searchParams.get("code");
  if (!code) return;
  if (isNative()) Browser.close().catch(() => {});
  if (u.pathname.includes("openrouter") || u.host === "openrouter" || u.searchParams.get("or") === "1") return finishOpenRouter(code);
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) say("accountMsg", error.message, "bad");
  await show();
}
if (isNative()) App.addListener("appUrlOpen", ({ url }) => handleReturn(url));
else if (new URLSearchParams(location.search).get("code")) {
  // Back from Google or OpenRouter in the browser: finish, then clean the address bar.
  const back = location.href;
  history.replaceState(null, "", location.pathname + location.hash);
  handleReturn(back);
}

setMode("in");
show();
