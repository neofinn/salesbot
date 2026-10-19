// The MyOps account service (Supabase). The publishable key is meant to ship inside apps:
// row-level security limits every signed-in person to their own data.
export const SUPABASE_URL = "https://bsvahyfzpfnhkyzgmoow.supabase.co";
export const SUPABASE_KEY = "sb_publishable_FyJ8v9FcKGzjcxfIYCP6uQ_QMUqZ5p6";
// Deep links back into the app after Google or OpenRouter sign-in in the system browser.
export const SCHEME = "com.myops.app";
export const AUTH_REDIRECT = `${SCHEME}://auth`;
export const OPENROUTER_REDIRECT = `${SCHEME}://openrouter`;
