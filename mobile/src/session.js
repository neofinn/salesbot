// Shared by the sign-in page and the app: the MyOps account (Supabase Auth) and the AI connection.
import { createClient } from "@supabase/supabase-js";
import { SUPABASE_KEY, SUPABASE_URL } from "./config.js";

export const supabase = createClient(SUPABASE_URL, SUPABASE_KEY, {
  auth: { flowType: "pkce", persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
});

// The AI login stays on this phone only (app-private storage); it is never uploaded.
const AI_KEY = "myops.ai";
export const loadAI = () => { try { return JSON.parse(localStorage.getItem(AI_KEY) || "null"); } catch { return null; } };
export const saveAI = (cfg) => localStorage.setItem(AI_KEY, JSON.stringify(cfg));
export const clearAI = () => localStorage.removeItem(AI_KEY);

export async function currentUser() {
  const { data } = await supabase.auth.getSession();
  return data.session?.user || null;
}

export const isNative = () => !!window.Capacitor?.isNativePlatform?.();
