"use client";

/**
 * AuthContext — provides Supabase Google Authentication state across the entire app.
 *
 * Flow for Google Sign-In:
 *   1. Supabase Google OAuth → redirect / session
 *   2. POST /auth/supabase { access_token, email, full_name } → backend session token + user profile
 *   3. Persist session token in localStorage + cookie (same as existing flow)
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import type { User as SupabaseUser } from "@supabase/supabase-js";
import { getSupabaseClient } from "./supabase";
import * as api from "./api";

// ─── Cookie helpers (mirrors token into a cookie for Edge middleware) ──────────

function setAuthCookie(token: string) {
  if (typeof document === "undefined") return;
  const expires = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toUTCString();
  document.cookie = `graphrag_auth=${token}; path=/; expires=${expires}; SameSite=Lax`;
}

function clearAuthCookie() {
  if (typeof document === "undefined") return;
  document.cookie = "graphrag_auth=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax";
}

// ─── Types ────────────────────────────────────────────────────────────────────

export interface AuthContextValue {
  supabaseUser: SupabaseUser | null;
  appUser: api.UserProfile | null;
  loading: boolean;
  authError: string | null;
  clearAuthError: () => void;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  setAppUser: (user: api.UserProfile | null) => void;
}

// ─── Context ──────────────────────────────────────────────────────────────────

export const AuthContext = createContext<AuthContextValue>({
  supabaseUser: null,
  appUser: null,
  loading: true,
  authError: null,
  clearAuthError: () => {},
  signInWithGoogle: async () => {},
  signOut: async () => {},
  setAppUser: () => {},
});

// ─── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [supabaseUser, setSupabaseUser] = useState<SupabaseUser | null>(null);
  const [appUser, setAppUser] = useState<api.UserProfile | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [authError, setAuthError] = useState<string | null>(null);

  // ── On mount: validate existing backend session token ───────────────────────
  useEffect(() => {
    const token = typeof window !== "undefined"
      ? localStorage.getItem("graphrag_user_token")
      : null;

    if (token) {
      // Don't restore from cache — let getMe validate before setting appUser.
      // This prevents auto-login on reload for stale sessions.
      api
        .getMe(token)
        .then((u) => {
          setAppUser(u);
          localStorage.setItem("graphrag_user_profile", JSON.stringify(u));
          setAuthCookie(token);
        })
        .catch(() => {
          localStorage.removeItem("graphrag_user_token");
          localStorage.removeItem("graphrag_user_profile");
          clearAuthCookie();
          setAppUser(null);
          api.resetGuestSession();
        })
        .finally(() => {
          setLoading(false);
        });
    } else {
      api.resetGuestSession();
      setLoading(false);
    }
  }, []);

  // ── Supabase auth state listener ─────────────────────────────────────────────
  useEffect(() => {
    let unsubscribe: (() => void) | null = null;

    getSupabaseClient()
      .then((supabase) => {
        if (!supabase) {
          setLoading(false);
          return;
        }

        // Initial session check
        supabase.auth.getSession().then(({ data: { session } }) => {
          if (session?.user) {
            setSupabaseUser(session.user);
            exchangeSupabaseToken(session.access_token, session.user.email, session.user.user_metadata?.full_name || session.user.user_metadata?.name);
          }
          setLoading(false);
        });

        // Listen for auth state changes — only exchange on explicit sign-in, not on page load
        const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, session) => {
          if (event === "SIGNED_IN" && session?.user) {
            setSupabaseUser(session.user);
            await exchangeSupabaseToken(session.access_token, session.user.email, session.user.user_metadata?.full_name || session.user.user_metadata?.name);
          } else if (event === "SIGNED_OUT") {
            setSupabaseUser(null);
          }
          setLoading(false);
        });

        unsubscribe = () => subscription.unsubscribe();
      })
      .catch((err) => {
        console.warn("Supabase Auth initialization deferred (pending credentials):", err);
        setLoading(false);
      });

    return () => {
      if (unsubscribe) unsubscribe();
    };
  }, []);

  /** Exchange a Supabase access token for a backend session token. */
  async function exchangeSupabaseToken(accessToken: string, email?: string, fullName?: string) {
    try {
      const res = await api.supabaseGoogleAuth(accessToken, email, fullName);
      localStorage.setItem("graphrag_user_token", res.token);
      localStorage.setItem("graphrag_user_profile", JSON.stringify(res.user));
      setAuthCookie(res.token);
      setAppUser(res.user);
      setAuthError(null);
    } catch (err) {
      const msg = (err as Error).message || "Google sign-in failed. Please try again.";
      console.error("Supabase token exchange failed:", msg);
      setAuthError(msg);
      // Do not leave stale session artifacts behind a failed exchange.
      localStorage.removeItem("graphrag_user_token");
      localStorage.removeItem("graphrag_user_profile");
      clearAuthCookie();
      setAppUser(null);
    }
  }

  // ── Actions ──────────────────────────────────────────────────────────────────

  const signInWithGoogle = useCallback(async () => {
    setAuthError(null);
    const supabase = await getSupabaseClient();
    if (!supabase) {
      throw new Error("Supabase credentials missing. Please set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in your backend .env file.");
    }
    const redirectTo = typeof window !== "undefined" ? `${window.location.origin}/login` : undefined;
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo,
        queryParams: {
          access_type: "offline",
          prompt: "consent",
        },
      },
    });
    if (error) {
      throw error;
    }
  }, []);

  const signOut = useCallback(async () => {
    const token = typeof window !== "undefined"
      ? localStorage.getItem("graphrag_user_token")
      : null;
    if (token) {
      api.logout(token).catch(() => { /* ignore */ });
    }

    localStorage.removeItem("graphrag_user_token");
    localStorage.removeItem("graphrag_user_profile");
    clearAuthCookie();

    try {
      const supabase = await getSupabaseClient();
      if (supabase) {
        await supabase.auth.signOut();
      }
    } catch { /* ignore */ }

    api.resetGuestSession();
    setAppUser(null);
    setSupabaseUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ supabaseUser, appUser, loading, authError, clearAuthError: () => setAuthError(null), signInWithGoogle, signOut, setAppUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}
