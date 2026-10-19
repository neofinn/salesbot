// Runs the MyOps page on a phone: provides the window.claude runtime the page expects, backed by the
// owner's own AI login (sample), an on-phone database synced to their MyOps account (db), the signed-in
// person (user) and the phone's share sheet (downloads). Loaded before the page's own script.
import { Directory, Filesystem } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";
import { AIError, complete, provider } from "./providers.js";
import { clearAI, currentUser, isNative, loadAI, supabase } from "./session.js";

const ready = (async () => {
  const user = await currentUser(), ai = loadAI();
  if (!user || !ai) {
    location.replace("index.html");
    await new Promise(() => {}); // never resolves: the page is leaving
  }
  return { user, ai };
})();

// ---------- sample: the AI the whole team runs on ----------
const parseJson = (text) => {
  const t = String(text || "").trim();
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/);
  const starts = ["{", "["].map((c) => t.indexOf(c)).filter((i) => i >= 0);
  const body = fence ? fence[1] : t.slice(Math.min(...starts), Math.max(t.lastIndexOf("}"), t.lastIndexOf("]")) + 1);
  return JSON.parse(body);
};
function makeSample(ai) {
  const sample = async (input, opts = {}) => {
    const text = await complete(ai, input, { signal: opts.signal });
    opts.onText?.({ text, delta: text });
    return { text, truncated: false, modelApplied: ai.model };
  };
  sample.json = async (input, opts = {}) => {
    const suffix = "\n\nReply with ONLY the JSON value: no prose, no markdown fences.";
    const ask = typeof input === "string" ? input + suffix
      : input.map((m, i) => (i === input.length - 1 ? { ...m, content: m.content + suffix } : m));
    const { text } = await sample(ask, opts);
    try { return parseJson(text); } catch { throw new AIError("invalid_json", "The reply was not JSON.", text); }
  };
  sample.limits = async () => ({ tools: false, images: false });
  return sample;
}

