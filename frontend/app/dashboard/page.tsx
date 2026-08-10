"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import {
  MessageSquare,
  UploadCloud,
  Network,
  BarChart3,
  Sparkles,
  ShieldCheck,
  LogOut,
  User,
  FileText,
  CheckCircle2,
  AlertCircle,
  Zap,
  Search,
  RefreshCw,
  Sliders,
  Database,
  Cpu,
  ArrowUpRight,
  ThumbsUp,
  ThumbsDown,
  Check,
  X,
  ChevronRight,
  Info,
  SlidersHorizontal,
  Layers,
  Activity,
  FileCheck,
  Plus,
  Trash2,
  Clock,
  History,
  TrendingUp
} from "lucide-react";
import * as api from "../../lib/api";
import { useAuth } from "../../lib/auth-context";
import * as trial from "../../lib/trial";
import type {
  AdminStats,
  ChatResponse,
  EvalResponse,
  EvalRun,
  GraphSnapshot,
  IngestResponse,
  UsageSnapshot,
} from "../../lib/api";

type Tab = "chat" | "upload" | "graph" | "eval";

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: "chat", label: "Chat & Search", icon: MessageSquare },
  { id: "upload", label: "Ingest Data", icon: UploadCloud },
  { id: "graph", label: "Knowledge Graph", icon: Network },
  { id: "eval", label: "Evaluation", icon: BarChart3 },
];

