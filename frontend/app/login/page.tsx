"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Network,
  Lock,
  Mail,
  User,
  Eye,
  EyeOff,
  ArrowRight,
  ArrowLeft,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  Shield,
  KeyRound,
  ShieldCheck,
} from "lucide-react";
import * as api from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function AuthPage() {
  const router = useRouter();
  const { signInWithGoogle, setAppUser, appUser, authError, clearAuthError, loading: authValidating } = useAuth();

  // Auto-redirect only after validation is complete (not on cached profile)
  useEffect(() => {
    if (!authValidating && appUser) {
      router.replace("/dashboard");
    }
  }, [appUser, authValidating, router]);

  // Surface backend token-exchange failures (e.g. Supabase API errors) on the form.
  useEffect(() => {
    if (authError) {
      setErr(authError);
    }
  }, [authError]);

  const [mode, setMode] = useState<"login" | "signup">("login");
  const [step, setStep] = useState<"form" | "otp">("form");

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");
  const [devOtp, setDevOtp] = useState<string | null>(null);

  const getPasswordStrength = (pwd: string) => {
    if (!pwd) return { label: "", color: '#9CA3AF', pct: 0 };
    if (pwd.length < 6) return { label: "Weak (min 6 chars)", color: '#B91C1C', pct: 33 };
    if (pwd.length >= 8 && /[A-Z]/.test(pwd) && /[0-9!@#$%^&*]/.test(pwd)) {
      return { label: "Strong password", color: '#163526', pct: 100 };
    }
    return { label: "Medium strength", color: '#D97706', pct: 66 };
  };

  const strength = getPasswordStrength(password);

  /** Real Supabase Google OAuth — redirects to Google sign-in */
  async function handleGoogleSignIn() {
    setErr("");
    clearAuthError();
    setLoading(true);
    try {
      await signInWithGoogle();
      // signInWithOAuth resolves once the popup/redirect is launched; the
      // exchange completes via onAuthStateChange (SIGNED_IN). Reset the
      // spinner so a blocked/cancelled popup doesn't leave the button stuck.
      setTimeout(() => setLoading(false), 3000);
    } catch (e: unknown) {
      const msg = (e as Error).message || "";
      if (!msg.includes("popup-closed") && !msg.includes("cancelled")) {
        setErr(msg || "Google sign-in failed. Please check your Supabase configuration.");
      }
      setLoading(false);
    }
  }

  async function handleSendOtp() {
    if (!email.trim() || !fullName.trim() || !password) {
      setErr("Please fill in all required fields.");
      return;
    }
    if (!email.includes("@")) {
      setErr("Please provide a valid email address.");
      return;
    }
    if (password.length < 6) {
      setErr("Password must be at least 6 characters long.");
      return;
    }
    if (password !== confirmPassword) {
      setErr("Passwords do not match.");
      return;
    }

    setLoading(true);
    setErr("");
    setSuccess("");
    try {
      const res = await api.sendOtp(email);
      if (res.dev_otp) {
        setDevOtp(res.dev_otp);
      }
      setStep("otp");
      setSuccess(`Security verification code sent to ${email}.`);
    } catch (e) {
      setErr((e as Error).message || "Failed to send OTP verification email.");
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyOtpAndSignUp(e: React.FormEvent) {
    e.preventDefault();
    if (!otp.trim() || otp.trim().length !== 6) {
      setErr("Please enter the 6-digit OTP code.");
      return;
    }

    setLoading(true);
    setErr("");
    setSuccess("");
    try {
      const res = await api.verifyOtpSignUp(fullName, email, password, otp.trim());
      if (typeof window !== "undefined") {
        localStorage.setItem("graphrag_user_token", res.token);
        localStorage.setItem("graphrag_user_profile", JSON.stringify(res.user));
        const expires = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toUTCString();
        document.cookie = `graphrag_auth=${res.token}; path=/; expires=${expires}; SameSite=Lax`;
      }
      setAppUser(res.user);
      setSuccess(`Account verified & created for ${res.user.full_name}! Redirecting...`);
      setTimeout(() => { router.push("/dashboard"); }, 1000);
    } catch (e) {
      setErr((e as Error).message || "Invalid or expired OTP code.");
    } finally {
      setLoading(false);
    }
  }

  async function handleLoginSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setSuccess("");

    if (!email.trim() || !password) {
      setErr("Please enter your email address and password.");
      return;
    }

    setLoading(true);
    try {
      const res = await api.login(email, password);
      if (typeof window !== "undefined") {
        localStorage.setItem("graphrag_user_token", res.token);
        localStorage.setItem("graphrag_user_profile", JSON.stringify(res.user));
        // Mirror token into cookie so Next.js middleware can read it
        const expires = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toUTCString();
        document.cookie = `graphrag_auth=${res.token}; path=/; expires=${expires}; SameSite=Lax`;
      }
      setAppUser(res.user);
      setSuccess(`Welcome back, ${res.user.full_name}! Redirecting...`);
      setTimeout(() => { router.push("/dashboard"); }, 800);
    } catch (e) {
      setErr((e as Error).message || "Invalid email address or password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col justify-center py-12 px-4 sm:px-6 lg:px-8 antialiased relative" style={{ background: 'var(--bg-page)', color: 'var(--text-primary)' }}>

      {/* Brand Header */}
      <div className="sm:mx-auto sm:w-full sm:max-w-md text-center space-y-3">
        <Link href="/" className="inline-flex items-center gap-2.5 group">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl text-white group-hover:scale-105 transition-transform duration-150" style={{ background: '#163526' }}>
            <Network className="h-5 w-5" />
          </div>
          <span className="text-xl font-bold tracking-tight text-ink" style={{ color: 'var(--text-primary)' }}>
            Neuro-Adaptive GraphRAG
          </span>
        </Link>
        <h2 className="text-xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>
          {mode === "login" ? "Sign in to your account" : step === "otp" ? "Verify Email with OTP" : "Create secure account"}
        </h2>
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          Enterprise Graph Retrieval &amp; Multi-Factor Authentication
        </p>
      </div>

      {/* Main Card */}
      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
        <div className="card px-6 py-8 sm:px-8 space-y-6 bg-white shadow-sm border border-gray-200 rounded-2xl">
          
          {/* Mode Switcher */}
          <div className="flex rounded-xl p-1 gap-1" style={{ background: '#E4E6E0', border: '1px solid #D4D7D1' }}>
            {(['login', 'signup'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => { setMode(m); setStep("form"); setErr(""); setSuccess(""); setDevOtp(null); }}
                className={`flex-1 rounded-lg py-2 text-xs font-semibold transition-all duration-150 ${mode === m ? 'tab-active' : ''}`}
                style={mode !== m ? { color: 'var(--text-muted)' } : {}}
              >
                {m === 'login' ? 'Sign In' : 'Create Account'}
              </button>
            ))}
          </div>

          {/* ── Google Sign-In Button (real Firebase OAuth) ── */}
          {step === "form" && (
            <div className="space-y-3">
              <button
                type="button"
                id="google-signin-btn"
                onClick={handleGoogleSignIn}
                disabled={loading}
                className="w-full flex items-center justify-center gap-3 py-2.5 px-4 rounded-xl border border-gray-300 bg-white text-xs font-semibold text-gray-700 hover:bg-gray-50 shadow-sm transition disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {loading ? (
                  <RefreshCw className="h-4 w-4 animate-spin text-gray-500" />
                ) : (
                  <svg className="h-4 w-4" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
                  </svg>
                )}
                <span>Continue with Google</span>
              </button>

              <div className="relative flex items-center justify-center my-2">
                <div className="border-t border-gray-200 w-full" />
                <span className="bg-white px-2.5 text-[11px] text-gray-400 font-mono uppercase">or email</span>
                <div className="border-t border-gray-200 w-full" />
              </div>
            </div>
          )}

          {/* Alerts */}
          {err && (
            <div className="error-box">
              <AlertCircle className="h-4 w-4 shrink-0 text-red-500" />
              <span>{err}</span>
            </div>
          )}

          {success && (
            <div className="success-box">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-700" />
              <span>{success}</span>
            </div>
          )}

          {devOtp && (
            <div className="rounded-xl p-3 bg-emerald-50 border border-emerald-200 text-xs text-emerald-900 space-y-1">
              <div className="font-bold flex items-center gap-1">
                <ShieldCheck className="h-4 w-4 text-emerald-700" /> Dev OTP Code: <span className="font-mono text-base text-emerald-950 underline">{devOtp}</span>
              </div>
              <p className="text-[11px] text-emerald-700">SMTP credentials not configured. Use this OTP code to complete email verification.</p>
            </div>
          )}

          {/* LOGIN FORM */}
          {mode === "login" && (
            <form className="space-y-4" onSubmit={handleLoginSubmit} autoComplete="off">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                  Email Address
                </label>
                <div className="relative">
                  <input
                    type="email"
                    name="username_email_no_fill"
                    autoComplete="off"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="name@company.com"
                    className="input pl-10"
                  />
                  <Mail className="absolute left-3 top-3 h-4 w-4" style={{ color: 'var(--text-placeholder)' }} />
                </div>
              </div>

              <div>
                <div className="flex justify-between items-center mb-1.5">
                  <label className="block text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-secondary)' }}>
                    Password
                  </label>
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="text-xs font-medium flex items-center gap-1 transition hover:underline"
                    style={{ color: '#104F77' }}
                  >
                    {showPassword ? <><EyeOff className="h-3 w-3" /> Hide</> : <><Eye className="h-3 w-3" /> Show</>}
                  </button>
                </div>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    name="password_no_fill"
                    autoComplete="new-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="input pl-10"
                  />
                  <Lock className="absolute left-3 top-3 h-4 w-4" style={{ color: 'var(--text-placeholder)' }} />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="btn w-full py-2.5 text-sm font-semibold mt-6 flex justify-center items-center gap-2"
                style={{ background: '#163526' }}
              >
                {loading ? (
                  <><RefreshCw className="h-4 w-4 animate-spin text-white" /><span>Signing in...</span></>
                ) : (
                  <><span>Sign In</span><ArrowRight className="h-4 w-4" /></>
                )}
              </button>
            </form>
          )}

          {/* SIGNUP FORM - Step 1: Form */}
          {mode === "signup" && step === "form" && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                  Full Name
                </label>
                <div className="relative">
                  <input
                    type="text"
                    required
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="e.g. Arjun Sharma"
                    className="input pl-10"
                  />
                  <User className="absolute left-3 top-3 h-4 w-4" style={{ color: 'var(--text-placeholder)' }} />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                  Email Address
                </label>
                <div className="relative">
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="name@company.com"
                    className="input pl-10"
                  />
                  <Mail className="absolute left-3 top-3 h-4 w-4" style={{ color: 'var(--text-placeholder)' }} />
                </div>
              </div>

              <div>
                <div className="flex justify-between items-center mb-1.5">
                  <label className="block text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-secondary)' }}>
                    Password
                  </label>
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="text-xs font-medium flex items-center gap-1 transition hover:underline"
                    style={{ color: '#104F77' }}
                  >
                    {showPassword ? <><EyeOff className="h-3 w-3" /> Hide</> : <><Eye className="h-3 w-3" /> Show</>}
                  </button>
                </div>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="input pl-10"
                  />
                  <Lock className="absolute left-3 top-3 h-4 w-4" style={{ color: 'var(--text-placeholder)' }} />
                </div>
                {password && (
                  <div className="mt-2 space-y-1">
                    <div className="h-1.5 w-full rounded-full overflow-hidden" style={{ background: 'var(--bg-subtle)' }}>
                      <div
                        className="h-full transition-all duration-300 rounded-full"
                        style={{ width: `${strength.pct}%`, background: strength.color }}
                      />
                    </div>
                    <span className="text-[11px] font-medium block" style={{ color: 'var(--text-muted)' }}>{strength.label}</span>
                  </div>
                )}
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                  Confirm Password
                </label>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    required
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="••••••••"
                    className="input pl-10"
                  />
                  <Shield className="absolute left-3 top-3 h-4 w-4" style={{ color: 'var(--text-placeholder)' }} />
                </div>
              </div>

              <button
                type="button"
                onClick={handleSendOtp}
                disabled={loading}
                className="btn w-full py-2.5 text-sm font-semibold mt-6 flex justify-center items-center gap-2"
                style={{ background: '#163526' }}
              >
                {loading ? (
                  <><RefreshCw className="h-4 w-4 animate-spin text-white" /><span>Sending Verification Code...</span></>
                ) : (
                  <><span>Send Email OTP &amp; Continue</span><ArrowRight className="h-4 w-4" /></>
                )}
              </button>
            </div>
          )}

          {/* SIGNUP FORM - Step 2: OTP Verification */}
          {mode === "signup" && step === "otp" && (
            <form className="space-y-4" onSubmit={handleVerifyOtpAndSignUp}>
              <div className="text-center space-y-1">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-800 border border-emerald-200">
                  <KeyRound className="h-6 w-6" />
                </div>
                <h3 className="font-bold text-base text-gray-900">Enter Security Code</h3>
                <p className="text-xs text-gray-500">
                  We sent a 6-digit OTP code to <strong className="text-emerald-950">{email}</strong>
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-center mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                  6-Digit Verification OTP
                </label>
                <input
                  type="text"
                  maxLength={6}
                  required
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/[^0-9]/g, ''))}
                  placeholder="1 2 3 4 5 6"
                  className="input text-center text-2xl font-mono tracking-widest py-3"
                  autoFocus
                />
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setStep("form")}
                  className="btn-secondary flex-1 py-2 text-xs font-semibold"
                >
                  Back
                </button>
                <button
                  type="submit"
                  disabled={loading || otp.length !== 6}
                  className="btn flex-2 py-2.5 text-xs font-semibold flex items-center justify-center gap-1.5"
                  style={{ background: '#163526' }}
                >
                  {loading ? (
                    <><RefreshCw className="h-3.5 w-3.5 animate-spin" /><span>Verifying...</span></>
                  ) : (
                    <><span>Verify OTP &amp; Create Account</span><ArrowRight className="h-3.5 w-3.5" /></>
                  )}
                </button>
              </div>

              <div className="text-center pt-2">
                <button
                  type="button"
                  onClick={handleSendOtp}
                  disabled={loading}
                  className="text-xs font-semibold text-emerald-800 hover:underline"
                >
                  Didn&apos;t receive code? Resend OTP
                </button>
              </div>
            </form>
          )}

          <div className="text-center pt-4" style={{ borderTop: '1px solid var(--border)' }}>
            <Link
              href="/"
              className="text-xs font-medium transition inline-flex items-center gap-1 hover:underline"
              style={{ color: 'var(--text-muted)' }}
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Return to Main Application
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