// ---------- db: on-phone storage, synced to the owner's MyOps account ----------
// Shape: { [collection]: { [docId]: { d: data, t: updatedMs, x: deleted } } }
class PhoneDB {
  constructor(uid) {
    this.uid = uid; this.key = `myops.db.${uid}`; this.subs = new Map(); this.pending = new Map();
    try { this.cols = JSON.parse(localStorage.getItem(this.key) || "{}"); } catch { this.cols = {}; }
  }
  collection(c) { return new Query(this, c); }
  rows(c) { return Object.entries(this.cols[c] || {}).filter(([, r]) => !r.x).map(([id, r]) => ({ id, d: r.d })); }
  emit(c) { for (const q of this.subs.get(c) || []) q.fire(); }
  persist() {
    clearTimeout(this.pt);
    this.pt = setTimeout(() => { try { localStorage.setItem(this.key, JSON.stringify(this.cols)); } catch (e) { console.warn("storage full", e); } }, 250);
  }
  write(c, id, d, deleted = false) {
    (this.cols[c] ||= {})[id] = { d: deleted ? null : d, t: Date.now(), ...(deleted ? { x: 1 } : {}) };
    this.persist(); this.emit(c);
    this.pending.set(`${c}\u0000${id}`, [c, id]);
    clearTimeout(this.ft); this.ft = setTimeout(() => this.flush(), 1500);
  }
  async flush() {
    const items = [...this.pending.values()]; this.pending.clear();
    for (let i = 0; i < items.length; i += 200) {
      const rows = items.slice(i, i + 200).map(([c, id]) => {
        const r = this.cols[c]?.[id];
        return { user_id: this.uid, collection: c, doc_id: id, data: r?.d ?? {}, deleted: !!r?.x, updated_at: new Date(r?.t || Date.now()).toISOString() };
      });
      const { error } = await supabase.from("user_docs").upsert(rows, { onConflict: "user_id,collection,doc_id" });
      if (error) { items.slice(i, i + 200).forEach(([c, id]) => this.pending.set(`${c}\u0000${id}`, [c, id])); console.warn("sync failed", error.message); return; }
    }
  }
  // Pull the account's copy and merge (newest write wins), then push anything only this phone has.
  async sync() {
    const remote = new Map();
    for (let from = 0; ; from += 1000) {
      const { data, error } = await supabase.from("user_docs").select("collection,doc_id,data,deleted,updated_at").range(from, from + 999);
      if (error) { console.warn("sync pull failed", error.message); return; }
      for (const r of data) remote.set(`${r.collection}\u0000${r.doc_id}`, r);
      if (data.length < 1000) break;
    }
    const touched = new Set();
    for (const r of remote.values()) {
      const t = Date.parse(r.updated_at), local = this.cols[r.collection]?.[r.doc_id];
      if (!local || local.t < t) { (this.cols[r.collection] ||= {})[r.doc_id] = { d: r.deleted ? null : r.data, t, ...(r.deleted ? { x: 1 } : {}) }; touched.add(r.collection); }
    }
    for (const [c, docs] of Object.entries(this.cols)) for (const [id, r] of Object.entries(docs)) {
      const rr = remote.get(`${c}\u0000${id}`);
      if (!rr || Date.parse(rr.updated_at) < r.t) this.pending.set(`${c}\u0000${id}`, [c, id]);
    }
    if (touched.size) { this.persist(); touched.forEach((c) => this.emit(c)); }
    if (this.pending.size) await this.flush();
  }
}
class Query {
  constructor(db, c, order = null, max = 0) { this.db = db; this.c = c; this.order = order; this.max = max; }
  orderBy(field, dir = "asc") { return new Query(this.db, this.c, { field, dir }, this.max); }
  limit(n) { return new Query(this.db, this.c, this.order, n); }
  snapshot() {
    let rows = this.db.rows(this.c);
    if (this.order) {
      const { field, dir } = this.order, s = dir === "desc" ? -1 : 1;
      rows.sort((a, b) => ((a.d?.[field] ?? 0) > (b.d?.[field] ?? 0) ? s : (a.d?.[field] ?? 0) < (b.d?.[field] ?? 0) ? -s : 0));
    }
    if (this.max) rows = rows.slice(0, this.max);
    return { docs: rows.map((r) => ({ id: r.id, data: () => r.d })), size: rows.length };
  }
  onSnapshot(fn) {
    const sub = { fire: () => fn(this.snapshot()) };
    if (!this.db.subs.has(this.c)) this.db.subs.set(this.c, new Set());
    this.db.subs.get(this.c).add(sub);
    queueMicrotask(sub.fire);
    return () => this.db.subs.get(this.c)?.delete(sub);
  }
  async get() { return this.snapshot(); }
  doc(id) {
    const db = this.db, c = this.c;
    return {
      set: async (d) => db.write(c, id, structuredClone(d)),
      update: async (d) => db.write(c, id, { ...(db.cols[c]?.[id]?.x ? {} : db.cols[c]?.[id]?.d || {}), ...structuredClone(d) }),
      delete: async () => db.write(c, id, null, true),
      get: async () => { const r = db.cols[c]?.[id]; return { id, exists: !!r && !r.x, data: () => (r && !r.x ? r.d : undefined) }; },
    };
  }
}

// ---------- downloads: hand the file to the phone's share sheet ----------
async function toBase64(data) {
  const blob = data instanceof Blob ? data : new Blob([data]);
  const buf = new Uint8Array(await blob.arrayBuffer());
  let s = ""; for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return btoa(s);
}
const downloads = {
  async save({ filename, data }) {
    if (!filename || data == null) throw { code: "bad_request", message: "filename and data are required" };
    if (isNative()) {
      const { uri } = await Filesystem.writeFile({ path: filename, data: await toBase64(data), directory: Directory.Cache });
      try { await Share.share({ title: filename, url: uri, dialogTitle: `Save ${filename}` }); }
      catch (e) { if (/cancel/i.test(String(e?.message))) throw { code: "declined", message: "Not saved" }; throw e; }
      return { status: "saved" };
    }
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(data instanceof Blob ? data : new Blob([data])), download: filename });
    document.body.append(a); a.click(); a.remove();
    return { status: "saved" };
  },
};

