// Every big AI platform the phone app can run the team on. All calls go straight from the phone to the
// provider with the owner's own login or key (Capacitor's native HTTP, so no browser CORS limits).

export const PROVIDERS = [
  { id: "openrouter", name: "OpenRouter", kind: "openai", base: "https://openrouter.ai/api/v1", oauth: true,
    keyUrl: "https://openrouter.ai/keys", note: "Sign in once for Claude, GPT, Gemini, Grok, Llama, Qwen and more." },
  { id: "anthropic", name: "Anthropic Claude", kind: "anthropic", base: "https://api.anthropic.com/v1",
    keyUrl: "https://console.anthropic.com/settings/keys", prefer: ["sonnet", "opus", "haiku"] },
  { id: "openai", name: "OpenAI (GPT)", kind: "openai", base: "https://api.openai.com/v1",
    keyUrl: "https://platform.openai.com/api-keys", prefer: ["gpt-5", "gpt-4.1", "gpt-4o", "o4"], skip: /embedding|tts|whisper|dall-e|image|audio|realtime|transcribe|moderation|search/ },
  { id: "gemini", name: "Google Gemini", kind: "gemini", base: "https://generativelanguage.googleapis.com/v1beta",
    keyUrl: "https://aistudio.google.com/apikey", prefer: ["pro", "flash"], skip: /embedding|aqa|imagen|tts|image|vision-only/ },
  { id: "xai", name: "xAI Grok", kind: "openai", base: "https://api.x.ai/v1", keyUrl: "https://console.x.ai", prefer: ["grok-4", "grok-3"], skip: /image|vision-only/ },
  { id: "deepseek", name: "DeepSeek", kind: "openai", base: "https://api.deepseek.com/v1", keyUrl: "https://platform.deepseek.com/api_keys", prefer: ["chat", "reasoner"] },
  { id: "mistral", name: "Mistral", kind: "openai", base: "https://api.mistral.ai/v1", keyUrl: "https://console.mistral.ai/api-keys", prefer: ["large", "medium"], skip: /embed|moderation|ocr/ },
  { id: "groq", name: "Groq", kind: "openai", base: "https://api.groq.com/openai/v1", keyUrl: "https://console.groq.com/keys", prefer: ["llama-3.3-70b", "70b"], skip: /whisper|guard|tts/ },
  { id: "qwen", name: "Alibaba Qwen", kind: "openai", base: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    keyUrl: "https://bailian.console.alibabacloud.com/?apiKey=1", models: ["qwen-max", "qwen-plus", "qwen-turbo"] },
  { id: "perplexity", name: "Perplexity", kind: "openai", base: "https://api.perplexity.ai", keyUrl: "https://www.perplexity.ai/settings/api", models: ["sonar-pro", "sonar"] },
  { id: "together", name: "Together AI", kind: "openai", base: "https://api.together.xyz/v1", keyUrl: "https://api.together.ai/settings/api-keys", prefer: ["Llama-3.3-70B", "Qwen"], skip: /embed|image|flux|whisper/ },
  { id: "cohere", name: "Cohere", kind: "openai", base: "https://api.cohere.ai/compatibility/v1", keyUrl: "https://dashboard.cohere.com/api-keys", models: ["command-a-03-2025", "command-r-plus"] },
  { id: "openclaw", name: "OpenClaw (Clawdbot)", kind: "openai", base: "http://192.168.1.10:18789/v1", customBase: true, models: ["openclaw:main"],
    tokenLabel: "Gateway token", note: "Your own OpenClaw agent runs the team (it can browse the web)." },
  { id: "ollama", name: "Ollama (your own computer)", kind: "openai", base: "http://192.168.1.10:11434/v1", noKey: true, customBase: true, prefer: ["qwen", "llama"] },
];

export const provider = (id) => PROVIDERS.find((p) => p.id === id);

export class AIError extends Error {
  constructor(code, message, text) { super(message); this.code = code; if (text) this.text = text; }
}

const headers = (p, key) => {
  if (p.kind === "anthropic") return { "x-api-key": key, "anthropic-version": "2023-06-01", "anthropic-dangerous-direct-browser-access": "true", "content-type": "application/json" };
  const h = { "content-type": "application/json" };
  if (key) h.authorization = `Bearer ${key}`;
  if (p.id === "openrouter") Object.assign(h, { "HTTP-Referer": "https://myops.app", "X-Title": "MyOps" });
  return h;
};

