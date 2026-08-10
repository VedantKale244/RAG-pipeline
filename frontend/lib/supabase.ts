import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { getSupabaseConfig } from "./api";

let supabaseInstance: SupabaseClient | null = null;
let initPromise: Promise<SupabaseClient | null> | null = null;

function sanitizeSupabaseUrl(rawUrl: string): string {
  let url = rawUrl.trim();
  if (url.endsWith("/rest/v1/") || url.endsWith("/rest/v1")) {
    url = url.split("/rest/v1")[0];
  }
  return url.replace(/\/+$/, "");
}

async function initSupabaseClient(): Promise<SupabaseClient | null> {
  let url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  let anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

  // Attempt fetching from backend config if missing or empty in browser env
  if (!url.trim() || !anonKey.trim()) {
    try {
      const config = await getSupabaseConfig();
      url = url || config.supabaseUrl || "";
      anonKey = anonKey || config.supabaseAnonKey || "";
    } catch (e) {
      console.warn("Could not fetch Supabase configuration from backend:", e);
    }
  }

  url = sanitizeSupabaseUrl(url);
  anonKey = anonKey.trim();

  if (!url || !anonKey) {
    console.warn("Supabase credentials missing. Please set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in backend .env");
    return null;
  }

  supabaseInstance = createClient(url, anonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });
  return supabaseInstance;
}

export async function getSupabaseClient(): Promise<SupabaseClient | null> {
  if (!supabaseInstance) {
    if (!initPromise) {
      initPromise = initSupabaseClient();
    }
    supabaseInstance = await initPromise;
    if (!supabaseInstance) {
      initPromise = null;
    }
  }
  return supabaseInstance;
}