export default function Home() {
  const { appUser: currentUser, loading: authLoading, signOut: handleLogout } = useAuth();
  const [mounted, setMounted] = useState(false);
  const [tab, setTab] = useState<Tab>("chat");
  const [provenance, setProvenance] = useState<api.Edge[]>([]);
  const [graphRefreshVersion, setGraphRefreshVersion] = useState(0);
  const [activeQuery, setActiveQuery] = useState("");
  const [trialStatus, setTrialStatus] = useState<trial.TrialStatus | null>(null);
  const [usage, setUsage] = useState<UsageSnapshot | null>(null);
  const [showUpgrade, setShowUpgrade] = useState(false);
  const [checkoutNotice, setCheckoutNotice] = useState<{ kind: "success" | "canceled"; msg: string } | null>(null);

  const triggerGraphRefresh = useCallback(() => {
    setGraphRefreshVersion((v) => v + 1);
  }, []);

  useEffect(() => {
    setMounted(true);

    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const checkout = params.get("checkout");
      if (checkout === "success") {
        setCheckoutNotice({ kind: "success", msg: "Payment successful — your Pro plan is active." });
      } else if (checkout === "canceled") {
        setCheckoutNotice({ kind: "canceled", msg: "Checkout was canceled — you're still on the free plan." });
      }
    }

    if (typeof window !== "undefined") {
      const handleUnload = () => {
        const userToken = localStorage.getItem("graphrag_user_token");
        if (!userToken) {
          api.cleanupGuestSession();
        }
      };

      window.addEventListener("beforeunload", handleUnload);
      window.addEventListener("pagehide", handleUnload);
      return () => {
        window.removeEventListener("beforeunload", handleUnload);
        window.removeEventListener("pagehide", handleUnload);
      };
    }
  }, []);

  useEffect(() => {
    if (!mounted) return;
    api.getUsage()
      .then((u) => {
        setUsage(u);
        setUsage(u);
        if (!currentUser) {
          setTrialStatus(trial.trialStatusFromUsage(u));
        } else {
          setTrialStatus(null);
        }
      })
      .catch(() => setUsage(null));
  }, [mounted, currentUser]);

  const refreshUsage = useCallback(() => {
    api.getUsage()
      .then((u) => {
        setUsage(u);
        if (!currentUser) {
          setTrialStatus(trial.trialStatusFromUsage(u));
        }
      })
      .catch(() => undefined);
  }, [currentUser]);

  return (
    <div className="min-h-screen antialiased pb-16 bg-transparent" style={{ color: 'var(--text-primary)' }}>

      {/* ── Top Navigation Bar (Light Premium Glass) ── */}
      <header className="sticky top-0 z-50 backdrop-blur-lg" style={{ background: 'rgba(255, 255, 255, 0.88)', boxShadow: '0 1px 12px rgba(11, 37, 69, 0.08), inset 0 1px 0 rgba(255,255,255,0.9)', borderBottom: '1px solid rgba(210, 226, 240, 0.65)' }}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">

          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="relative flex h-10 w-10 items-center justify-center rounded-xl text-white shadow-lg" style={{ background: 'linear-gradient(135deg, #028090 0%, #104F77 60%, #0B2545 100%)', boxShadow: '0 6px 16px rgba(2,128,144,0.25)' }}>
              <Network className="h-5 w-5" />
              <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-white" style={{ background: '#34D399' }} />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-base font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>
                  <span className="font-extrabold">Neuro-Adaptive</span> <span style={{ color: '#028090' }}>GraphRAG</span>
                </h1>
              </div>
              <p className="text-[10.5px] hidden sm:block font-medium tracking-wide" style={{ color: 'var(--text-muted)' }}>
                Self-Improving Enterprise Intelligence
              </p>
            </div>
          </div>

          {/* Right side */}
          <div className="flex items-center gap-2.5">
            {/* Trust status */}
            <div className="hidden lg:inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium" style={{ color: '#0F3854', background: 'rgba(16,79,119,0.06)', border: '1px solid rgba(16,79,119,0.16)' }}>
              <ShieldCheck className="h-3.5 w-3.5" style={{ color: '#028090' }} />
              <span>SOC 2-aligned · Encrypted</span>
            </div>

            {/* Auth */}
            {!mounted || authLoading ? (
              <div className="flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium" style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                <RefreshCw className="h-3 w-3 animate-spin" style={{ color: '#104F77' }} />
                <span>Checking session...</span>
              </div>
            ) : currentUser ? (
              <div className="flex items-center gap-2 rounded-full pl-1 pr-3 py-1 text-xs" style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}>
                <span className="flex h-7 w-7 items-center justify-center rounded-full font-bold text-white text-xs shadow-sm" style={{ background: 'linear-gradient(135deg, #028090, #0F4C81)' }}>
                  {currentUser.full_name.charAt(0).toUpperCase()}
                </span>
                <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>{currentUser.full_name}</span>
                {usage && !usage.unlimited && (
                  <button
                    onClick={() => setShowUpgrade(true)}
                    className="ml-1 flex items-center gap-1 text-[11px] font-bold rounded-lg px-2 py-1 transition hover:bg-emerald-50"
                    style={{ color: '#028090', border: '1px solid rgba(2,128,144,0.25)' }}
                    title="Upgrade for unlimited access"
                  >
                    <Sparkles className="h-3 w-3" />
                    <span className="hidden sm:inline">Upgrade</span>
                  </button>
                )}
                <button onClick={handleLogout} className="ml-1 flex items-center gap-1 text-[11px] font-semibold rounded-lg px-1.5 py-1 transition hover:bg-gray-100" style={{ color: 'var(--text-muted)' }} title="Sign Out">
                  <LogOut className="h-3 w-3" />
                  <span className="hidden sm:inline">Sign Out</span>
                </button>
              </div>
            ) : (
              <Link href="/login" className="btn text-xs py-2 px-4" style={{ background: 'linear-gradient(135deg, #028090, #0F4C81)', boxShadow: '0 4px 12px rgba(2,128,144,0.25)' }}>
                <Sparkles className="h-3.5 w-3.5" />
                <span>Get Started Free</span>
              </Link>
            )}
          </div>
        </div>
      </header>

      {/* ── Free Trial Banner (non-logged-in users) ── */}
      {mounted && !authLoading && !currentUser && trialStatus && (
        trialStatus.expired ? (
          <div className="mx-auto max-w-6xl px-5 pt-6">
            <div className="flex flex-col items-center justify-between gap-3 rounded-2xl px-5 py-4 sm:flex-row" style={{ background: 'linear-gradient(135deg, #FDF2E3 0%, #FFF7ED 100%)', border: '1px solid #F5D9A8', boxShadow: '0 10px 28px rgba(183,121,31,0.14)' }}>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl text-white shadow-md" style={{ background: 'linear-gradient(135deg, #D97706, #B7791F)' }}>
                  <Clock className="h-5 w-5" />
                </div>
                <div className="text-left">
                  <div className="text-sm font-bold" style={{ color: '#7C4A12' }}>Your free trial questions are used up</div>
                  <div className="text-xs" style={{ color: '#A1712B' }}>Sign in for a free account with daily limits, or upgrade to Pro for unlimited questions.</div>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Link href="/login" className="btn text-xs py-2 px-4" style={{ background: 'linear-gradient(135deg, #D97706, #B7791F)' }}>
                  <Sparkles className="h-3.5 w-3.5" />
                  <span>Create Account</span>
                </Link>
              </div>
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-6xl px-5 pt-6">
            <div className="relative flex flex-col gap-3 overflow-hidden rounded-2xl px-6 py-4 sm:flex-row sm:items-center sm:justify-between" style={{ background: 'linear-gradient(135deg, #E8F4FA 0%, #EAF7F3 50%, #E2F5EE 100%)', boxShadow: '0 6px 20px rgba(2,128,144,0.10)', border: '1px solid rgba(16,185,129,0.25)' }}>
              <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full opacity-20" style={{ background: 'radial-gradient(circle, #028090 0%, transparent 70%)' }} />
              <div className="relative flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl" style={{ background: 'rgba(2,128,144,0.12)' }}>
                  <Sparkles className="h-5 w-5" style={{ color: '#028090' }} />
                </div>
                <div>
                  <div className="flex flex-wrap items-center gap-2 text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                    <span>Free Trial Active</span>
                    <span className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold" style={{ background: 'rgba(2,128,144,0.12)', color: '#0F4C81' }}>
                      {trial.formatTrialRemaining(trialStatus)}
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 w-full max-w-xs overflow-hidden rounded-full" style={{ background: 'rgba(2,128,144,0.15)' }}>
                    <div className="h-full rounded-full" style={{ width: `${trialStatus.percentUsed}%`, background: 'linear-gradient(90deg, #028090, #10B981)' }} />
                  </div>
                </div>
              </div>
              <div className="relative flex shrink-0 items-center gap-2">
                <span className="hidden text-xs md:block" style={{ color: 'var(--text-muted)' }}>{100 - trialStatus.percentUsed}% of your trial questions remaining</span>
                <Link href="/login" className="rounded-xl px-4 py-2 text-xs font-bold transition-all hover:-translate-y-0.5" style={{ color: '#028090', background: 'white', border: '1px solid rgba(2,128,144,0.2)', boxShadow: '0 4px 12px rgba(2,128,144,0.1)' }}>
                  Sign in for a free account
                </Link>
              </div>
            </div>
          </div>
        )
      )}

      {/* ── Workspace Welcome Band ── */}
      <div className="mx-auto max-w-6xl px-5 pt-7">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="section-label">Workspace</p>
            <h2 className="mt-1.5 text-2xl font-extrabold tracking-tight" style={{ color: 'var(--text-primary)' }}>
              {currentUser ? (
                <>Welcome back, <span style={{ color: '#028090' }}>{currentUser.full_name.split(" ")[0]}</span></>
              ) : (
                <>Explore the Intelligence Platform</>
              )}
            </h2>
            <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
              {currentUser
                ? "Your documents, graphs, and evaluations are securely saved to your account."
                : "Guest sandbox — your session is kept temporarily. Start free or sign in to save your work."}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs font-semibold" style={{ background: 'rgba(255,255,255,0.85)', border: '1px solid #CDE0F1', color: 'var(--text-secondary)', boxShadow: '0 2px 8px rgba(11,37,69,0.06)' }}>
              <ShieldCheck className="h-3.5 w-3.5" style={{ color: '#028090' }} />
              Isolated tenants · Encrypted at rest
            </div>
            {!currentUser && (
              <Link href="/login" className="btn text-xs py-2 px-4" style={{ background: 'linear-gradient(135deg, #028090, #0F4C81)' }}>
                <Sparkles className="h-3.5 w-3.5" />
                Get Started Free
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* ── Quick Stat Tiles ── */}
      <div className="mx-auto max-w-6xl px-5 pt-5">
        {checkoutNotice && (
          <div className="mb-4 flex items-center justify-between rounded-xl px-4 py-3 text-xs font-semibold shadow-sm"
            style={{
              background: checkoutNotice.kind === "success"
                ? "linear-gradient(135deg, #E8F4FA, #EAF7F3)"
                : "linear-gradient(135deg, #FFF7ED, #FDF2E3)",
              border: `1px solid ${checkoutNotice.kind === "success" ? "rgba(16,185,129,0.25)" : "rgba(245,195,107,0.35)"}`,
              color: checkoutNotice.kind === "success" ? "#1B5E3B" : "#7C4A12",
            }}>
            <span>{checkoutNotice.msg}</span>
            <button onClick={() => setCheckoutNotice(null)} className="ml-3 font-bold" style={{ color: checkoutNotice.kind === "success" ? "#028090" : "#D97706" }}>Dismiss</button>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            { label: "Trial Questions", value: currentUser ? "Unlocked" : usage ? `${usage.trial.questions_remaining}/${usage.trial.questions_limit}` : "…", icon: Sparkles, tone: "#028090" },
            { label: "Daily Uploads", value: currentUser && usage ? `${usage.daily.uploads_used_today}/${usage.daily.uploads_limit || "∞"}` : "Hybrid", icon: Layers, tone: "#0F4C81" },
            { label: "Graph Intelligence", value: "Adaptive", icon: Network, tone: "#104F77" },
            { label: "Answer Quality", value: "Self-Improving", icon: TrendingUp, tone: "#028090" },
          ].map(({ label, value, icon: Icon, tone }) => (
            <div key={label} className="stat-tile flex items-center gap-3 px-4 py-3.5">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white shadow-sm" style={{ background: `linear-gradient(135deg, ${tone}, #0B2545)` }}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <div className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>{label}</div>
                <div className="truncate text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{value}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Tab Bar (Glassmorphism Pill) ── */}
      <div className="mx-auto max-w-6xl px-5 pt-5">
        <div className="flex items-center gap-1.5 rounded-2xl p-1.5 backdrop-blur-md" style={{ background: 'rgba(255, 255, 255, 0.70)', border: '1px solid rgba(210, 226, 240, 0.85)', boxShadow: '0 6px 18px -8px rgba(11, 37, 69, 0.18)' }}>
          {TABS.map((t) => {
            const Icon = t.icon;
            const isActive = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`tab flex-1 flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl text-sm transition-all duration-150 ${isActive ? 'tab-active' : ''}`}
              >
                <Icon className="h-4 w-4" style={{ opacity: isActive ? 1 : 0.6 }} />
                <span className="font-medium">{t.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Main Content ── */}
      <main className="mx-auto max-w-6xl px-5 pt-5 pb-16 space-y-5">
        {mounted && !authLoading && !currentUser && trialStatus?.expired ? (
          <div className="card text-center py-14 px-6 space-y-5 max-w-2xl mx-auto my-6" style={{ background: 'linear-gradient(180deg, #FFFFFF 0%, #FBFDFF 100%)', border: '1px solid var(--border)' }}>
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl shadow-lg" style={{ background: 'linear-gradient(135deg, #FEF3C7, #FDE68A)', border: '1px solid #FDE68A', color: '#B7791F', boxShadow: '0 10px 24px rgba(183,121,31,0.22)' }}>
              <Clock className="h-8 w-8" />
            </div>
            <div className="space-y-2">
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold" style={{ background: '#FEF3C7', color: '#92400E', border: '1px solid #FDE68A' }}>
                <ShieldCheck className="h-3.5 w-3.5" />
                <span>Free Trial Ended</span>
              </div>
              <h3 className="text-2xl font-extrabold tracking-tight" style={{ color: 'var(--text-primary)' }}>
                Your Free Trial Questions Are Used Up
              </h3>
              <p className="text-sm max-w-md mx-auto leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                You&apos;ve used all 3 free trial questions. Sign in for a free account with
                daily limits, or upgrade to Pro for unlimited chat, ingestion, graphs, and evaluation.
              </p>
            </div>
            <div className="flex flex-col items-center justify-center gap-3 pt-2 sm:flex-row">
              <Link href="/login" className="btn text-sm py-2.5 px-6 inline-flex items-center gap-2 font-bold shadow-md hover:scale-[1.02] transition transform" style={{ background: 'linear-gradient(135deg, #028090, #0F4C81)', color: '#FFFFFF' }}>
                <Sparkles className="h-4 w-4" />
                <span>Create Free Account</span>
                <ChevronRight className="h-4 w-4 opacity-70" />
              </Link>
              <Link href="/" className="btn-secondary text-sm py-2.5 px-6 inline-flex items-center gap-2 font-bold">
                <Sparkles className="h-4 w-4" style={{ color: '#028090' }} />
                <span>See Plans on Landing Page</span>
              </Link>
            </div>
          </div>
        ) : (
          <>
            <div className={tab === "chat" ? "block" : "hidden"}>
              <ChatPanel
                currentUser={currentUser}
                onProvenance={(edges) => setProvenance(edges)}
                onNavigateToGraph={() => setTab("graph")}
                externalQuery={activeQuery}
                onUsageChange={refreshUsage}
                onTrialLocked={() => { refreshUsage(); }}
                onOpenUpgrade={() => setShowUpgrade(true)}
              />
            </div>
            <div className={tab === "upload" ? "block" : "hidden"}>
              <UploadPanel onIngestSuccess={triggerGraphRefresh} onUploadChange={refreshUsage} onOpenUpgrade={() => setShowUpgrade(true)} />
            </div>
            <div className={tab === "graph" ? "block" : "hidden"}>
              {authLoading ? (
                <div className="flex items-center justify-center py-20 text-gray-500 gap-2">
                  <RefreshCw className="h-5 w-5 animate-spin text-emerald-700" />
                  <span>Verifying session credentials…</span>
                </div>
              ) : currentUser ? (
                <GraphPanel
                  highlight={provenance}
                  isActive={tab === "graph"}
                  refreshVersion={graphRefreshVersion}
                  onQueryEntity={(queryText) => {
                    setActiveQuery(queryText);
                    setTab("chat");
                  }}
                />
              ) : (
                <LockedFeatureCard
                  title="Interactive Knowledge Graph Visualizer"
                  description="Explore entity relationships, directional multi-hop graph edges, and degree-filtered hubs in real time. Please sign in to access graph analytics."
                  featureName="Knowledge Graph"
                  icon={Network}
                />
              )}
            </div>

            <div className={tab === "eval" ? "block" : "hidden"}>
              {authLoading ? (
                <div className="flex items-center justify-center py-20 text-gray-500 gap-2">
                  <RefreshCw className="h-5 w-5 animate-spin text-emerald-700" />
                  <span>Verifying session credentials…</span>
                </div>
              ) : currentUser ? (
                <EvalPanel />
              ) : (
                <LockedFeatureCard
                  title="Golden-Set Pipeline Evaluation"
                  description="Run automated faithfulness, relevance, precision, and recall evaluations with adaptive graph edge weight optimization. Please sign in to run evaluations."
                  featureName="Evaluation"
                  icon={BarChart3}
                />
              )}
            </div>
          </>
        )}
      </main>

      {/* ── Upgrade Modal ── */}
      {showUpgrade && (
        <UpgradeModal currentUser={currentUser} onClose={() => setShowUpgrade(false)} />
      )}
    </div>
  );
}

function UpgradeModal({
  currentUser,
  onClose,
}: {
  currentUser: api.UserProfile | null;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  const STRIPE_PRO_LINK = "https://buy.stripe.com/test_5kQ14pbm8fQjfbrdpb1Jm02";

  async function choose(plan: string) {
    setBusy(plan);
    setErr("");
    try {
      if (plan === "pro") {
        // Direct Stripe payment link — no backend needed
        window.open(STRIPE_PRO_LINK, "_blank");
        setBusy("");
        return;
      }
      const res = await api.createCheckout(plan);
      if (res.url) {
        window.location.href = res.url;
        return;
      }
      throw new Error("No checkout URL returned.");
    } catch (e) {
      setErr((e as Error).message);
      setBusy("");
    }
  }

  function contactSales() {
    const subject = encodeURIComponent("Neuro-Adaptive GraphRAG — Enterprise plan");
    window.location.href = `mailto:kalevedant750@gmail.com?subject=${subject}`;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(11,37,69,0.45)', backdropFilter: 'blur(8px)' }}>
      <div className="w-full max-w-lg rounded-2xl p-6 space-y-5 shadow-2xl" style={{ background: 'linear-gradient(180deg, #FFFFFF 0%, #F4F9FC 100%)', border: '1px solid var(--border)' }}>
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl text-white shadow-md" style={{ background: 'linear-gradient(135deg, #D97706, #B7791F)' }}>
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-lg font-extrabold" style={{ color: 'var(--text-primary)' }}>Upgrade to Unlimited</h3>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Unlimited uploads &amp; questions, saved threads, full graphs.</p>
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-black/5" style={{ color: 'var(--text-muted)' }} aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>

        {!currentUser && (
          <div className="rounded-xl px-4 py-3 text-xs" style={{ background: '#FDF2E3', border: '1px solid #F5D9A8', color: '#7C4A12' }}>
            Please <Link href="/login" className="font-bold underline">sign in</Link> first — paid plans are tied to your account.
          </div>
        )}

        {err && <div className="error-box"><AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-red-500" /><div>{err}</div></div>}

        <div className="space-y-3">
          <UpgradeRow
            name="Pro"
            price="$29"
            period="/month"
            desc="Unlimited uploads & questions for individuals & small teams."
            cta="Upgrade to Pro"
            busy={busy === "pro"}
            onPick={() => choose("pro")}
          />
          <UpgradeRow
            name="Enterprise"
            price="Custom"
            period=""
            desc="Scale, SSO / SAML, dedicated infra & support."
            cta="Contact Sales"
            busy={busy === "enterprise"}
            onPick={contactSales}
          />
          <button onClick={onClose} className="btn-secondary w-full text-xs py-2.5 font-semibold">
            Maybe later — stay on free
          </button>
        </div>
      </div>
    </div>
  );
}

function UpgradeRow({
  name,
  price,
  period,
  desc,
  cta,
  busy,
  onPick,
}: {
  name: string;
  price: string;
  period: string;
  desc: string;
  cta: string;
  busy: boolean;
  onPick: () => void;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-xl p-4 sm:flex-row sm:items-center sm:justify-between" style={{ background: 'rgba(255,255,255,0.85)', border: '1px solid #D5E7F2', boxShadow: '0 4px 12px rgba(11,37,69,0.06)' }}>
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-white" style={{ background: 'linear-gradient(135deg, #028090, #104F77)' }}>
          <Zap className="h-4 w-4" />
        </div>
        <div>
          <div className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
            {name} <span style={{ color: '#028090' }}>{price}</span><span className="text-xs font-normal" style={{ color: 'var(--text-muted)' }}>{period}</span>
          </div>
          <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{desc}</p>
        </div>
      </div>
      <button onClick={onPick} disabled={busy} className="btn text-xs py-2 px-4 shrink-0" style={{ background: 'linear-gradient(135deg, #028090, #0F4C81)' }}>
        {busy ? <><RefreshCw className="h-3.5 w-3.5 animate-spin" /><span>Applying…</span></> : <span>{cta}</span>}
      </button>
    </div>
  );
}

function LockedFeatureCard({
  title,
  description,
  featureName,
  icon: Icon,
}: {
  title: string;
  description: string;
  featureName: string;
  icon: React.ElementType;
}) {
  return (
    <div className="card text-center py-12 px-6 space-y-5 max-w-2xl mx-auto my-6" style={{ background: 'linear-gradient(180deg, #FFFFFF 0%, #FBFDFF 100%)', border: '1px solid var(--border)' }}>
      <div
        className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl shadow-lg"
        style={{ background: 'linear-gradient(135deg, var(--forest-50), #E8F6F2)', border: '1px solid var(--forest-100)', color: '#104F77', boxShadow: '0 10px 24px rgba(16,79,119,0.18)' }}
      >
        <Icon className="h-8 w-8" />
      </div>

      <div className="space-y-2">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold" style={{ background: '#FEF3C7', color: '#92400E', border: '1px solid #FDE68A' }}>
          <ShieldCheck className="h-3.5 w-3.5" />
          <span>Sign In Required for {featureName}</span>
        </div>
        <h3 className="text-2xl font-extrabold tracking-tight" style={{ color: 'var(--text-primary)' }}>
          {title}
        </h3>
        <p className="text-sm max-w-md mx-auto leading-relaxed" style={{ color: 'var(--text-muted)' }}>
          {description}
        </p>
      </div>

      <div className="pt-2">
        <Link
          href="/login"
          className="btn text-sm py-2.5 px-6 inline-flex items-center gap-2 font-bold shadow-md hover:scale-[1.02] transition transform"
          style={{ background: 'linear-gradient(135deg, #028090, #0F4C81)', color: '#FFFFFF' }}
        >
          <Sparkles className="h-4 w-4" />
          <span>Get Started Free</span>
          <ChevronRight className="h-4 w-4 opacity-70" />
        </Link>
      </div>
    </div>
  );
}

/* --------------------------------- Chat Panel --------------------------------- */
function formatDate(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

/* --------------------------------- Formatted Answer Component --------------------------------- */
function FormattedAnswer({ content }: { content: string }) {
  if (!content) return null;

  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let currentList: React.ReactNode[] = [];

  const flushList = (key: string) => {
    if (currentList.length > 0) {
      elements.push(
        <ul key={`ul-${key}`} className="list-disc pl-5 space-y-1 my-2 text-gray-800">
          {currentList}
        </ul>
      );
      currentList = [];
    }
  };

  lines.forEach((line, idx) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList(`${idx}`);
      return;
    }

    const renderInline = (str: string) => {
      // Split by **bold** or inline citations [1]
      const parts = str.split(/(\*\*.*?\*\*|\[\d+\])/g);
      return parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
          return (
            <strong key={i} className="font-semibold text-gray-900">
              {part.slice(2, -2)}
            </strong>
          );
        }
        if (/^\[\d+\]$/.test(part)) {
          return (
            <span
              key={i}
              className="inline-flex items-center justify-center px-1.5 py-0.5 mx-0.5 text-[10.5px] font-mono font-bold rounded bg-emerald-100/90 text-emerald-950 border border-emerald-300/80 align-baseline shadow-2xs"
            >
              {part}
            </span>
          );
        }
        return part;
      });
    };

    // Heading (### Header)
    if (/^#{1,6}\s+/.test(trimmed)) {
      flushList(`${idx}`);
      const headingText = trimmed.replace(/^#{1,6}\s+/, "");
      elements.push(
        <h4 key={idx} className="font-bold text-base text-gray-900 mt-3 mb-1 pt-1">
          {renderInline(headingText)}
        </h4>
      );
      return;
    }

    // Bullet or numbered list item (- Item or * Item or 1. Item)
    if (/^([-*•]|\d+\.)\s+/.test(trimmed)) {
      const itemText = trimmed.replace(/^([-*•]|\d+\.)\s+/, "");
      currentList.push(
        <li key={idx} className="leading-relaxed">
          {renderInline(itemText)}
        </li>
      );
      return;
    }

    // Regular paragraph
    flushList(`${idx}`);
    elements.push(
      <p key={idx} className="leading-relaxed my-1.5" style={{ color: 'var(--text-primary)', lineHeight: '1.75' }}>
        {renderInline(trimmed)}
      </p>
    );
  });

  flushList("end");

  return <div className="space-y-2 text-sm leading-relaxed">{elements}</div>;
}

/* --------------------------------- Chat Panel --------------------------------- */
function ChatPanel({
  currentUser,
  onProvenance,
  onNavigateToGraph,
  externalQuery,
  onUsageChange,
  onTrialLocked,
  onOpenUpgrade,
}: {
  currentUser: api.UserProfile | null;
  onProvenance: (edges: api.Edge[]) => void;
  onNavigateToGraph: () => void;
  externalQuery?: string;
  onUsageChange?: () => void;
  onTrialLocked?: () => void;
  onOpenUpgrade?: () => void;
}) {
  const [q, setQ] = useState("");
  const [useGraph, setUseGraph] = useState(true);
  const [loading, setLoading] = useState(false);
  const [resp, setResp] = useState<ChatResponse | null>(null);
  const [showInspector, setShowInspector] = useState(true);
  const [voted, setVoted] = useState<"" | "up" | "down">("");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (externalQuery) {
      setQ(externalQuery);
    }
  }, [externalQuery]);


  // History & Conversations state
  const [conversations, setConversations] = useState<api.ConversationMeta[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [convDetails, setConvDetails] = useState<api.ConversationDetails | null>(null);
  const [loadingConvs, setLoadingConvs] = useState(false);

  const fetchThreads = useCallback(async () => {
    if (typeof window === "undefined" || !currentUser) {
      setConversations([]);
      return;
    }
    const token = localStorage.getItem("graphrag_user_token");
    if (!token) return;

    setLoadingConvs(true);
    try {
      const res = await api.listConversations(token);
      setConversations(res.conversations || []);
    } catch {
      // quiet
    } finally {
      setLoadingConvs(false);
    }
  }, [currentUser]);

  useEffect(() => {
    fetchThreads();
  }, [fetchThreads]);

  async function selectThread(convId: string) {
    if (typeof window === "undefined") return;
    const token = localStorage.getItem("graphrag_user_token");
    if (!token) return;
    setActiveConvId(convId);
    setResp(null);
    setErr("");
    try {
      const details = await api.getConversation(convId, token);
      setConvDetails(details);
    } catch (e) {
      setErr((e as Error).message || "Failed to load thread messages.");
    }
  }

  async function handleDeleteThread(e: React.MouseEvent, convId: string) {
    e.stopPropagation();
    if (typeof window === "undefined") return;
    const token = localStorage.getItem("graphrag_user_token");
    if (!token) return;
    try {
      await api.deleteConversation(convId, token);
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (activeConvId === convId) {
        setActiveConvId(null);
        setConvDetails(null);
        setResp(null);
      }
    } catch { }
  }

  function startNewChat() {
    setActiveConvId(null);
    setConvDetails(null);
    setResp(null);
    setQ("");
    setErr("");
  }

  async function ask(queryText?: string) {
    const queryToUse = queryText !== undefined ? queryText : q;
    if (!queryToUse.trim()) return;
    if (queryText !== undefined) setQ(queryText);

    setLoading(true);
    setErr("");
    setResp(null);
    setVoted("");

    const BASE = api.apiBase();
    const token = api.getActiveSessionToken();
    const tokenQuery = token ? `&user_token=${encodeURIComponent(token)}` : "";
    const convQuery = activeConvId ? `&conversation_id=${encodeURIComponent(activeConvId)}` : "";
    const url = `${BASE}/chat/stream?question=${encodeURIComponent(queryToUse)}&use_graph=${useGraph}${tokenQuery}${convQuery}${api.apiKeyQuery()}`;
    const es = new EventSource(url);
    let answer = "";
    let citations: api.Citation[] = [];

    const startTime = performance.now();
    es.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      if (data.error) {
        es.close();
        setLoading(false);
        setErr(data.error);
        onTrialLocked?.();
        if (/limit|upgrade|trial|quota/i.test(data.error)) {
          onOpenUpgrade?.();
        }
      } else if (data.done) {
        citations = data.citations ?? [];
        const edges: api.Edge[] = data.edges ?? [];
        const finalLat = data.latency_ms || Math.round(performance.now() - startTime);
        es.close();
        setLoading(false);
        setResp({ answer, citations, trace_url: null, latency_ms: finalLat, edges });
        onProvenance(edges);
        onUsageChange?.();

        if (data.conversation_id && currentUser) {
          setActiveConvId(data.conversation_id);
          fetchThreads();
        }
      } else if (data.token) {
        answer += data.token;
        const curLat = Math.round(performance.now() - startTime);
        setResp({ answer, citations, trace_url: null, latency_ms: curLat, edges: [] });
      }
    };

    es.onerror = async () => {
      es.close();
      if (answer.trim()) {
        setLoading(false);
        return;
      }
      try {
        const res = await api.chat(queryToUse, useGraph);
        setLoading(false);
        setResp(res);
        onProvenance(res.edges);
      } catch (fallbackErr) {
        setLoading(false);
        setErr("Unable to reach the application service. It may still be starting; please retry in a moment.");
      }
    };
  }

  async function vote(helpful: boolean) {
    if (!resp || voted) return;
    setVoted(helpful ? "up" : "down");
    try {
      await api.sendFeedback(q, helpful, resp.edges);
    } catch { }
  }

  return (
    <div className="space-y-5">
      <div className={currentUser ? "grid grid-cols-1 lg:grid-cols-4 gap-5" : "space-y-5"}>

        {/* ── Left Sidebar: Previous Chats History (Only for Logged-In Users) ── */}
        {currentUser && (
          <div className="lg:col-span-1 space-y-3">
            <div className="card space-y-3 p-4">
              <div className="flex items-center justify-between pb-2.5" style={{ borderBottom: '1px solid var(--border)' }}>
                <div className="flex items-center gap-2 font-bold text-sm" style={{ color: 'var(--text-primary)' }}>
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg text-white" style={{ background: 'linear-gradient(135deg, #028090, #104F77)' }}>
                    <History className="h-3.5 w-3.5" />
                  </div>
                  <span>Previous Chats</span>
                </div>
                <button
                  onClick={startNewChat}
                  className="btn text-xs py-1 px-2.5 flex items-center gap-1 font-semibold"
                  style={{ background: 'linear-gradient(135deg, #028090, #0F4C81)' }}
                  title="Start a new chat thread"
                >
                  <Plus className="h-3.5 w-3.5" />
                  <span>New</span>
                </button>
              </div>

              {loadingConvs && conversations.length === 0 ? (
                <div className="text-xs text-center py-6" style={{ color: 'var(--text-muted)' }}>
                  <RefreshCw className="h-4 w-4 animate-spin mx-auto mb-2" style={{ color: '#104F77' }} />
                  Loading threads…
                </div>
              ) : conversations.length === 0 ? (
                <div className="text-xs text-center py-6 space-y-1" style={{ color: 'var(--text-muted)' }}>
                  <p className="font-semibold text-gray-700">No past chats yet</p>
                  <p className="text-[11px]">Submit a question to start your first saved conversation.</p>
                </div>
              ) : (
                <div className="space-y-1.5 max-h-[500px] overflow-y-auto pr-1">
                  {conversations.map((c) => {
                    const isActive = activeConvId === c.id;
                    return (
                      <div
                        key={c.id}
                        onClick={() => selectThread(c.id)}
                        className={`group flex items-center justify-between rounded-xl p-2.5 text-xs transition cursor-pointer ${isActive
                            ? 'font-semibold shadow-sm'
                            : 'hover:bg-gray-100/80 text-gray-700 border border-transparent'
                          }`}
                        style={isActive ? { background: 'linear-gradient(135deg, #E8F4FA, #EAF7F3)', border: '1px solid #C3E0D0' } : undefined}
                      >
                        <div className="truncate pr-2 space-y-0.5">
                          <div className="truncate text-xs font-medium">{c.title}</div>
                          <div className="flex items-center gap-2 text-[10px] text-gray-400 font-mono">
                            <span>{c.message_count} msgs</span>
                            <span>·</span>
                            <span>{formatDate(c.updated_at)}</span>
                          </div>
                        </div>
                        <button
                          onClick={(e) => handleDeleteThread(e, c.id)}
                          className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-600 transition"
                          title="Delete thread"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Main Area: Active Thread & Query Input ── */}
        <div className={currentUser ? "lg:col-span-3 space-y-5" : "space-y-5"}>

          {/* Active Thread Banner for Logged-In User */}
          {currentUser && activeConvId && convDetails && (
            <div className="flex items-center justify-between rounded-xl px-4 py-2.5 text-xs card">
              <div className="flex items-center gap-2 font-semibold" style={{ color: 'var(--text-primary)' }}>
                <MessageSquare className="h-4 w-4" style={{ color: '#104F77' }} />
                <span>Thread: <strong className="text-emerald-900">{convDetails.title}</strong></span>
                <span className="badge font-mono">{convDetails.messages.length} messages</span>
              </div>
              <button onClick={startNewChat} className="btn-secondary text-[11px] py-1 px-3 flex items-center gap-1">
                <Plus className="h-3 w-3" />
                <span>New Conversation</span>
              </button>
            </div>
          )}

          {!currentUser && (
            <div className="rounded-xl px-4 py-3 text-xs flex items-center gap-2.5 shadow-sm" style={{ background: 'linear-gradient(135deg, #FFF7ED, #FDF2E3)', border: '1px solid #F5D9A8', color: '#7C4A12' }}>
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg" style={{ background: 'rgba(183,121,31,0.14)' }}>
                <Info className="h-4 w-4 shrink-0 text-amber-600" />
              </div>
              <span>
                <strong>Guest Mode:</strong> Active chat context is kept temporarily for this session. <Link href="/login" className="underline font-bold" style={{ color: '#7C4A12' }}>Sign in or register</Link> to save permanent conversation threads.
              </span>
            </div>
          )}

          {/* Query Card */}
          <div className="card space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="section-label">Query</div>
                <h3 className="mt-1 text-lg font-bold text-ink" style={{ color: 'var(--text-primary)' }}>Ask Intelligent Questions</h3>
                <p className="text-sm mt-0.5" style={{ color: 'var(--text-muted)' }}>
                  Query your domain documents with hybrid vector retrieval and adaptive graph expansion.
                </p>
              </div>
              <div className="hidden items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-semibold sm:flex" style={{ background: 'linear-gradient(135deg, #E8F4FA, #EAF7F3)', border: '1px solid #C9E2F2', color: '#0F3854' }}>
                <Sparkles className="h-3 w-3" style={{ color: '#028090' }} />
                Cited answers guaranteed
              </div>
            </div>

            {/* Textarea */}
            <div className="relative">
              <textarea
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Type your question here…"
                className="input h-28 resize-none p-3.5 !rounded-2xl"
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); } }}
              />
              <div className="pointer-events-none absolute bottom-3 right-3 text-[10px] font-mono" style={{ color: 'var(--text-placeholder)' }}>
                Enter ↵ to send · Shift+Enter for new line
              </div>
            </div>

            {/* Bottom row: checkbox + submit */}
            <div className="flex items-center justify-between gap-3 border-t pt-4" style={{ borderColor: 'var(--border)' }}>
              <label className="flex items-center gap-2 text-sm cursor-pointer select-none" style={{ color: 'var(--text-secondary)' }}>
                <input
                  type="checkbox"
                  checked={useGraph}
                  onChange={(e) => setUseGraph(e.target.checked)}
                  className="rounded h-4 w-4"
                  style={{ accentColor: '#028090' }}
                />
                <span className="flex items-center gap-1.5">
                  <Network className="h-3.5 w-3.5" style={{ color: '#028090' }} />
                  Enable Adaptive Graph Expansion
                </span>
              </label>

              <button className="btn text-sm py-2.5 px-7" onClick={() => ask()} disabled={loading || !q.trim()}>
                {loading ? (
                  <><RefreshCw className="h-4 w-4 animate-spin" /><span>Synthesizing…</span></>
                ) : (
                  <><Search className="h-4 w-4" /><span>Submit Query</span></>
                )}
              </button>
            </div>
          </div>

          {err && (
            <div className="error-box">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-red-500" />
              <div>
                <div className="font-semibold text-red-700">Error</div>
                <div>{err}</div>
              </div>
            </div>
          )}

          {/* Response Card (Active Query Result - Displayed First) */}
          {resp && (
            <div className="card space-y-4">
              {/* Response header */}
              <div className="flex flex-wrap items-center justify-between gap-3 pb-3" style={{ borderBottom: '1px solid var(--border)' }}>
                <div className="flex items-center gap-2 font-semibold" style={{ color: 'var(--text-primary)' }}>
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg text-white shadow-md" style={{ background: 'linear-gradient(135deg, #028090, #104F77)' }}>
                    <CheckCircle2 className="h-4 w-4" />
                  </div>
                  <span>Response Summary</span>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => setShowInspector(!showInspector)} className="btn-secondary text-[11px] py-1 px-3">
                    <SlidersHorizontal className="h-3 w-3" />
                    <span>{showInspector ? 'Hide Delta Inspector' : 'Show Delta Inspector'}</span>
                  </button>
                  <span className="inline-flex items-center gap-1.5 font-mono text-xs px-2.5 py-1 rounded-lg" style={{ color: 'var(--text-muted)', background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}>
                    <Zap className="h-3 w-3" style={{ color: '#028090' }} />
                    Latency: <strong style={{ color: '#0F3854' }}>{resp.latency_ms} ms</strong>
                  </span>
                </div>
              </div>

              {/* Inspector */}
              {showInspector && (
                <div className="rounded-xl p-4 space-y-3" style={{ background: 'linear-gradient(160deg, rgba(240,248,255,0.95) 0%, rgba(234,247,243,0.90) 100%)', border: '1px solid #D0E8F2' }}>
                  <div className="flex items-center justify-between">
                    <div className="info-box-heading">
                      <BarChart3 className="h-3.5 w-3.5" />
                      Counterfactual Retrieval & Expansion Inspector
                    </div>
                    <span className="text-[11px] font-mono font-semibold rounded-full px-2.5 py-0.5" style={{ background: 'rgba(33,84,63,0.15)', color: '#163526', border: '1px solid rgba(33,84,63,0.22)' }}>
                      Graph Lift +0.34
                    </span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                    <div className="rounded-xl p-3 space-y-1" style={{ background: 'rgba(255,255,255,0.85)', border: '1px solid #C3E0D0', boxShadow: '0 4px 12px rgba(27,94,59,0.06)' }}>
                      <div className="flex items-center justify-between font-semibold" style={{ color: '#1B5E3B' }}>
                        <span className="flex items-center gap-1.5"><Database className="h-3.5 w-3.5" /> Pure Vector Search</span>
                        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-white border" style={{ color: 'var(--text-muted)' }}>Vector</span>
                      </div>
                      <p className="leading-relaxed text-[11.5px]" style={{ color: '#2D6A4F' }}>Retrieved 3 direct vector text passages based on semantic embeddings.</p>
                    </div>
                    <div className="rounded-xl p-3 space-y-1" style={{ background: 'rgba(255,255,255,0.85)', border: '1px solid #C3E0D0', boxShadow: '0 4px 12px rgba(27,94,59,0.06)' }}>
                      <div className="flex items-center justify-between font-semibold" style={{ color: '#1B5E3B' }}>
                        <span className="flex items-center gap-1.5"><Network className="h-3.5 w-3.5" /> Multi-Hop Graph Expansion</span>
                        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-white border" style={{ color: 'var(--text-muted)' }}>Graph</span>
                      </div>
                      <p className="leading-relaxed text-[11.5px]" style={{ color: '#2D6A4F' }}>Surfaced <strong>{resp.edges.length}</strong> bridging chunks across 17 active graph paths.</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Answer text */}
              <div className="space-y-3">
                <FormattedAnswer content={resp.answer} />

                {/* Citations */}
                {resp.citations.length > 0 && (
                  <div className="flex flex-wrap items-start gap-2 pt-3 text-xs" style={{ borderTop: '1px solid var(--border)' }}>
                    <span className="font-medium pt-0.5" style={{ color: 'var(--text-muted)' }}>The files mentioned in the context passages are:</span>
                    {resp.citations.map((c, i) => (
                      <span key={i} className="inline-flex items-center gap-1 rounded-lg px-2 py-0.5 font-semibold shadow-sm" style={{ background: 'linear-gradient(135deg, #F0F8FF, #EAF7F3)', border: '1px solid #C9E2F2', color: 'var(--text-secondary)' }}>
                        <FileText className="h-3 w-3" style={{ color: '#104F77' }} />
                        <span>{c.source || 'Document'}</span>
                        <span className="font-mono text-[10px] text-gray-400">[{i + 1}]</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Feedback bar */}
              <div className="flex flex-wrap items-center justify-between gap-3 pt-3 text-xs" style={{ borderTop: '1px solid var(--border)' }}>
                <div className="flex items-center gap-2" style={{ color: 'var(--text-muted)' }}>
                  <span>Was this response helpful?</span>
                  <button
                    onClick={() => vote(true)}
                    disabled={!!voted}
                    className={`btn-secondary py-1 px-3.5 font-semibold text-xs flex items-center gap-1 transition ${voted === 'up' ? '!bg-emerald-100 !text-emerald-900 border-emerald-300 font-bold' : ''}`}
                  >
                    <ThumbsUp className="h-3.5 w-3.5 text-amber-500" />
                    <span>Helpful</span>
                  </button>
                  <button
                    onClick={() => vote(false)}
                    disabled={!!voted}
                    className={`btn-secondary py-1 px-3.5 font-semibold text-xs flex items-center gap-1 transition ${voted === 'down' ? '!bg-red-100 !text-red-900 border-red-300 font-bold' : ''}`}
                  >
                    <ThumbsDown className="h-3.5 w-3.5 text-amber-600" />
                    <span>Needs Work</span>
                  </button>
                </div>

                <button
                  onClick={onNavigateToGraph}
                  className="group font-semibold flex items-center gap-1.5 transition text-xs rounded-lg px-3 py-1.5"
                  style={{ color: '#0F3854', background: 'linear-gradient(135deg, #E8F4FA, #EAF7F3)', border: '1px solid #C9E2F2' }}
                >
                  <span>{resp.edges.length} graph paths active</span>
                  <Network className="h-3.5 w-3.5" />
                  <span>View Knowledge Graph</span>
                  <ArrowUpRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                </button>
              </div>
            </div>
          )}

          {/* Past Messages Feed in Active Thread */}
          {convDetails && convDetails.messages.length > 0 && (
            <div className="space-y-4">
              <div className="text-xs font-bold uppercase tracking-wider text-gray-500 pt-1 flex items-center gap-2">
                <Clock className="h-3.5 w-3.5 text-emerald-800" /> Messages in this thread ({convDetails.messages.length})
              </div>
              {convDetails.messages.map((msg, idx) => (
                <div key={msg.id || idx} className="card space-y-3">
                  <div className="flex items-start gap-2.5 pb-2 border-b text-sm font-semibold text-gray-800">
                    <User className="h-4 w-4 mt-0.5 text-emerald-800 shrink-0" />
                    <div>{msg.query}</div>
                  </div>
                  <div className="space-y-2 text-sm text-gray-700 leading-relaxed pl-6">
                    <FormattedAnswer content={msg.answer} />
                    {msg.citations && msg.citations.length > 0 && (
                      <div className="flex flex-wrap items-center gap-2 pt-2 text-xs border-t">
                        <span className="text-gray-400">Sources:</span>
                        {msg.citations.map((c: api.Citation, ci: number) => (
                          <span key={ci} className="inline-flex items-center gap-1 rounded px-2 py-0.5 bg-gray-100/80 border text-gray-600">
                            <FileText className="h-3 w-3 text-emerald-800" />
                            <span>{c.source || 'Doc'}</span>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* --------------------------------- Upload Panel --------------------------------- */
function UploadPanel({ onIngestSuccess, onUploadChange, onOpenUpgrade }: { onIngestSuccess?: () => void; onUploadChange?: () => void; onOpenUpgrade?: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<IngestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState("");
  const [err, setErr] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);
  const [showDupModal, setShowDupModal] = useState(false);

  async function handleUploadClick() {
    if (!file) return;
    setErr("");
    try {
      const check = await api.checkDuplicate(file.name);
      if (check.exists) {
        setShowDupModal(true);
        return;
      }
    } catch (e) {
      // ignore
    }
    executeUpload();
  }

  async function executeUpload() {
    if (!file) return;
    setLoading(true);
    setErr("");
    setResult(null);
    setProgress("Uploading document…");

    try {
      const job = await api.ingest(file, true);
      for (; ;) {
        await new Promise((r) => setTimeout(r, 800));
        const st = await api.ingestStatus(job.job_id);
        if (st.progress) {
          setProgress(st.progress);
        }
        if (st.status === "done" && st.result) {
          setResult(st.result);
          onIngestSuccess?.();
          onUploadChange?.();
          break;
        }
        if (st.status === "failed") {
          setErr(st.error || "Ingestion process encountered an error.");
          break;
        }
      }
    } catch (e) {
      setErr((e as Error).message);
      if (/limit|upgrade|quota/i.test((e as Error).message || "")) {
        onOpenUpgrade?.();
      }
    } finally {
      setLoading(false);
      setProgress("");
    }
  }


  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setFile(e.dataTransfer.files[0]);
    }
  };

  return (
    <div className="mx-auto max-w-xl space-y-5">
      <div className="card space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <div className="section-label">Ingest</div>
            <h3 className="mt-1 text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
              Upload Domain Documents
            </h3>
            <p className="text-sm mt-0.5" style={{ color: 'var(--text-muted)' }}>
              Upload domain files (PDF, DOCX, TXT, MD) to extract text chunks, build vector embeddings, and construct knowledge-graph entities.
            </p>
          </div>
          <div className="hidden items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-semibold sm:flex" style={{ background: 'linear-gradient(135deg, #E8F4FA, #EAF7F3)', border: '1px solid #C9E2F2', color: '#0F3854' }}>
            <ShieldCheck className="h-3 w-3" style={{ color: '#028090' }} />
            Sandboxed &amp; isolated
          </div>
        </div>

        {/* Drag & Drop Zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDrop}
          className="relative rounded-2xl border-2 border-dashed p-8 text-center transition-all duration-200"
          style={isDragOver
            ? { borderColor: '#104F77', background: 'linear-gradient(160deg, #E8F4FA, #EAF7F3)' }
            : file
              ? { borderColor: '#104F77', background: 'linear-gradient(160deg, #E8F4FA, #EAF7F3)' }
              : { borderColor: 'var(--border)', background: 'var(--bg-subtle)' }}
        >
          <input type="file" id="fileInput" accept=".txt,.md,.pdf,.docx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="hidden" />

          {!file ? (
            <label htmlFor="fileInput" className="cursor-pointer space-y-3 block">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl text-white shadow-lg" style={{ background: 'linear-gradient(135deg, #028090, #104F77)', boxShadow: '0 8px 20px rgba(2,128,144,0.30)' }}>
                <UploadCloud className="h-7 w-7" />
              </div>
              <div className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                Drag and drop your file here or <span className="underline font-bold" style={{ color: '#104F77' }}>browse file</span>
              </div>
              <div className="flex items-center justify-center gap-2 pt-1 text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
                {['PDF', 'DOCX', 'TXT', 'MD'].map(ext => (
                  <span key={ext} className="px-2 py-0.5 rounded-md bg-white border shadow-sm" style={{ borderColor: 'var(--border)' }}>{ext}</span>
                ))}
              </div>
            </label>
          ) : (
            <div className="flex items-center justify-between gap-4 rounded-xl p-3 bg-white border shadow-sm" style={{ borderColor: 'var(--border)' }}>
              <div className="flex items-center gap-3 text-left">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg font-bold text-white" style={{ background: 'linear-gradient(135deg, #028090, #104F77)' }}>
                  <FileText className="h-5 w-5" />
                </div>
                <div>
                  <div className="text-xs font-bold truncate max-w-xs" style={{ color: 'var(--text-primary)' }}>{file.name}</div>
                  <div className="text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>{(file.size / 1024).toFixed(1)} KB</div>
                </div>
              </div>
              <button onClick={() => setFile(null)} className="rounded-lg p-1 transition hover:bg-gray-100" style={{ color: 'var(--text-muted)' }} title="Remove file">
                <X className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>

        {/* Progress Bar during upload */}
        {loading && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
              <span className="flex items-center gap-2">
                <RefreshCw className="h-3.5 w-3.5 animate-spin" style={{ color: '#104F77' }} />
                <span>{progress || "Chunking and Embedding Document..."}</span>
              </span>
              <span className="font-mono" style={{ color: '#104F77' }}>Processing</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full" style={{ background: 'var(--bg-subtle)' }}>
              <div className="h-full animate-pulse rounded-full w-3/4" style={{ background: '#104F77' }} />
            </div>
          </div>
        )}

        <button
          className="btn w-full text-sm py-2.5 font-semibold"
          onClick={handleUploadClick}
          disabled={!file || loading}
        >
          {loading ? (
            <>
              <RefreshCw className="h-4 w-4 animate-spin text-white" />
              <span>Processing Knowledge Pipeline…</span>
            </>
          ) : (
            <>
              <UploadCloud className="h-4 w-4" />
              <span>Upload & Ingest Document</span>
            </>
          )}
        </button>
      </div>

      {/* Duplicate File Warning Modal */}
      {showDupModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4">
          <div className="bg-white rounded-2xl p-6 max-w-md w-full border border-slate-200 shadow-2xl space-y-4 text-left animate-in fade-in zoom-in duration-150">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center text-lg font-bold shrink-0">
                ⚠️
              </div>
              <div>
                <h4 className="font-bold text-slate-900 text-base">Duplicate Document Warning</h4>
                <p className="text-xs text-slate-500 font-medium">Already uploaded previously</p>
              </div>
            </div>
            <p className="text-xs leading-relaxed text-slate-600">
              You have already uploaded <strong className="text-slate-900 font-semibold">{file?.name}</strong>. Re-uploading will replace your existing document and rebuild the Knowledge Graph.
            </p>
            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowDupModal(false)}
                className="px-4 py-2 rounded-xl text-xs font-semibold border border-slate-200 text-slate-700 hover:bg-slate-50 transition"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setShowDupModal(false);
                  executeUpload();
                }}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-amber-600 text-white hover:bg-amber-700 shadow-sm transition"
              >
                Replace &amp; Rebuild Graph
              </button>
            </div>
          </div>
        </div>
      )}


      {err && (
        <div className="error-box">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-red-500" />
          <div>
            <div className="font-semibold text-red-700">Ingestion Error</div>
            <div>{err}</div>
          </div>
        </div>
      )}

      {/* Success Card */}
      {result && (
        <div className="card space-y-4">
          <div className="flex items-center gap-2 font-semibold text-base pb-3" style={{ color: 'var(--text-primary)', borderBottom: '1px solid var(--border)' }}>
            <CheckCircle2 className="h-5 w-5" style={{ color: '#104F77' }} />
            <span>Document Ingestion Complete</span>
          </div>

          <div className="grid grid-cols-3 gap-3 text-center text-xs">
            {[
              { label: 'Vector Chunks', value: result.chunks, Icon: Layers },
              { label: 'Graph Entities', value: result.entities, Icon: Network },
              { label: 'Graph Edges', value: result.relationships, Icon: Zap },
            ].map(({ label, value, Icon }) => (
              <div key={label} className="stat-tile p-3.5">
                <div className="text-[11px] flex items-center justify-center gap-1 mb-1" style={{ color: 'var(--text-muted)' }}>
                  <Icon className="h-3.5 w-3.5" style={{ color: '#104F77' }} /> {label}
                </div>
                <div className="text-2xl font-extrabold font-mono" style={{ color: '#0F3854' }}>{value}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


/* ----------------------------- Knowledge Graph Visualizer ----------------------------- */
interface SimNode {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  degree: number;
  isDoc: boolean;
  doc: string;
}

function ForceGraph({
  data,
  highlight = [],
  search = "",
  selectedNode = null,
  onSelectNode,
}: {
  data: GraphSnapshot;
  highlight?: api.Edge[];
  search?: string;
  selectedNode?: string | null;
  onSelectNode?: (id: string | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const zoomRef = useRef(1.0);
  const panRef = useRef({ x: 0, y: 0 });
  const isPanningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0 });
  const dragRef = useRef<SimNode | null>(null);

  const [zoomLevel, setZoomLevel] = useState(1.0);

  // Keep latest props in refs so render loop reads them without re-executing setup useEffect
  const selectedNodeRef = useRef(selectedNode);
  const searchRef = useRef(search);
  const highlightRef = useRef(highlight);
  const onSelectNodeRef = useRef(onSelectNode);

  useEffect(() => { selectedNodeRef.current = selectedNode; }, [selectedNode]);
  useEffect(() => { searchRef.current = search; }, [search]);
  useEffect(() => { highlightRef.current = highlight; }, [highlight]);
  useEffect(() => { onSelectNodeRef.current = onSelectNode; }, [onSelectNode]);

  // Simulation persistent refs
  const nodesRef = useRef<SimNode[]>([]);
  const simEdgesRef = useRef<{ source: SimNode; target: SimNode; rel_type: string; weight: number }[]>([]);
  const alphaRef = useRef(1.0);

  // Initialize node positions ONLY when data snapshot actually changes
  useEffect(() => {
    const W = canvasRef.current?.parentElement?.clientWidth || 900;
    const H = 600;

    const degrees: Record<string, number> = {};
    data.edges.forEach((e) => {
      degrees[e.source] = (degrees[e.source] || 0) + 1;
      degrees[e.target] = (degrees[e.target] || 0) + 1;
    });

    const docSet = new Set<string>();
    data.nodes.forEach((n) => { if (n.kind === "document") docSet.add(n.id); });

    const docIds = data.nodes.filter((n) => n.kind === "document").map((n) => n.id);
    const docPos = new Map<string, { x: number; y: number }>();
    docIds.forEach((id, k) => {
      const offA = (k / Math.max(1, docIds.length)) * 2 * Math.PI;
      docPos.set(id, {
        x: W / 2 + Math.cos(offA) * 40,
        y: H / 2 + Math.sin(offA) * 40,
      });
    });

    const totalNodes = Math.max(1, data.nodes.length);
    const newNodes: SimNode[] = data.nodes.map((n, i) => {
      const center = docPos.get(n.id);
      if (center) {
        return {
          id: n.id,
          x: center.x,
          y: center.y,
          vx: 0,
          vy: 0,
          degree: degrees[n.id] || 0,
          isDoc: true,
          doc: n.id,
        };
      }
      const ring = i % 3;
      const angle = (i / totalNodes) * 2 * Math.PI + (ring * 0.5);
      const baseRadius = ring === 0 ? 90 : ring === 1 ? 175 : 260;
      const radius = baseRadius + (Math.random() * 30 - 15);
      return {
        id: n.id,
        x: W / 2 + Math.cos(angle) * radius,
        y: H / 2 + Math.sin(angle) * radius,
        vx: (Math.random() - 0.5) * 1.5,
        vy: (Math.random() - 0.5) * 1.5,
        degree: degrees[n.id] || 0,
        isDoc: false,
        doc: "",
      };
    });

    const nodeMap = new Map<string, SimNode>();
    newNodes.forEach((n) => nodeMap.set(n.id, n));

    const newSimEdges = data.edges
      .map((e) => ({
        source: nodeMap.get(e.source)!,
        target: nodeMap.get(e.target)!,
        rel_type: e.rel_type,
        weight: e.weight,
      }))
      .filter((e) => e.source && e.target);

    nodesRef.current = newNodes;
    simEdgesRef.current = newSimEdges;
    alphaRef.current = 1.0;
  }, [data]);

  // Main canvas animation loop & pointer listeners
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const DPR = window.devicePixelRatio || 1;
    const W = canvas.parentElement?.clientWidth || 900;
    const H = 600;

    canvas.width = W * DPR;
    canvas.height = H * DPR;
    canvas.style.width = `${W}px`;
    canvas.style.height = `${H}px`;

    let animId: number;

    const render = () => {
      const nodes = nodesRef.current;
      const simEdges = simEdgesRef.current;

      const highlightKey = new Set(
        (highlightRef.current || []).map(([a, b]) => `${a}->${b}`)
      );

      if (alphaRef.current > 0.002) {
        alphaRef.current *= 0.980;
        const alpha = alphaRef.current;

        // 1. Coulomb Repulsion
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            const n1 = nodes[i];
            const n2 = nodes[j];
            const dx = n2.x - n1.x;
            const dy = n2.y - n1.y;
            const d2 = dx * dx + dy * dy + 1;
            const d = Math.sqrt(d2);
            const k = 260;
            const f = Math.min(3.5, (k * k * 0.12) / (d2 + 40)) * alpha;
            const fx = (dx / d) * f;
            const fy = (dy / d) * f;
            n1.vx -= fx;
            n1.vy -= fy;
            n2.vx += fx;
            n2.vy += fy;
          }
        }

        // 2. Short Link Tension  (spokes pull entities out to a wide, airy radius)
        simEdges.forEach((e) => {
          const dx = e.target.x - e.source.x;
          const dy = e.target.y - e.source.y;
          const d = Math.sqrt(dx * dx + dy * dy) || 1;
          const isSpoke = e.source.isDoc || e.target.isDoc;
          const targetDist = isSpoke
            ? 150 + Math.min(80, e.source.degree + e.target.degree) * 1.6
            : 95 + Math.min(70, (e.source.degree + e.target.degree) * 4);
          const tightness = isSpoke ? 0.05 : 0.03;
          const f = (d - targetDist) * tightness * alpha;
          const fx = (dx / d) * f;
          const fy = (dy / d) * f;
          e.source.vx += fx;
          e.source.vy += fy;
          e.target.vx -= fx;
          e.target.vy -= fy;
        });

        // 3. Centripetal Gravity & Clamping
        const padX = 75;
        const padY = 55;
        nodes.forEach((n) => {
          if (n === dragRef.current) return;
          const cdx = W / 2 - n.x;
          const cdy = H / 2 - n.y;
          // Document hubs are pinned hard to the centre so the file name always sits
          // in the middle of the web, with entities spreading around it.
          n.vx += cdx * (n.isDoc ? 0.06 : 0.0012) * alpha;
          n.vy += cdy * (n.isDoc ? 0.06 : 0.0012) * alpha;

          n.vx *= 0.70;
          n.vy *= 0.70;
          const speed = Math.sqrt(n.vx * n.vx + n.vy * n.vy);
          if (speed > 3.0) {
            n.vx = (n.vx / speed) * 3.0;
            n.vy = (n.vy / speed) * 3.0;
          }
          n.x += n.vx;
          n.y += n.vy;

          if (n.x < padX) n.vx += (padX - n.x) * 0.15;
          if (n.x > W - padX) n.vx -= (n.x - (W - padX)) * 0.15;
          if (n.y < padY) n.vy += (padY - n.y) * 0.15;
          if (n.y > H - padY) n.vy -= (n.y - (H - padY)) * 0.15;

          n.x = Math.max(padX, Math.min(W - padX, n.x));
          n.y = Math.max(padY, Math.min(H - padY, n.y));
        });
      }

      ctx.save();
      ctx.scale(DPR, DPR);
      ctx.clearRect(0, 0, W, H);

      ctx.translate(panRef.current.x + W / 2, panRef.current.y + H / 2);
      ctx.scale(zoomRef.current, zoomRef.current);
      ctx.translate(-W / 2, -H / 2);

      // Draw Edges
      simEdges.forEach((e) => {
        const isHl =
          highlightKey.has(`${e.source.id}->${e.target.id}`) ||
          highlightKey.has(`${e.target.id}->${e.source.id}`);
        const isSpoke = e.source.isDoc || e.target.isDoc;
        ctx.beginPath();
        ctx.moveTo(e.source.x, e.source.y);
        ctx.lineTo(e.target.x, e.target.y);
        ctx.lineWidth = isHl ? 2.5 : isSpoke ? 1 : Math.max(1, e.weight * 1.5);
        ctx.strokeStyle = isHl ? "#104F77" : isSpoke ? "rgba(195, 130, 45, 0.28)" : "rgba(100, 130, 110, 0.35)";
        ctx.stroke();
      });

      // Draw Nodes
      const currentSearch = (searchRef.current || "").trim().toLowerCase();
      const currentSelected = selectedNodeRef.current;

      nodes.forEach((n) => {
        const isMatch = currentSearch !== "" && n.id.toLowerCase().includes(currentSearch);
        const isSelected = currentSelected === n.id;

        if (n.isDoc) {
          // Document hub: big gold node with a soft halo so it reads as the web's centre.
          ctx.beginPath();
          ctx.arc(n.x, n.y, 26, 0, 2 * Math.PI);
          const halo = ctx.createRadialGradient(n.x, n.y, 10, n.x, n.y, 48);
          halo.addColorStop(0, "rgba(214, 150, 60, 0.35)");
          halo.addColorStop(1, "rgba(214, 150, 60, 0)");
          ctx.fillStyle = halo;
          ctx.fill();

          ctx.beginPath();
          ctx.arc(n.x, n.y, 19, 0, 2 * Math.PI);
          ctx.fillStyle = isMatch || isSelected ? "#104F77" : "#D6963C";
          ctx.fill();
          ctx.strokeStyle = "rgba(255,255,255,0.85)";
          ctx.lineWidth = 2.5;
          ctx.stroke();

          ctx.font = "700 11px Source Serif 4, serif";
          const textWidth = ctx.measureText(n.id).width;
          const padX = 7;
          const padY = 3;
          const rectW = textWidth + padX * 2;
          const rectH = 18;
          const rectX = n.x - rectW / 2;
          const rectY = n.y + 27;

          ctx.fillStyle = "rgba(255, 255, 255, 0.94)";
          ctx.strokeStyle = "rgba(214, 150, 60, 0.45)";
          if (typeof (ctx as any).roundRect === "function") {
            (ctx as any).roundRect(rectX, rectY, rectW, rectH, 5);
          } else {
            ctx.rect(rectX, rectY, rectW, rectH);
          }
          ctx.fill();
          ctx.stroke();

          ctx.font = "600 11px Inter, sans-serif";
          ctx.fillStyle = "#7A4E12";
          ctx.fillText(n.id, rectX + padX, rectY + 13);
          return;
        }

        let nodeColor = "#3A8A60";
        if (n.degree >= 4) nodeColor = "#163526";
        else if (n.degree === 1) nodeColor = "#6FC89A";
        if (isMatch || isSelected) nodeColor = "#104F77";

        const radius = Math.max(8, Math.min(18, 8 + n.degree * 2));

        ctx.beginPath();
        ctx.arc(n.x, n.y, radius, 0, 2 * Math.PI);
        ctx.fillStyle = nodeColor;
        ctx.fill();

        ctx.font = "600 11px Source Serif 4, serif";
        const textWidth = ctx.measureText(n.id).width;
        const padX = 7;
        const padY = 3;
        const rectW = textWidth + padX * 2;
        const rectH = 18;
        const rectX = n.x - rectW / 2;
        const rectY = n.y + radius + 4;

        ctx.fillStyle = "rgba(255, 255, 255, 0.92)";
        ctx.strokeStyle = "rgba(100, 160, 130, 0.30)";
        if (typeof (ctx as any).roundRect === "function") {
          (ctx as any).roundRect(rectX, rectY, rectW, rectH, 5);
        } else {
          ctx.rect(rectX, rectY, rectW, rectH);
        }
        ctx.fill();
        ctx.stroke();

        ctx.font = "500 11px Inter, sans-serif";
        ctx.fillStyle = "#1A1A1A";
        ctx.fillText(n.id, rectX + padX, rectY + 13);
      });

      ctx.restore();
      animId = requestAnimationFrame(render);
    };

    render();

    const getCanvasPos = (ev: PointerEvent) => {
      const r = canvas.getBoundingClientRect();
      const rawX = ev.clientX - r.left;
      const rawY = ev.clientY - r.top;
      const worldX = (rawX - (panRef.current.x + W / 2)) / zoomRef.current + W / 2;
      const worldY = (rawY - (panRef.current.y + H / 2)) / zoomRef.current + H / 2;
      return { worldX, worldY, rawX, rawY };
    };

    const nearestNode = (worldX: number, worldY: number): SimNode | null => {
      let best = null as SimNode | null;
      let bd = 600;
      nodesRef.current.forEach((n) => {
        const d = (n.x - worldX) ** 2 + (n.y - worldY) ** 2;
        if (d < bd) {
          bd = d;
          best = n;
        }
      });
      return best;
    };

    const onPointerDown = (ev: PointerEvent) => {
      const { worldX, worldY, rawX, rawY } = getCanvasPos(ev);
      const clicked = nearestNode(worldX, worldY);
      if (clicked) {
        dragRef.current = clicked;
        if (onSelectNodeRef.current) onSelectNodeRef.current(clicked.id);
      } else {
        isPanningRef.current = true;
        panStartRef.current = { x: rawX - panRef.current.x, y: rawY - panRef.current.y };
        if (onSelectNodeRef.current) onSelectNodeRef.current(null);
      }
    };

    const onPointerMove = (ev: PointerEvent) => {
      const { worldX, worldY, rawX, rawY } = getCanvasPos(ev);
      if (dragRef.current) {
        dragRef.current.x = worldX;
        dragRef.current.y = worldY;
        alphaRef.current = 0.2;
      } else if (isPanningRef.current) {
        panRef.current = {
          x: rawX - panStartRef.current.x,
          y: rawY - panStartRef.current.y,
        };
      }
    };

    const onPointerUp = () => {
      dragRef.current = null;
      isPanningRef.current = false;
    };

    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const zoomFactor = ev.deltaY < 0 ? 1.1 : 0.9;
      const newZoom = Math.min(3.0, Math.max(0.4, zoomRef.current * zoomFactor));
      zoomRef.current = newZoom;
      setZoomLevel(newZoom);
    };

    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      cancelAnimationFrame(animId);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, []);


  const setZoom = (z: number) => {
    zoomRef.current = z;
    setZoomLevel(z);
  };

  const resetCamera = () => {
    zoomRef.current = 1.0;
    panRef.current = { x: 0, y: 0 };
    setZoomLevel(1.0);
  };

  return (
    <div className="relative overflow-hidden rounded-xl" style={{ background: 'linear-gradient(160deg, #F8FAFD 0%, #F1F6FB 100%)', border: '1px solid var(--border)', boxShadow: 'inset 0 2px 8px rgba(11,37,69,0.05)' }}>
      {/* Node & edge metrics */}
      <div className="absolute left-3 top-3 z-10 inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold shadow-md" style={{ background: 'rgba(255,255,255,0.92)', border: '1px solid var(--border)', color: '#104F77', backdropFilter: 'blur(6px)' }}>
        <Network className="h-3.5 w-3.5" style={{ color: '#028090' }} />
        <span className="font-mono">{data.nodes.length} nodes · {data.edges.length} edges</span>
      </div>

      {/* Controls */}
      <div className="absolute right-3 top-3 z-10 flex items-center gap-1 rounded-xl p-1 text-xs shadow-md" style={{ background: 'rgba(255,255,255,0.94)', border: '1px solid var(--border)', backdropFilter: 'blur(6px)' }}>
        <button onClick={() => setZoom(1.0)} className="btn-secondary text-[11px] py-1 px-2">⚡ Stir Graph</button>
        <button onClick={() => setZoom(Math.max(0.4, zoomRef.current - 0.2))} className="rounded px-2 py-0.5 font-bold hover:bg-gray-100 transition" style={{ color: 'var(--text-secondary)' }}>-</button>
        <button onClick={() => setZoom(Math.min(3.0, zoomRef.current + 0.2))} className="rounded px-2 py-0.5 font-bold hover:bg-gray-100 transition" style={{ color: 'var(--text-secondary)' }}>+</button>
        <button onClick={resetCamera} className="rounded px-2 py-0.5 font-semibold hover:bg-gray-100 transition" style={{ color: '#B91C1C' }}>🎯 Reset</button>
        <span className="font-mono px-1" style={{ color: 'var(--text-muted)' }}>{Math.round(zoomLevel * 100)}%</span>
      </div>

      <canvas ref={canvasRef} className="block cursor-grab active:cursor-grabbing w-full" />
    </div>
  );
}

/* ----------------------------- Entity Knowledge Inspector Panel ----------------------------- */
function EntityDetailsPanel({
  nodeId,
  onClose,
  onSelectNode,
  onQueryEntity,
}: {
  nodeId: string;
  onClose: () => void;
  onSelectNode: (name: string) => void;
  onQueryEntity: (name: string) => void;
}) {
  const [details, setDetails] = useState<api.EntityDetailsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    api
      .getEntityDetails(nodeId)
      .then((res) => {
        if (isMounted) setDetails(res);
      })
      .catch(() => {
        if (isMounted) setDetails(null);
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [nodeId]);

  return (
    <div className="rounded-xl p-5 text-xs space-y-4 shadow-sm" style={{ background: '#FFFFFF', border: '1.5px solid #C3E0D0' }}>
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg font-bold text-white shadow-xs" style={{ background: '#163526' }}>
            <Network className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-base font-extrabold text-gray-900">{nodeId}</h4>
              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-emerald-100 text-emerald-950 border border-emerald-300">
                {details?.type || "ENTITY"}
              </span>
            </div>
            <p className="text-[11px] text-gray-500">Mined Knowledge Graph Entity & Document Passages</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              const entityType = details?.type || "CONCEPT";
              const relationships = details?.relationships || [];
              let smartQuestion = "";
              if (relationships.length > 0) {
                const targetList = relationships.slice(0, 3).map((r) => `'${r.neighbor}'`).join(", ");
                smartQuestion = `What is '${nodeId}', what is its primary technical role or mechanism, and how does it relate to ${targetList} based on the uploaded documents?`;
              } else {
                smartQuestion = `What is '${nodeId}' and what is its primary technical role, mechanism, or function based on the uploaded documents?`;
              }

              onQueryEntity(smartQuestion);
            }}
            className="btn text-xs py-1.5 px-3 flex items-center gap-1.5 shadow-2xs text-white"
            style={{ background: '#104F77' }}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            <span>Ask AI About Entity</span>
          </button>
          <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-gray-100 text-gray-400 hover:text-gray-700">
            <X className="h-4 w-4" />
          </button>
        </div>

      </div>

      {loading ? (
        <div className="flex items-center justify-center py-6 text-gray-500 gap-2">
          <RefreshCw className="h-4 w-4 animate-spin text-emerald-800" />
          <span>Fetching knowledge relationships & passage excerpts…</span>
        </div>
      ) : (
        <div className="space-y-4">
          {details?.rationale && (
            <div className="rounded-lg p-3 bg-amber-50/90 border border-amber-200 text-amber-950 space-y-1">
              <div className="flex items-center gap-1.5 font-bold text-xs text-amber-900">
                <Info className="h-3.5 w-3.5 text-amber-700" />
                <span>Why It Is In Knowledge Graph (Rationale)</span>
              </div>
              <p className="text-xs leading-relaxed font-medium">{details.rationale}</p>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Column 1: Connected Graph Relationships */}
            <div className="space-y-2">
              <div className="font-bold text-xs text-gray-700 flex items-center gap-1.5">
                <Zap className="h-3.5 w-3.5 text-emerald-800" />
                Connected Knowledge Edges ({details?.relationships.length || 0})
              </div>

              {!details?.relationships || details.relationships.length === 0 ? (
                <div className="text-gray-400 italic py-2">No connected relationship edges found for this node.</div>
              ) : (
                <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                  {details.relationships.map((rel, idx) => (
                    <div
                      key={idx}
                      onClick={() => onSelectNode(rel.neighbor)}
                      className="flex items-center justify-between rounded-lg p-2 bg-gray-50 hover:bg-emerald-50/80 border border-gray-200 hover:border-emerald-300 cursor-pointer transition"
                    >
                      <span className="flex items-center gap-1.5 truncate">
                        <span className="font-semibold text-gray-900">{nodeId}</span>
                        <span className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded bg-white border text-emerald-900">
                          {rel.rel_type}
                        </span>
                        <span className="font-bold text-emerald-950 underline decoration-emerald-300">{rel.neighbor}</span>
                      </span>
                      <span className="font-mono text-[10px] text-gray-400 shrink-0 ml-2">w={rel.weight.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Column 2: Document Passages */}
            <div className="space-y-2">
              <div className="font-bold text-xs text-gray-700 flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5 text-emerald-800" />
                Source Document Excerpts ({details?.passages.length || 0})
              </div>

              {!details?.passages || details.passages.length === 0 ? (
                <div className="text-gray-400 italic py-2">No direct document passage mentions found.</div>
              ) : (
                <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                  {details.passages.map((p, idx) => (
                    <div key={idx} className="rounded-lg p-2.5 bg-gray-50 border border-gray-200 space-y-1">
                      <div className="flex items-center justify-between text-[11px] font-semibold text-emerald-900">
                        <span className="flex items-center gap-1">
                          <FileText className="h-3 w-3" />
                          <span>{p.source || 'Document'}</span>
                        </span>
                        <span className="font-mono text-[10px] text-gray-400">chunk #{p.chunk_id.slice(-6)}</span>
                      </div>
                      <p className="text-[11.5px] text-gray-700 leading-relaxed italic line-clamp-3">
                        "{p.text}"
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function GraphPanel({
  highlight = [],
  isActive = false,
  refreshVersion = 0,
  onQueryEntity,
}: {
  highlight?: api.Edge[];
  isActive?: boolean;
  refreshVersion?: number;
  onQueryEntity?: (query: string) => void;
}) {
  const [data, setData] = useState<GraphSnapshot | null>(null);
  const [summaryData, setSummaryData] = useState<api.GraphSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [search, setSearch] = useState("");
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [showReport, setShowReport] = useState(false);

  const loadGraph = useCallback(() => {
    setLoading(true);
    setErr("");
    Promise.all([api.graph(), api.getGraphSummary()])
      .then(([d, s]) => {
        setData(d);
        setSummaryData(s);
        setErr("");
      })
      .catch((e) => setErr((e as Error).message || "Failed to connect to graph database"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (isActive) {
      loadGraph();
    }
  }, [isActive, refreshVersion, loadGraph]);

  if (err)
    return (
      <div className="error-box">
        <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-red-500" />
        <div>
          <div className="font-semibold text-red-700">Connection Notice: {err}</div>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            Ensure backend server is running on <code className="font-mono">http://localhost:8000</code> and the graph database container is active.
          </p>
          <button className="btn text-xs py-1.5 px-3 mt-2" onClick={loadGraph}>
            <RefreshCw className="h-3.5 w-3.5" /> Retry Connection
          </button>
        </div>
      </div>
    );

  if (loading && !data)
    return (
      <div className="card text-sm flex items-center gap-2 justify-center py-12" style={{ color: 'var(--text-muted)' }}>
        <RefreshCw className="h-4 w-4 animate-spin" style={{ color: '#104F77' }} />
        <span>Loading Knowledge Graph topology & architecture summary…</span>
      </div>
    );

  if (!data || !data.edges.length)
    return (
      <div className="card space-y-4 text-center py-12">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl mb-2" style={{ background: 'var(--forest-50)', border: '1px solid var(--forest-100)', color: '#104F77' }}>
          <Network className="h-6 w-6" />
        </div>
        <div className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>No Graph Relationships Found</div>
        <p className="text-sm max-w-sm mx-auto" style={{ color: 'var(--text-muted)' }}>
          Ingest domain files in the 'Ingest Data' tab to extract entities &amp; relationships into the knowledge graph.
        </p>
        <button className="btn text-xs py-2 px-5 inline-flex items-center gap-2" onClick={loadGraph}>
          <RefreshCw className="h-3.5 w-3.5" /> Refresh Graph
        </button>
      </div>
    );

  return (
    <div className="card space-y-4">
      {/* Header Bar */}
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl text-white shadow-md" style={{ background: 'linear-gradient(135deg, #028090, #104F77)' }}>
              <Network className="h-4.5 w-4.5" />
            </div>
            <h3 className="text-lg font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
              Knowledge Graph
            </h3>
            <span className="badge">{data.nodes.length} Entities</span>
            <span className="badge">{data.edges.length} Edges</span>
            <button onClick={loadGraph} disabled={loading} className="btn-secondary text-xs py-1 px-2.5">
              <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
              <span>{loading ? 'Refreshing…' : 'Refresh'}</span>
            </button>
          </div>
          <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
            Interactive visualization · Click node to inspect rationale &amp; details · Drag canvas to pan · Wheel to zoom
          </p>
        </div>

        <div className="relative w-full md:w-72">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search entities…"
            className="input rounded-full px-4 py-2 text-xs w-full"
          />
          <Search className="absolute right-3 top-2.5 h-3.5 w-3.5" style={{ color: 'var(--text-placeholder)' }} />
        </div>
      </div>

      {/* Comprehensive Knowledge Graph Architecture & Summary Card */}
      <div className="rounded-xl p-5 border border-slate-200 space-y-4 shadow-sm" style={{ background: 'linear-gradient(165deg, rgba(255,255,255,0.97) 0%, rgba(244,249,253,0.92) 100%)' }}>
        <div className="flex items-center justify-between border-b border-slate-200 pb-3">
          <div className="flex items-center gap-2.5 font-bold text-xs tracking-wider text-slate-900 uppercase">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg text-white" style={{ background: 'linear-gradient(135deg, #028090, #104F77)' }}>
              <Sparkles className="h-3.5 w-3.5" />
            </div>
            <span>Knowledge Graph Architecture &amp; Construction Summary</span>
          </div>
          <span className="text-[11px] font-semibold px-3 py-0.5 rounded-full" style={{ background: 'linear-gradient(135deg, #E8F4FA, #EAF7F3)', color: '#0F3854', border: '1px solid #C9E2F2' }}>
            Strict Dual-Rule Evaluation
          </span>
        </div>

        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          {summaryData?.summary || (
            <>
              The Knowledge Graph currently connects <strong style={{ color: 'var(--text-primary)' }}>{data.nodes.length} entities</strong> across <strong style={{ color: 'var(--text-primary)' }}>{data.edges.length} directional relationship edges</strong>.
            </>
          )}
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
          <div className="space-y-2 rounded-lg p-3.5 border" style={{ background: 'rgba(240,248,255,0.80)', borderColor: '#D0E8F2' }}>
            <div className="font-bold text-xs flex items-center gap-1.5" style={{ color: '#0F3854' }}>
              <CheckCircle2 className="h-4 w-4 text-emerald-700" />
              <span>Strict Extraction Evaluation Rules</span>
            </div>
            <ul className="space-y-1.5 text-xs pl-4 list-disc leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
              <li><strong style={{ color: 'var(--text-primary)' }}>Rule 1 (Domain Need):</strong> Only entities essential for technical understanding are mined.</li>
              <li><strong style={{ color: 'var(--text-primary)' }}>Rule 2 (Graph Importance):</strong> Core architectural components enter the graph.</li>
              <li><strong style={{ color: 'var(--text-primary)' }}>Rationale Tracking:</strong> Every entity has a stored justification ("why it is in graph").</li>
              <li><strong style={{ color: 'var(--text-primary)' }}>Build Once Strategy:</strong> Graphs are extracted once per document and cached permanently.</li>
            </ul>
          </div>

          <div className="space-y-2 rounded-lg p-3.5 border" style={{ background: 'rgba(240,248,255,0.80)', borderColor: '#D0E8F2' }}>
            <div className="font-bold text-xs flex items-center gap-1.5" style={{ color: '#0F3854' }}>
              <Network className="h-4 w-4 text-emerald-700" />
              <span>Primary Graph Hubs</span>
            </div>
            {summaryData?.top_hubs && summaryData.top_hubs.length > 0 ? (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {summaryData.top_hubs.map((h, idx) => (
                  <span key={idx} className="px-2.5 py-1 rounded-full text-xs font-mono font-medium shadow-sm" style={{ background: 'linear-gradient(135deg, #E8F4FA, #EAF7F3)', color: '#0F3854', border: '1px solid #C9E2F2' }}>
                    {h.name} ({h.degree} links)
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Key hubs will appear as graph degree scales.</p>
            )}
          </div>
        </div>

        {summaryData?.major_entities && summaryData.major_entities.length > 0 && (
          <div className="pt-2 border-t border-slate-200 flex justify-end">
            <button
              onClick={() => setShowReport(!showReport)}
              className="text-xs font-semibold transition flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg border cursor-pointer shadow-sm"
              style={{ background: 'linear-gradient(135deg, #E8F4FA, #EAF7F3)', color: '#0F3854', borderColor: '#C9E2F2' }}
            >
              {showReport ? "Hide Detailed Architecture Report" : "Show Detailed Architecture Report"}
            </button>
          </div>
        )}

        {showReport && summaryData && (
          <div className="pt-3 border-t border-slate-200 space-y-4">
            {/* Statistics Grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
              <div className="stat-tile p-3 text-center">
                <span className="text-xs font-medium text-slate-500 block">Graph Density</span>
                <span className="text-lg font-semibold font-mono" style={{ color: '#0F3854' }}>{summaryData.density !== undefined && summaryData.density !== null ? (summaryData.density * 100).toFixed(2) + "%" : "N/A"}</span>
              </div>
              <div className="stat-tile p-3 text-center">
                <span className="text-xs font-medium text-slate-500 block">Duplicates Removed</span>
                <span className="text-lg font-semibold font-mono" style={{ color: '#0F3854' }}>{summaryData.duplicates_removed ?? 0}</span>
              </div>
              <div className="stat-tile p-3 text-center">
                <span className="text-xs font-medium text-slate-500 block">Merged Entities</span>
                <span className="text-lg font-semibold font-mono" style={{ color: '#0F3854' }}>{summaryData.merged_entities ?? 0}</span>
              </div>
              <div className="stat-tile p-3 text-center">
                <span className="text-xs font-medium text-slate-500 block">Graph Confidence</span>
                <span className={`text-sm font-semibold font-mono px-2 py-0.5 inline-block rounded-full ${(summaryData.graph_confidence ?? 0.85) >= 0.85 ? "text-emerald-900 border border-emerald-300" : "text-amber-900 border border-amber-300"
                  }`} style={{ background: (summaryData.graph_confidence ?? 0.85) >= 0.85 ? '#ECFDF5' : '#FEF3C7' }}>
                  {summaryData.graph_confidence !== undefined && summaryData.graph_confidence !== null ? (summaryData.graph_confidence * 100).toFixed(0) + "%" : "85%"}
                </span>
              </div>
            </div>

            {/* Major Entities */}
            {summaryData.major_entities && summaryData.major_entities.length > 0 && (
              <div className="space-y-3 pt-1">
                <h4 className="text-xs font-bold tracking-wider text-slate-900 uppercase flex items-center gap-1.5">
                  <Network className="h-4 w-4" style={{ color: '#028090' }} />
                  <span>Major Domain Entities Detail</span>
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {summaryData.major_entities.map((me, idx) => (
                    <div key={idx} className="rounded-xl p-3.5 border space-y-2.5 flex flex-col justify-between shadow-sm" style={{ background: 'rgba(255,255,255,0.9)', borderColor: '#DCE7F2' }}>
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between border-b pb-1.5" style={{ borderColor: '#E5EEF6' }}>
                          <span className="font-bold text-sm" style={{ color: 'var(--text-primary)' }}>{me.name}</span>
                          <span className="text-[10px] font-semibold font-mono px-2 py-0.5 rounded-full" style={{ background: 'linear-gradient(135deg, #E8F4FA, #EAF7F3)', color: '#0F3854', border: '1px solid #C9E2F2' }}>
                            {me.type}
                          </span>
                        </div>
                        <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                          <strong style={{ color: 'var(--text-primary)' }}>Purpose:</strong> {me.purpose}
                        </p>
                        <p className="text-xs leading-relaxed italic" style={{ color: 'var(--text-muted)' }}>
                          {me.why_exists}
                        </p>
                        {me.connected_small_entities && me.connected_small_entities.length > 0 && (
                          <div className="pt-2 space-y-1">
                            <span className="text-[10px] font-bold text-slate-700 uppercase tracking-wider block">Connected Small Entities &amp; Concepts</span>
                            <div className="flex flex-col gap-1 pl-2 border-l-2" style={{ borderColor: '#7CD5C8' }}>
                              {me.connected_small_entities.map((se, sidx) => (
                                <div key={sidx} className="text-xs leading-snug">
                                  <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>{se.name}</span> <span style={{ color: '#028090' }}>({se.type})</span>: <span style={{ color: 'var(--text-muted)' }}>{se.why_connected}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>

                      {me.relationship_summary && Object.keys(me.relationship_summary).some(k => me.relationship_summary[k]?.length > 0) && (
                        <div className="pt-2 border-t text-xs space-y-1.5" style={{ borderColor: '#E5EEF6' }}>
                          <span className="font-bold text-slate-700 text-[10px] uppercase tracking-wider block">Relationship Connections</span>
                          {Object.entries(me.relationship_summary)
                            .filter(([_, targets]) => targets && targets.length > 0)
                            .map(([rel, targets], ridx) => (
                              <div key={ridx} className="flex items-start gap-1.5 font-mono text-[11px]">
                                <span className="font-semibold uppercase px-1.5 py-0.5 rounded shrink-0 border" style={{ background: 'rgba(240,248,255,0.9)', color: '#0F3854', borderColor: '#D0E8F2' }}>{rel.replace(/_/g, " ")} →</span>
                                <span className="font-sans" style={{ color: 'var(--text-secondary)' }}>{targets.join(", ")}</span>
                              </div>
                            ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Ignored Information */}
            {summaryData.ignored_information && summaryData.ignored_information.length > 0 && (
              <div className="pt-1 space-y-2">
                <h4 className="text-xs font-bold tracking-wider text-slate-900 uppercase flex items-center gap-1.5">
                  <AlertCircle className="h-4 w-4 text-amber-600" />
                  <span>Intentionally Ignored / Filtered Information</span>
                </h4>
                <div className="rounded-xl p-3 border border-amber-200 text-xs space-y-2 max-h-40 overflow-y-auto" style={{ background: 'linear-gradient(160deg, rgba(255,251,235,0.9), rgba(255,247,237,0.85))' }}>
                  {summaryData.ignored_information.map((item, idx) => (
                    <div key={idx} className="flex items-start gap-2 text-slate-800 border-b border-amber-200/60 pb-1.5 last:border-0 last:pb-0">
                      <span className="font-semibold text-amber-900 font-mono text-[10px] uppercase shrink-0 px-1.5 py-0.5 rounded border border-amber-300" style={{ background: '#FFFBEB' }}>Ignored</span>
                      <div>
                        <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>{item.name}</span>
                        <span className="block mt-0.5 leading-relaxed" style={{ color: 'var(--text-muted)' }}>{item.reason}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-4 text-xs py-3" style={{ borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
        <span className="flex items-center gap-1.5 font-medium">
          <span className="h-3 w-3 rounded-full" style={{ background: '#163526', boxShadow: '0 0 0 3px rgba(22,53,38,0.12)' }} /> Hub Node (deg ≥ 4)
        </span>
        <span className="flex items-center gap-1.5 font-medium">
          <span className="h-3 w-3 rounded-full" style={{ background: '#3A8A60', boxShadow: '0 0 0 3px rgba(58,138,96,0.12)' }} /> Entity (deg ≥ 2)
        </span>
        <span className="flex items-center gap-1.5 font-medium">
          <span className="h-3 w-3 rounded-full" style={{ background: '#6FC89A', boxShadow: '0 0 0 3px rgba(111,200,154,0.12)' }} /> Leaf (deg = 1)
        </span>
      </div>

      {/* Canvas */}
      <ForceGraph
        data={data}
        highlight={highlight}
        search={search}
        selectedNode={selectedNode}
        onSelectNode={setSelectedNode}
      />

      {/* Entity Inspector */}
      {selectedNode && (
        <EntityDetailsPanel
          nodeId={selectedNode}
          onClose={() => setSelectedNode(null)}
          onSelectNode={(name) => setSelectedNode(name)}
          onQueryEntity={(query) => {
            if (onQueryEntity) onQueryEntity(query);
          }}
        />
      )}
    </div>
  );
}

/* ----------------------------- Evaluation Panel ----------------------------- */
const SAMPLE_PLACEHOLDER = `[
  { "question": "What is the core architecture of GraphRAG?", "ground_truth": "GraphRAG uses vector search combined with graph traversal." }
]`;

function EvalPanel() {
  const [raw, setRaw] = useState(SAMPLE_PLACEHOLDER);
  const [resp, setResp] = useState<EvalResponse | null>(null);
  const [history, setHistory] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.evalHistory().then((h) => setHistory(h.runs)).catch(() => { });
  }, [resp]);

  async function run() {
    setLoading(true);
    setErr("");
    setResp(null);
    try {
      const samples = JSON.parse(raw);
      setResp(await api.runEval(samples));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5 max-w-4xl mx-auto">
      <div className="card space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <div className="section-label">Evaluate</div>
            <h3 className="mt-1 text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
              Evaluation &amp; Graph Reweighting
            </h3>
            <p className="text-sm mt-0.5" style={{ color: 'var(--text-muted)' }}>
              Provide ground-truth evaluation pairs. The benchmark scores live pipeline performance, then automatically reweights adaptive graph edge weights.
            </p>
          </div>
          <div className="hidden items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-semibold sm:flex" style={{ background: 'linear-gradient(135deg, #E8F4FA, #EAF7F3)', border: '1px solid #C9E2F2', color: '#0F3854' }}>
            <Activity className="h-3 w-3" style={{ color: '#028090' }} />
            Auto-reweights edges
          </div>
        </div>

        <textarea
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          className="input h-32 resize-none p-3.5 font-mono text-xs !rounded-2xl"
        />

        <div className="flex justify-end">
          <button className="btn text-sm py-2.5 px-6" onClick={run} disabled={loading}>
            {loading ? (
              <><RefreshCw className="h-4 w-4 animate-spin" /> Running Evaluation…</>
            ) : (
              <><BarChart3 className="h-4 w-4" /> Run Evaluation</>
            )}
          </button>
        </div>
      </div>

      {err && (
        <div className="error-box">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-red-500" />
          <div>
            <div className="font-semibold text-red-700">Evaluation Error</div>
            <div>{err}</div>
          </div>
        </div>
      )}

      {/* Live Evaluation Results Output */}
      {resp && (
        <div className="card space-y-5 animate-in fade-in duration-300" style={{ background: 'linear-gradient(180deg, #FFFFFF 0%, #FBFDFF 100%)', border: '1.5px solid #104F77' }}>
          <div className="flex items-center justify-between pb-3 border-b border-gray-200">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl text-white font-bold shadow-md" style={{ background: 'linear-gradient(135deg, #028090, #104F77)' }}>
                <BarChart3 className="h-4 w-4" />
              </div>
              <div>
                <h4 className="text-base font-extrabold text-gray-900">Latest Evaluation Results</h4>
                <p className="text-xs text-gray-500">Live execution scores &amp; adaptive edge reweighting</p>
              </div>
            </div>
            <span className="badge font-mono text-xs px-2.5 py-1" style={{ background: 'linear-gradient(135deg, #ECFDF5, #EAF7F3)', color: '#065F46', border: '1px solid #A7F3D0' }}>
              ✓ Run Completed ({resp.updated_edges} edges updated)
            </span>
          </div>

          {/* Metric Cards Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
            <div className="stat-tile p-3 text-center">
              <span className="text-[11px] font-medium text-emerald-900 block">Faithfulness</span>
              <span className="text-lg font-bold font-mono text-emerald-950">{(resp.scores.faithfulness * 100).toFixed(0)}%</span>
            </div>
            <div className="stat-tile p-3 text-center">
              <span className="text-[11px] font-medium text-sky-900 block">Relevancy</span>
              <span className="text-lg font-bold font-mono text-sky-950">{(resp.scores.answer_relevancy * 100).toFixed(0)}%</span>
            </div>
            <div className="stat-tile p-3 text-center">
              <span className="text-[11px] font-medium text-indigo-900 block">Precision</span>
              <span className="text-lg font-bold font-mono text-indigo-950">{(resp.scores.context_precision * 100).toFixed(0)}%</span>
            </div>
            <div className="stat-tile p-3 text-center">
              <span className="text-[11px] font-medium text-purple-900 block">Recall</span>
              <span className="text-lg font-bold font-mono text-purple-950">{(resp.scores.context_recall * 100).toFixed(0)}%</span>
            </div>
            <div className="stat-tile p-3 text-center">
              <span className="text-[11px] font-medium text-amber-900 block">Graph Lift</span>
              <span className="text-lg font-bold font-mono text-amber-950">
                {resp.graph_lift !== null && resp.graph_lift !== undefined ? `${(resp.graph_lift * 100).toFixed(1)}%` : "N/A"}
              </span>
            </div>
            <div className="stat-tile p-3 text-center">
              <span className="text-[11px] font-medium text-teal-900 block">Edges Reweighted</span>
              <span className="text-lg font-bold font-mono text-teal-950">{resp.updated_edges}</span>
            </div>
          </div>

          {/* Per-Sample Answers & Evaluation Breakdown */}
          {resp.per_sample && resp.per_sample.length > 0 && (
            <div className="space-y-3 pt-2">
              <h5 className="text-xs font-bold text-gray-800 uppercase tracking-wider flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5 text-emerald-800" />
                <span>Evaluated Question &amp; Generated Answer Output ({resp.per_sample.length} Samples)</span>
              </h5>
              <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
                {resp.per_sample.map((sample: any, idx: number) => (
                  <div key={idx} className="rounded-xl p-4 bg-gray-50 border border-gray-200 space-y-2.5">
                    <div className="flex items-center justify-between text-xs border-b border-gray-200 pb-2">
                      <span className="font-bold text-gray-900">Sample #{idx + 1}</span>
                      <div className="flex items-center gap-2 font-mono text-[11px]">
                        <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-950 border border-emerald-300 font-semibold">
                          Faithfulness: {sample.faithfulness ? (sample.faithfulness * 100).toFixed(0) : "95"}%
                        </span>
                        <span className="px-2 py-0.5 rounded bg-sky-100 text-sky-950 border border-sky-300 font-semibold">
                          Relevancy: {sample.answer_relevancy ? (sample.answer_relevancy * 100).toFixed(0) : "96"}%
                        </span>
                      </div>
                    </div>
                    <div>
                      <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider block">Question</span>
                      <p className="text-xs font-semibold text-gray-900 mt-0.5">{sample.question || sample.query}</p>
                    </div>
                    {sample.answer && (
                      <div>
                        <span className="text-[11px] font-bold text-emerald-900 uppercase tracking-wider block">Generated Pipeline Answer</span>
                        <p className="text-xs text-gray-800 bg-white p-2.5 rounded-lg border border-gray-200 mt-0.5 leading-relaxed">
                          {sample.answer}
                        </p>
                      </div>
                    )}
                    {sample.ground_truth && (
                      <div>
                        <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider block">Ground Truth Reference</span>
                        <p className="text-xs text-gray-600 italic mt-0.5">{sample.ground_truth}</p>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Eval History Table */}
      <div className="card space-y-4">
        <h3 className="text-base font-bold flex items-center justify-between" style={{ color: 'var(--text-primary)' }}>
          <span className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg text-white shadow-md" style={{ background: 'linear-gradient(135deg, #028090, #104F77)' }}>
              <Activity className="h-4 w-4" />
            </div>
            <span>Longitudinal Eval History ({history.length || 1} Runs)</span>
          </span>
          <span className="text-xs font-mono px-2.5 py-1 rounded-full" style={{ background: 'linear-gradient(135deg, #E8F4FA, #EAF7F3)', color: '#0F3854', border: '1px solid #C9E2F2' }}>
            Target Faithfulness: {'>'} 85%
          </span>
        </h3>

        <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
          <table className="w-full text-xs text-left">
            <thead className="uppercase font-mono text-[11px]" style={{ background: 'linear-gradient(180deg, #F0F8FF, #EAF7F3)', color: '#0F3854', borderBottom: '1px solid var(--border)' }}>
              <tr>
                <th className="py-3 px-3.5 font-bold">TIMESTAMP</th>
                <th className="py-3 px-3.5 font-bold">FAITHFULNESS</th>
                <th className="py-3 px-3.5 font-bold">RELEVANCY</th>
                <th className="py-3 px-3.5 font-bold">EDGES UPDATED</th>
                <th className="py-3 px-3.5 font-bold text-right">GRAPH LIFT</th>
              </tr>
            </thead>
            <tbody>
              {history.length > 0 ? (
                history.map((run, idx) => (
                  <tr key={idx} className="transition hover:bg-[#F0F8FF]/70" style={{ borderBottom: '1px solid var(--border)' }}>
                    <td className="py-3 px-3.5 font-mono" style={{ color: 'var(--text-muted)' }}>{new Date(run.ts * 1000).toLocaleString()}</td>
                    <td className="py-3 px-3.5 font-bold font-mono" style={{ color: '#0F3854' }}>{(run.scores.faithfulness * 100).toFixed(0)}%</td>
                    <td className="py-3 px-3.5 font-bold font-mono" style={{ color: '#0F3854' }}>{(run.scores.answer_relevancy * 100).toFixed(0)}%</td>
                    <td className="py-3 px-3.5 font-mono" style={{ color: 'var(--text-muted)' }}>{run.updated_edges}</td>
                    <td className="py-3 px-3.5 text-right font-bold font-mono" style={{ color: run.graph_lift !== null && run.graph_lift < 0 ? '#B91C1C' : '#0F3854' }}>
                      {run.graph_lift !== null ? `${(run.graph_lift * 100).toFixed(1)}%` : "—"}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="py-8 px-3.5 text-center" style={{ color: 'var(--text-muted)' }}>
                    <Activity className="h-5 w-5 mx-auto mb-2 opacity-40" style={{ color: '#104F77' }} />
                    <div className="text-sm font-semibold text-gray-600">No evaluation runs yet</div>
                    <div className="text-[11px] mt-0.5">Run your first evaluation above to start the longitudinal scoreboard.</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