// ---------- the runtime the page asks for ----------
let dbInstance = null;
const caps = {
  async sample() { const { ai } = await ready; return makeSample(ai); },
  async db() {
    const { user } = await ready;
    if (!dbInstance) {
      dbInstance = new PhoneDB(user.id);
      dbInstance.sync().catch(() => {});
      document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") dbInstance.sync().catch(() => {}); });
    }
    return dbInstance;
  },
  async user() {
    const { user } = await ready;
    return { isOwner: () => true, canEdit: () => true, can: async () => true, id: async () => user.id,
      me: async () => ({ id: user.id, name: user.user_metadata?.full_name || user.email || "" }), profiles: async () => ({}) };
  },
  async downloads() { await ready; return downloads; },
  async mcp() { return null; }, // Clay and Airtable connectors live in claude.ai, not on the phone
};
window.claude = Object.freeze({ use: (name) => (caps[name] ? caps[name]() : Promise.resolve(null)) });

// ---------- account button: who is signed in, which AI, sign out ----------
function accountPanel({ user, ai }) {
  const p = provider(ai.provider);
  const btn = Object.assign(document.createElement("button"), { textContent: "Account", className: "myops-account-btn" });
  const panel = document.createElement("div");
  panel.className = "myops-account-panel"; panel.hidden = true;
  panel.innerHTML = `<strong>Signed in</strong><div class="row"></div><strong>AI</strong><div class="row ai"></div>
    <button data-a="ai">Change AI</button><button data-a="out">Sign out</button><button data-a="close">Close</button>`;
  panel.querySelector(".row").textContent = user.email || user.user_metadata?.full_name || user.id;
  panel.querySelector(".ai").textContent = `${p?.name || ai.provider} · ${ai.model}`;
  panel.addEventListener("click", async (e) => {
    const a = e.target.dataset?.a;
    if (a === "close") panel.hidden = true;
    if (a === "ai") { clearAI(); location.replace("index.html#ai"); }
    if (a === "out") { await dbInstance?.flush().catch(() => {}); await supabase.auth.signOut(); clearAI(); location.replace("index.html"); }
  });
  btn.onclick = () => { panel.hidden = !panel.hidden; };
  const style = document.createElement("style");
  style.textContent = `.myops-account-btn{position:fixed;right:10px;top:calc(10px + env(safe-area-inset-top));z-index:50;font:600 12px system-ui;padding:6px 10px;border-radius:999px;border:1px solid #c9c2b4;background:#fff;color:#18212b}
  .myops-account-btn.inline{position:static;margin-left:6px;flex:0 0 auto}.myops-account-panel[hidden]{display:none}.myops-account-panel{position:fixed;right:10px;top:calc(46px + env(safe-area-inset-top));z-index:50;width:260px;background:#fff;color:#18212b;border:1px solid #c9c2b4;border-radius:12px;padding:12px;font:13px system-ui;box-shadow:0 8px 30px #0003;display:flex;flex-direction:column;gap:6px}
  .myops-account-panel .row{color:#5b6470;overflow-wrap:anywhere}.myops-account-panel button{font:600 13px system-ui;padding:8px;border-radius:8px;border:1px solid #c9c2b4;background:#f4f1ea;color:#18212b}`;
  document.head.append(style);
  // In the page header next to the profile picker when there is one, else floating.
  const sel = document.getElementById("spaceSel");
  if (sel) { btn.classList.add("inline"); sel.after(btn); } else document.body.append(btn);
  document.body.append(panel);
}
ready.then((s) => (document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", () => accountPanel(s)) : accountPanel(s)));