async function call(url, init, signal) {
  let res;
  try { res = await fetch(url, { ...init, signal }); }
  catch (e) {
    if (signal?.aborted || e?.name === "AbortError") throw new AIError("cancelled", "Stopped.");
    throw new AIError("network", `Couldn't reach the AI service (${e?.message || "network error"}). Check your connection.`);
  }
  const body = await res.text();
  if (!res.ok) {
    let msg = body.slice(0, 300);
    try { const j = JSON.parse(body); msg = j.error?.message || j.message || j.error || msg; } catch { /* plain text */ }
    const code = res.status === 401 || res.status === 403 ? "bad_key" : res.status === 429 ? "rate_limited"
      : res.status === 413 || /context|too long|maximum.*tokens/i.test(String(msg)) ? "prompt_too_large" : "upstream_error";
    throw new AIError(code, `${res.status}: ${String(msg).slice(0, 300)}`);
  }
  try { return JSON.parse(body); } catch { throw new AIError("upstream_error", "The AI service sent an unreadable reply."); }
}

/** Model ids the key can use, best-first; also proves the key works. */
export async function listModels(cfg, signal) {
  const p = provider(cfg.provider), base = (cfg.base || p.base).replace(/\/$/, "");
  if (p.models) {
    // These platforms have no reliable model list: a tiny call checks the key instead.
    await complete({ ...cfg, model: p.models[0] }, "Reply with OK.", { signal, maxTokens: 5 });
    return p.models;
  }
  let ids;
  if (p.kind === "gemini") {
    const j = await call(`${base}/models?key=${encodeURIComponent(cfg.key)}&pageSize=200`, { headers: { "content-type": "application/json" } }, signal);
    ids = (j.models || []).filter((m) => (m.supportedGenerationMethods || []).includes("generateContent")).map((m) => m.name.replace(/^models\//, ""));
  } else {
    const j = await call(`${base}/models`, { headers: headers(p, cfg.key) }, signal);
    ids = (j.data || j.models || []).map((m) => m.id || m.name).filter(Boolean);
  }
  if (p.skip) ids = ids.filter((id) => !p.skip.test(id));
  const rank = (id) => { const i = (p.prefer || []).findIndex((s) => id.toLowerCase().includes(s.toLowerCase())); return i < 0 ? 99 : i; };
  // Keep the provider's own order (usually newest first) within each preference group.
  return ids.map((id, i) => ({ id, i })).sort((a, b) => rank(a.id) - rank(b.id) || a.i - b.i).map((x) => x.id);
}

const asMessages = (input) => (typeof input === "string" ? [{ role: "user", content: input }]
  : input.map((m) => ({ role: m.role === "assistant" ? "assistant" : "user", content: String(m.content) })));

/** One completion: returns the reply text. */
export async function complete(cfg, input, { signal, maxTokens = 8192 } = {}) {
  const p = provider(cfg.provider), base = (cfg.base || p.base).replace(/\/$/, ""), messages = asMessages(input);
  if (p.kind === "anthropic") {
    const j = await call(`${base}/messages`, { method: "POST", headers: headers(p, cfg.key),
      body: JSON.stringify({ model: cfg.model, max_tokens: maxTokens, messages }) }, signal);
    return (j.content || []).filter((c) => c.type === "text").map((c) => c.text).join("");
  }
  if (p.kind === "gemini") {
    const j = await call(`${base}/models/${encodeURIComponent(cfg.model)}:generateContent?key=${encodeURIComponent(cfg.key)}`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ contents: messages.map((m) => ({ role: m.role === "assistant" ? "model" : "user", parts: [{ text: m.content }] })),
        generationConfig: { maxOutputTokens: maxTokens } }) }, signal);
    const cand = j.candidates?.[0];
    if (!cand) throw new AIError("refused", j.promptFeedback?.blockReason ? `Blocked: ${j.promptFeedback.blockReason}` : "No answer.");
    return (cand.content?.parts || []).map((x) => x.text || "").join("");
  }
  const j = await call(`${base}/chat/completions`, { method: "POST", headers: headers(p, cfg.key),
    body: JSON.stringify({ model: cfg.model, messages, max_tokens: maxTokens }) }, signal);
  return j.choices?.[0]?.message?.content ?? "";
}

// OpenRouter's app sign-in (OAuth with PKCE): the owner logs in on openrouter.ai and the app receives a key.
export async function openRouterStart(redirect) {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  const verifier = btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const challenge = btoa(String.fromCharCode(...digest)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const url = `https://openrouter.ai/auth?callback_url=${encodeURIComponent(redirect)}&code_challenge=${challenge}&code_challenge_method=S256`;
  return { url, verifier };
}
export async function openRouterFinish(code, verifier) {
  const j = await call("https://openrouter.ai/api/v1/auth/keys", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ code, code_verifier: verifier, code_challenge_method: "S256" }) });
  if (!j.key) throw new AIError("bad_key", "OpenRouter didn't return a key.");
  return j.key;
}
