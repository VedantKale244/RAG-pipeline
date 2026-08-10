/**
 * useAuth hook — convenience re-export so pages can import from a single location.
 * Usage:  const { appUser, signInWithGoogle, signOut, loading } = useAuth();
 */
export { useAuth } from "../lib/auth-context";
