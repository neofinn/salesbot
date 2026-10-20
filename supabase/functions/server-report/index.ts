// A MyOps cloud server reports its setup progress here. It authenticates with the one-time report
// secret the phone app generated (only its SHA-256 is stored), so it can update its own row and nothing else.
import { createClient } from "jsr:@supabase/supabase-js@2";

const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const STATUSES = new Set(["booting", "installing", "ready", "failed"]);

async function sha256(text: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("POST only", { status: 405 });
  let body: Record<string, unknown>;
  try { body = await req.json(); } catch { return new Response("bad json", { status: 400 }); }
  const id = String(body.id || ""), secret = String(body.secret || ""), status = String(body.status || "");
  if (!/^[a-z0-9-]{4,40}$/.test(id) || secret.length < 20 || !STATUSES.has(status)) return new Response("bad request", { status: 400 });
  const { data: row } = await admin.from("cloud_servers").select("report_hash,status").eq("id", id).maybeSingle();
  if (!row || row.report_hash !== await sha256(secret)) return new Response("unknown server", { status: 403 });
  if (row.status === "ready" && status !== "failed") return new Response(JSON.stringify({ ok: true }), { headers: { "content-type": "application/json" } });
  const url = (v: unknown) => { const s = String(v || ""); return /^https:\/\/[a-z0-9.-]+\.ts\.net(:\d+)?(\/[\w./-]*)?$/i.test(s) ? s : ""; };
  const patch: Record<string, string> = { status, detail: String(body.detail || "").slice(0, 500), updated_at: new Date().toISOString() };
  if (url(body.openclaw_url)) patch.openclaw_url = url(body.openclaw_url);
  if (url(body.myops_url)) patch.myops_url = url(body.myops_url);
  const { error } = await admin.from("cloud_servers").update(patch).eq("id", id);
  if (error) return new Response("update failed", { status: 500 });
  return new Response(JSON.stringify({ ok: true }), { headers: { "content-type": "application/json" } });
});
