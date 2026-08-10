"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Network,
  MessageSquareText,
  UploadCloud,
  BarChart3,
  Sparkles,
  ShieldCheck,
  Zap,
  Database,
  Cpu,
  ArrowRight,
  Check,
  Layers,
  Search,
  Globe,
  Gauge,
  Star,
  KeyRound,
  GitBranch,
  Sliders,
  Target,
  BadgeCheck,
  Menu,
  X,
  CheckCircle2,
  Workflow,
  ChevronDown,
  FileText,
  Lock,
  TrendingUp,
  Brain,
  Fingerprint,
  LineChart,
  Rocket,
  Clock,
  Users2,
} from "lucide-react";

const NAV_LINKS = [
  { href: "#features", label: "Features" },
  { href: "#how-it-works", label: "How It Works" },
  { href: "#product", label: "Product" },
  { href: "#pricing", label: "Pricing" },
  { href: "#faq", label: "FAQ" },
];

const FEATURES = [
  {
    icon: MessageSquareText,
    title: "Hybrid Multi-Hop Retrieval",
    desc: "Blend semantic vector search with knowledge-graph traversal so answers surface hidden, cross-document connections — not just keyword matches.",
    tag: "GraphRAG",
  },
  {
    icon: Network,
    title: "Live Knowledge Graph",
    desc: "Explore entities, relationships, and directional edges in a real-time physics visualizer. Inspect rationale for every node right from the canvas.",
    tag: "Visualizer",
  },
  {
    icon: UploadCloud,
    title: "Instant Document Ingestion",
    desc: "Drop in PDF, DOCX, TXT, or Markdown and watch the pipeline chunk, embed, and build graph entities automatically — no manual setup.",
    tag: "Pipeline",
  },
  {
    icon: LineChart,
    title: "Evaluation & Graph Reweighting",
    desc: "Score faithfulness, relevancy, precision, and recall with a golden-set pipeline, then let feedback automatically reweight graph edges.",
    tag: "Self-Improving",
  },
  {
    icon: Fingerprint,
    title: "Enterprise-Grade Security",
    desc: "Email + OTP verification, Google OAuth, isolated multi-tenant sessions, and auto-expiring guest sandboxes keep your data private.",
    tag: "Secure",
  },
  {
    icon: Cpu,
    title: "Precision Cross-Encoder Re-ranking",
    desc: "A two-stage re-ranking pass over vector and graph results returns precise, citeable answers in milliseconds — never raw cosine similarity alone.",
    tag: "2-Stage",
  },
];

const STEPS = [
  {
    step: "01",
    icon: UploadCloud,
    title: "Upload your knowledge",
    desc: "Ingest company manuals, research papers, or policy documents. The system chunks, embeds, and maps them into a knowledge graph.",
  },
  {
    step: "02",
    icon: MessageSquareText,
    title: "Ask anything",
    desc: "Ask natural-language questions. Hybrid retrieval pulls vector matches and expands them across multi-hop graph relationships.",
  },
  {
    step: "03",
    icon: TrendingUp,
    title: "Measure & improve",
    desc: "Golden-set benchmarks score your answer quality and reweight graph edges so the system gets measurably smarter on every run.",
  },
];

const PRICING = [
  {
    name: "Starter",
    price: "$0",
    period: "Forever",
    desc: "For exploring the GraphRAG experience.",
    features: [
      "3 free trial questions for guests",
      "3 document uploads per day",
      "5 questions per document per day",
      "AI-powered document Q&A",
      "Vector + graph retrieval",
    ],
    cta: "Start Free",
    featured: false,
  },
  {
    name: "Pro",
    price: "$29",
    period: "/month",
    desc: "For individuals & small teams shipping daily.",
    features: [
      "Everything in Starter",
      "Unlimited uploads & questions",
      "Saved conversation threads",
      "Full Knowledge Graph visualizer",
      "Evaluation dashboard",
      "Adaptive edge reweighting",
      "Email & priority support",
    ],
    cta: "Start Free Trial",
    featured: true,
  },
  {
    name: "Enterprise",
    price: "Custom",
    period: "",
    desc: "For organizations with scale & compliance needs.",
    features: [
      "Everything in Pro",
      "SSO / SAML & audit logs",
      "Dedicated infra & support",
      "Multi-tenant isolation",
      "SLA-backed uptime",
      "Custom integrations",
    ],
    cta: "Talk to Sales",
    featured: false,
  },
];

const FAQS = [
  {
    q: "What does the free trial include?",
    a: "Every guest gets 3 free questions with full access to chat, document upload, the knowledge graph visualizer, and evaluation features — no credit card required. After the trial, sign in for a free account with daily limits, or upgrade to Pro for unlimited use.",
  },
  {
    q: "Do I need a credit card to start?",
    a: "No. Start for Free requires only your guest session. We will never charge you unless you explicitly choose a paid plan after your trial.",
  },
  {
    q: "How is my data kept private?",
    a: "Each guest session runs in an isolated sandbox with auto-expiring vectors and graph data. Signed-in users get multi-tenant thread isolation between accounts. Documents, embeddings, and knowledge graphs are scoped to your session only.",
  },
  {
    q: "Which document formats are supported?",
    a: "Currently PDF, DOCX, TXT, and Markdown. We extract full text, chunk deeply with overlap, and build entity-relationship graphs tuned to each document's domain.",
  },
  {
    q: "What makes this different from standard RAG?",
    a: "Standard RAG retrieves with vector similarity alone. GraphRAG also walks a knowledge graph with multi-hop connections and re-ranks results with a cross-encoder, concluding with self-optimizing edge weights validated by golden-set metrics.",
  },
  {
    q: "Can I cancel my trial anytime?",
    a: "Yes. There is nothing to cancel on the free trial — it simply ends after your 3 questions. If you begin a paid plan later you can downgrade or stop any time.",
  },
];

export default function LandingPage() {
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [faqOpen, setFaqOpen] = useState<number | null>(0);
  const [startedHint, setStartedHint] = useState("");
  const [scrollPct, setScrollPct] = useState(0);

  useEffect(() => {
    const onScroll = () => {
      const el = document.documentElement;
      const max = el.scrollHeight - el.clientHeight;
      setScrollPct(max > 0 ? Math.min(1, el.scrollTop / max) : 0);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  function startFree() {
    setStartedHint(
      "Your 3 free trial questions are active — directing you to the workspace…"
    );
    setTimeout(() => router.push("/dashboard"), 350);
  }

  function goToPro() {
    window.open("https://buy.stripe.com/test_5kQ14pbm8fQjfbrdpb1Jm02", "_blank");
  }

  return (
    <div className="min-h-screen antialiased overflow-x-hidden" style={{ color: "var(--text-primary)" }}>

      {/* ── Premium Scroll Progress ── */}
      <div className="pointer-events-none fixed inset-x-0 top-0 z-[60] h-[3px]">
        <div className="scroll-progress" style={{ width: `${scrollPct * 100}%` }} />
      </div>

      {/* ── NAV (Light Premium Glass) ── */}
      <header className="sticky top-0 z-50 backdrop-blur-md"
        style={{ background: "rgba(255, 255, 255, 0.82)", boxShadow: "0 1px 12px rgba(11, 37, 69, 0.08)", borderBottom: "1px solid rgba(210, 226, 240, 0.65)" }}>
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-3">
          <Link href="/" className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl text-white shadow-md"
              style={{ background: "linear-gradient(135deg,#028090 0%,#104F77 100%)", boxShadow: "0 4px 14px rgba(16,79,119,0.30)" }}>
              <Network className="h-5 w-5" />
            </div>
            <div className="leading-tight">
              <div className="text-[15px] font-extrabold tracking-tight" style={{ color: "var(--text-primary)" }}>
                NeuroGraph<span style={{ color: "#028090" }}>RAG</span>
              </div>
              <div className="hidden text-[10px] font-medium sm:block" style={{ color: "var(--text-muted)" }}>
                Self-Improving Enterprise Intelligence
              </div>
            </div>
          </Link>

          <nav className="hidden items-center gap-1 lg:flex">
            {NAV_LINKS.map((l) => (
              <a key={l.href} href={l.href}
                className="group relative rounded-lg px-3.5 py-2 text-sm font-medium transition-all duration-200 hover:bg-white/70 hover:shadow-sm"
                style={{ color: "var(--text-secondary)" }}>
                {l.label}
                <span className="absolute bottom-0.5 left-1/2 h-[3px] w-0 -translate-x-1/2 rounded-full transition-all duration-300 group-hover:w-7"
                  style={{ background: "linear-gradient(90deg,#028090,#104F77)" }} />
              </a>
            ))}
          </nav>

          <div className="hidden items-center gap-3 lg:flex">
            <Link href="/login"
              className="rounded-xl px-4 py-2 text-sm font-semibold transition-colors hover:text-[#0F3854]"
              style={{ color: "var(--text-secondary)" }}>
              Log In
            </Link>
            <button
              onClick={startFree}
              className="btn-shine inline-flex items-center gap-1.5 rounded-xl px-5 py-2 text-sm font-bold text-white transition-all hover:-translate-y-px"
              style={{ background: "linear-gradient(135deg,#028090 0%,#0F4C81 100%)", boxShadow: "0 6px 18px rgba(2,128,144,0.25)" }}>
              Start Free
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>

          <button className="rounded-lg p-2 lg:hidden" onClick={() => setMenuOpen((v) => !v)} aria-label="Toggle menu">
            {menuOpen ? <X className="h-5 w-5" style={{ color: "var(--text-primary)" }} /> : <Menu className="h-5 w-5" style={{ color: "var(--text-primary)" }} />}
          </button>
        </div>

        {menuOpen && (
          <div className="border-t lg:hidden" style={{ borderColor: "var(--border)" }}>
            <div className="mx-auto max-w-7xl space-y-1 px-5 py-4">
              {NAV_LINKS.map((l) => (
                <a key={l.href} href={l.href} onClick={() => setMenuOpen(false)}
                  className="block rounded-lg px-3 py-2 text-sm font-medium"
                  style={{ color: "var(--text-secondary)" }}>
                  {l.label}
                </a>
              ))}
              <div className="flex items-center gap-2 pt-2">
                <Link href="/login" onClick={() => setMenuOpen(false)}
                  className="flex-1 justify-center rounded-xl border px-4 py-2.5 text-sm font-semibold"
                  style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
                  Log In
                </Link>
                <button onClick={() => { setMenuOpen(false); startFree(); }}
                  className="flex-1 justify-center rounded-xl px-4 py-2.5 text-sm font-bold text-white"
                  style={{ background: "linear-gradient(135deg,#028090,#0F4C81)" }}>
                  Start Free
                </button>
              </div>
            </div>
          </div>
        )}
      </header>

      {startedHint && (
        <div className="fixed inset-x-0 top-20 z-50 mx-auto flex max-w-md items-center gap-2 rounded-2xl border bg-white px-4 py-3 text-sm font-semibold shadow-2xl sm:text-base"
          style={{ borderColor: "#A7D7C5", color: "var(--text-primary)" }}>
          <Sparkles className="h-5 w-5" style={{ color: "#028090" }} />
          {startedHint}
        </div>
      )}

      {/* ── HERO ── */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0"
          style={{ backgroundImage: "url('/custom-bg.jpg')", backgroundSize: "cover", backgroundPosition: "center", opacity: 0.34 }} />
        <div className="pointer-events-none absolute inset-0"
          style={{ background: "linear-gradient(180deg, rgba(235,244,251,0.92) 0%, rgba(240,248,255,0.92) 55%, #EBF4FB 100%)" }} />

        {/* Aurora drift layers */}
        <div className="aurora aurora-a" style={{ width: 520, height: 520, left: "-12%", top: "-10%", background: "radial-gradient(circle at 40% 40%, rgba(2,128,144,0.28), transparent 70%)" }} />
        <div className="aurora aurora-b" style={{ width: 640, height: 640, right: "-16%", top: "6%", background: "radial-gradient(circle at 60% 40%, rgba(16,79,119,0.26), transparent 70%)" }} />
        <div className="aurora aurora-a" style={{ width: 420, height: 420, left: "30%", bottom: "-18%", background: "radial-gradient(circle at 50% 50%, rgba(78,205,196,0.18), transparent 70%)" }} />

        <div className="relative mx-auto max-w-6xl px-5 pb-20 pt-16 lg:pt-24">
          <div className="mx-auto max-w-3xl text-center">
            <Reveal>
              <div className="kicker">
                <Sparkles className="h-3.5 w-3.5" style={{ color: "#028090" }} />
                Enterprise-grade GraphRAG · No credit card required
              </div>
            </Reveal>

            <Reveal delay={90}>
              <h1 className="text-5xl font-extrabold leading-[1.06] tracking-tight sm:text-6xl lg:text-7xl" style={{ color: "#0B2545" }}>
                Your documents, one
                <span className="mx-2 gradient-text">living brain</span>
              </h1>
            </Reveal>

            <Reveal delay={180}>
              <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed md:text-xl" style={{ color: "#334155" }}>
                Upload your knowledge, ask anything, and get precise, cited answers.
                Our hybrid vector + knowledge-graph pipeline re-ranks every result and{" "}
                <span className="font-bold" style={{ color: "#0F3854" }}>gets measurably smarter</span> with each question.
              </p>
            </Reveal>

            <Reveal delay={270}>
              <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
                <button
                  onClick={startFree}
                  className="group btn-shine inline-flex w-full items-center justify-center gap-2 rounded-2xl px-9 py-4 text-base font-bold text-white transition-all hover:-translate-y-0.5 sm:w-auto"
                  style={{ background: "linear-gradient(135deg,#028090 0%,#0F4C81 100%)", boxShadow: "0 16px 38px rgba(2,128,144,0.32), inset 0 1px 0 rgba(255,255,255,0.16)" }}>
                  <Rocket className="h-5 w-5" />
                  Start Free — 3 Questions
                  <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
                </button>
                <a href="#product"
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border bg-white/85 px-9 py-4 text-base font-bold backdrop-blur-sm transition-all hover:-translate-y-0.5 sm:w-auto"
                  style={{ borderColor: "rgba(16,79,119,0.18)", color: "#104F77" }}>
                  See How It Works
                </a>
              </div>
            </Reveal>

            <Reveal delay={360}>
              <div className="mt-7 flex flex-wrap items-center justify-center gap-x-7 gap-y-2.5 text-sm" style={{ color: "#64748B" }}>
                <span className="flex items-center gap-1.5"><Lock className="h-4 w-4 text-[#028090]" /> No credit card</span>
                <span className="h-3 w-px bg-[#CDE0F1]" />
                <span className="flex items-center gap-1.5"><Clock className="h-4 w-4 text-[#028090]" /> Works instantly</span>
                <span className="h-3 w-px bg-[#CDE0F1]" />
                <span className="flex items-center gap-1.5"><ShieldCheck className="h-4 w-4 text-[#028090]" /> Enterprise-grade security</span>
              </div>
            </Reveal>
          </div>

          <Reveal delay={460} className="relative mx-auto mt-16 max-w-4xl">
            <div className="absolute -inset-6 rounded-[2.5rem] opacity-50 blur-3xl"
              style={{ background: "linear-gradient(135deg,#A7D8CE,#BFE5EE,#9FD0E8)" }} />
            <div className="gradient-ring shadow-2xl" style={{ boxShadow: "0 40px 80px -20px rgba(11,37,69,0.40)" }}>
              <div className="rounded-[calc(1.6rem-1.5px)] bg-gradient-to-b from-white via-white/98 to-[#F5FAFD]">
                <PipelinePreview />
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── LOGO STRIP ── */}
      <Reveal>
        <section className="border-y bg-white/70 py-10 backdrop-blur-sm" style={{ borderColor: "rgba(16,79,119,0.10)" }}>
          <div className="mx-auto max-w-7xl px-5">
            <p className="text-center text-[11px] font-semibold uppercase tracking-[0.28em] text-gray-400">
              One engine. Every retrieval technique. No lock-in.
            </p>
            <div className="mt-6 flex flex-wrap items-center justify-center gap-y-5">
              {[
                { icon: Brain, t: "Adaptive Re-ranking" },
                { icon: Database, t: "Vector Search" },
                { icon: GitBranch, t: "Knowledge Graph" },
                { icon: Globe, t: "Multi-Hop Retrieval" },
                { icon: Layers, t: "Self-Improving" },
              ].map(({ icon: Icon, t }) => (
                <span key={t} className="flex items-center gap-2 pl-8 pr-8 text-sm font-bold sm:border-r sm:border-[#CDE0F1] last:sm:border-r-0" style={{ color: "#5B7595" }}>
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white shadow-sm ring-1 ring-[#E0ECF5]">
                    <Icon className="h-4 w-4" style={{ color: "#028090" }} />
                  </span>
                  {t}
                </span>
              ))}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ── FEATURES ── */}
      <section id="features" className="mx-auto max-w-7xl px-5 py-20 lg:py-28">
        <Reveal>
          <div className="mx-auto max-w-2xl text-center">
            <div className="kicker">
              <Zap className="h-3.5 w-3.5" style={{ color: "#028090" }} /> Why teams choose GraphRAG
            </div>
            <h2 className="mt-5 text-3xl font-extrabold tracking-tight sm:text-5xl" style={{ color: "#0B2545" }}>
              Retrieval that actually thinks
              <span className="block gradient-text mt-1">in relationships</span>
            </h2>
            <p className="mt-4 text-lg" style={{ color: "#64748B" }}>
              Vector search finds similar text. We also walk the graph between entities —
              then measure and tighten the web with every interaction.
            </p>
          </div>
        </Reveal>

        <div className="mt-16 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => {
            const Icon = f.icon;
            return (
              <Reveal key={f.title} delay={i * 90} className="h-full">
                <div
                  className="group relative card !rounded-2xl h-full p-7 transition-all duration-300 hover:-translate-y-1.5 hover:border-[#B9DAE8]">
                  <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full opacity-0 blur-2xl transition-opacity duration-300 group-hover:opacity-60"
                    style={{ background: "radial-gradient(closest-side, rgba(2,128,144,0.32), transparent)" }} />
                  <div className="flex items-center justify-between">
                    <div
                      className="flex h-12 w-12 items-center justify-center rounded-xl text-white shadow-sm transition-all duration-300 group-hover:scale-110 group-hover:shadow-lg"
                      style={{ background: "linear-gradient(135deg,#0F3854 0%,#104F77 60%,#028090 100%)", boxShadow: "0 6px 16px rgba(16,79,119,0.24)" }}>
                      <Icon className="h-6 w-6" />
                    </div>
                    <span className="rounded-full px-3 py-1 text-[11px] font-bold transition-colors" style={{ background: "rgba(16,79,119,0.08)", color: "#0F3854" }}>
                      {f.tag}
                    </span>
                  </div>
                  <h3 className="mt-5 flex items-center gap-2 text-lg font-bold" style={{ color: "#0B2545" }}>
                    {f.title}
                    <ArrowRight className="h-4 w-4 -translate-x-1 opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:opacity-100" style={{ color: "#028090" }} />
                  </h3>
                  <p className="mt-2.5 text-sm leading-relaxed" style={{ color: "#64748B" }}>{f.desc}</p>
                </div>
              </Reveal>
            );
          })}
        </div>
      </section>

      {/* ── HOW IT WORKS ── */}
      <section id="how-it-works" className="border-y py-20 lg:py-28"
        style={{ borderColor: "rgba(16,79,119,0.10)", background: "rgba(255,255,255,0.60)" }}>
        <div className="mx-auto max-w-7xl px-5">
          <Reveal>
            <div className="mx-auto max-w-2xl text-center">
              <div className="kicker">
                <Workflow className="h-3.5 w-3.5" style={{ color: "#028090" }} /> How it works
              </div>
              <h2 className="mt-5 text-3xl font-extrabold tracking-tight sm:text-5xl" style={{ color: "#0B2545" }}>
                From PDF to cited answers in three steps
              </h2>
            </div>
          </Reveal>

          <div className="relative mt-16 grid grid-cols-1 gap-6 md:grid-cols-3">
            <div className="pointer-events-none absolute left-[15%] right-[15%] top-7 hidden md:block">
              <div className="h-px bg-gradient-to-r from-[#104F77]/15 via-[#028090]/40 to-[#104F77]/15" />
            </div>
            {STEPS.map((s, i) => {
              const Icon = s.icon;
              return (
                <Reveal key={s.step} delay={i * 110} className="h-full">
                  <div className="group relative h-full overflow-hidden rounded-2xl border bg-white/90 p-7 backdrop-blur-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
                    style={{ borderColor: "rgba(16,79,119,0.12)" }}>
                    <span className="pointer-events-none absolute right-5 top-3 select-none text-6xl font-black tracking-tighter transition-colors duration-300 group-hover:text-[#E5F1F8]"
                      style={{ color: "rgba(16,79,119,0.07)" }}>{s.step}</span>
                    <div
                      className="relative -mt-1 flex h-12 w-12 items-center justify-center rounded-full text-white shadow-lg transition-transform duration-300 group-hover:scale-110"
                      style={{ background: "linear-gradient(135deg,#104F77,#028090)", boxShadow: "0 8px 20px rgba(16,79,119,0.30)" }}>
                      <Icon className="h-6 w-6" />
                    </div>
                    <span className="mt-4 block text-xs font-black tracking-[0.25em]" style={{ color: "#028090" }}>{s.step}</span>
                    <h3 className="mt-1.5 text-lg font-bold" style={{ color: "#0B2545" }}>{s.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed" style={{ color: "#64748B" }}>{s.desc}</p>
                  </div>
                </Reveal>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── PRODUCT / PIPELINE ── */}
      <section id="product" className="mx-auto max-w-7xl px-5 py-20 lg:py-28">
        <div className="grid grid-cols-1 items-center gap-14 lg:grid-cols-2">
          <Reveal direction="left">
            <div>
              <div className="kicker">
                <Database className="h-3.5 w-3.5" style={{ color: "#028090" }} /> The full pipeline
              </div>
              <h2 className="mt-5 text-3xl font-extrabold tracking-tight sm:text-5xl" style={{ color: "#0B2545" }}>
                Retrieval is a graph web,
                <span className="block gradient-text mt-1">not a flat list</span>
              </h2>
              <p className="mt-5 text-lg leading-relaxed" style={{ color: "#475569" }}>
                Every query runs a counterfactual pipeline — pure vector search against adaptive graph
                expansion — and shows you which path won. You see the{" "}
                <strong className="font-bold" style={{ color: "#0F3854" }}>why</strong> behind every answer.
              </p>

              <div className="mt-6 flex flex-wrap gap-2.5">
                {[
                  { v: "94%", l: "Faithfulness" },
                  { v: "0.88", l: "Rerank precision" },
                  { v: "3×", l: "Source coverage" },
                ].map((m) => (
                  <span key={m.l} className="flex items-center gap-2 rounded-full border bg-white/80 px-3.5 py-1.5 text-xs font-semibold backdrop-blur-sm"
                    style={{ borderColor: "rgba(16,79,119,0.15)", color: "#0F3854" }}>
                    <span className="font-extrabold gradient-text">{m.v}</span>
                    {m.l}
                  </span>
                ))}
              </div>

              <ul className="mt-9 space-y-4">
                {[
                  { icon: CheckCircle2, t: "Cross-encoder re-ranked — never raw cosine similarity" },
                  { icon: GitBranch, t: "Multi-hop expansion surfaces bridging concepts & documents" },
                  { icon: Gauge, t: "Live latency + provenance dashboards on every run" },
                  { icon: BadgeCheck, t: "Every answer ships with source citations" },
                ].map(({ icon: Icon, t }) => (
                  <li key={t} className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white"
                      style={{ background: "linear-gradient(135deg,#028090,#0F4C81)" }}>
                      <Icon className="h-4 w-4" />
                    </span>
                    <span className="text-[15px] font-semibold" style={{ color: "#334155" }}>{t}</span>
                  </li>
                ))}
              </ul>

              <div className="mt-10 flex flex-wrap gap-3">
                <button onClick={startFree}
                  className="btn-shine inline-flex items-center gap-2 rounded-xl px-7 py-3.5 text-sm font-bold text-white transition-all hover:-translate-y-0.5"
                  style={{ background: "linear-gradient(135deg,#028090,#104F77)", boxShadow: "0 8px 20px rgba(2,128,144,0.25)" }}>
                  <Rocket className="h-4 w-4" /> Start Free Trial
                  <ArrowRight className="h-4 w-4" />
                </button>
                <Link href="/login" className="btn-secondary rounded-xl px-6 py-3.5 text-sm font-bold">
                  View dashboard →
                </Link>
              </div>
            </div>
          </Reveal>

          <Reveal direction="right" delay={140}>
            <div className="relative">
              <div className="absolute -inset-4 rounded-[2rem] opacity-50 blur-2xl"
                style={{ background: "linear-gradient(135deg,#8FD1E8,#C8E9D9)" }} />
              <div className="gradient-ring shadow-xl">
                <div className="rounded-[calc(1.6rem-1.5px)] bg-gradient-to-b from-white via-white/98 to-[#F5FAFD]">
                  <WorkspacePreview />
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── STATS (Light Premium) ── */}
      <Reveal>
        <section className="relative overflow-hidden py-16"
          style={{ background: "linear-gradient(135deg, #E8F4FA 0%, #EAF7F3 50%, #E2F5EE 100%)" }}>
          <div className="pointer-events-none absolute -left-20 -top-20 h-64 w-64 rounded-full bg-[#028090]/5 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-24 -right-16 h-72 w-72 rounded-full bg-[#10B981]/8 blur-3xl" />
          <div className="pointer-events-none absolute inset-0" style={{ backgroundImage: "radial-gradient(rgba(16,79,119,0.07) 1px, transparent 1px)", backgroundSize: "26px 26px" }} />
          <p className="relative text-center text-[11px] font-semibold uppercase tracking-[0.3em] text-gray-500">
            Measured against a golden-set benchmark
          </p>
          <div className="relative mx-auto mt-10 grid max-w-7xl grid-cols-2 gap-y-10 px-5 lg:grid-cols-4 lg:divide-x lg:divide-[#CDE4EF]">
            {[
              { n: 1024, prefix: "", suffix: "", l: "Embedding dimensions" },
              { n: 800, prefix: "~", suffix: "ms", l: "Median answer latency" },
              { n: 34, prefix: "+", suffix: "%", l: "Graph lift on multi-hop" },
              { n: 200, prefix: "", suffix: "+", l: "Passed test scenarios" },
            ].map((s) => (
              <div key={s.l} className="text-center">
                <div className="gradient-text text-5xl font-extrabold tracking-tight lg:text-6xl">
                  <CountUp value={s.n} prefix={s.prefix} suffix={s.suffix} />
                </div>
                <div className="mx-auto mt-3 h-1 w-10 rounded-full bg-gradient-to-r from-[#028090] to-[#104F77]" />
                <div className="mt-3 text-sm font-medium" style={{ color: "#64748B" }}>{s.l}</div>
              </div>
            ))}
          </div>
        </section>
      </Reveal>

      {/* ── PRICING ── */}
      <section id="pricing" className="mx-auto max-w-7xl px-5 py-20 lg:py-28">
        <Reveal>
          <div className="mx-auto max-w-2xl text-center">
            <div className="kicker">
              <Target className="h-3.5 w-3.5" style={{ color: "#028090" }} /> Pricing
            </div>
            <h2 className="mt-5 text-3xl font-extrabold tracking-tight sm:text-5xl" style={{ color: "#0B2545" }}>
              Start free. Upgrade when you grow.
            </h2>
            <p className="mt-4 text-lg" style={{ color: "#64748B" }}>
              Every plan begins with 3 free questions — no card required. Sign in for a free account with daily limits, or pick Pro for unlimited use.
            </p>
          </div>
        </Reveal>

        <div className="mt-16 grid grid-cols-1 gap-7 lg:grid-cols-3">
          {PRICING.map((p, i) => (
            <Reveal key={p.name} delay={i * 110} className="relative h-full">
              {p.featured && (
                <div className="absolute -top-4 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1 rounded-full px-4 py-1.5 text-xs font-bold text-white shadow-lg"
                  style={{ background: "linear-gradient(135deg,#028090,#0F4C81)", boxShadow: "0 8px 20px rgba(2,128,144,0.30)" }}>
                  <Star className="h-3.5 w-3.5 fill-white" /> Most Popular
                </div>
              )}
              <div className={`gradient-ring h-full ${p.featured ? "lg:scale-[1.04]" : "opacity-90"}`}>
                <div className="flex h-full flex-col rounded-[calc(1.6rem-1.5px)] bg-gradient-to-b from-white via-white/98 to-[#F6FAFD] p-8">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-bold uppercase tracking-wider" style={{ color: "#64748B" }}>{p.name}</div>
                    {p.featured && (
                      <span className="rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-widest text-white"
                        style={{ background: "linear-gradient(135deg,#028090,#104F77)" }}>Recommended</span>
                    )}
                  </div>
                  <div className="mt-3 flex items-end gap-1">
                    <span className="text-5xl font-extrabold tracking-tight gradient-text">{p.price}</span>
                    <span className="mb-1.5 text-sm" style={{ color: "#94A3B8" }}>{p.period}</span>
                  </div>
                  <p className="mt-3 text-sm" style={{ color: "#64748B" }}>{p.desc}</p>
                  <div className="my-6 h-px bg-gradient-to-r from-[#104F77]/20 via-[#028090]/35 to-[#104F77]/20" />
                  <ul className="flex-1 space-y-2.5">
                    {p.features.map((f) => (
                      <li key={f} className="flex items-start gap-2.5 text-sm" style={{ color: "#334155" }}>
                        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-white"
                          style={{ background: "linear-gradient(135deg,#028090,#0F4C81)" }}>
                          <Check className="h-3 w-3" />
                        </span>
                        {f}
                      </li>
                    ))}
                  </ul>
                  <button onClick={p.featured ? goToPro : p.name === "Enterprise" ? () => window.location.href = "mailto:kalevedant750@gmail.com?subject=Enterprise%20Plan%20Inquiry" : startFree}
                    className={`mt-8 w-full rounded-xl px-4 py-3 text-sm font-bold transition-all ${p.featured ? "btn-shine text-white hover:-translate-y-0.5" : "hover:-translate-y-0.5"
                      }`}
                    style={
                      p.featured
                        ? { background: "linear-gradient(135deg,#028090,#0F4C81)", boxShadow: "0 12px 26px rgba(2,128,144,0.32), inset 0 1px 0 rgba(255,255,255,0.16)" }
                        : { border: "1px solid rgba(16,79,119,0.25)", background: "rgba(255,255,255,0.8)", color: "#028090" }
                    }>
                    {p.cta}
                  </button>
                </div>
              </div>
            </Reveal>
          ))}
        </div>

        <Reveal delay={120}>
          <p className="mt-10 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs font-medium" style={{ color: "#64748B" }}>
            <span className="flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5 text-[#028090]" /> SOC 2-aligned infrastructure</span>
            <span className="flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5 text-[#028090]" /> Cancel or downgrade anytime</span>
            <span className="flex items-center gap-1.5"><Lock className="h-3.5 w-3.5 text-[#028090]" /> No credit card for the free tier</span>
          </p>
        </Reveal>
      </section>

      {/* ── FAQ ── */}
      <section id="faq" className="mx-auto max-w-3xl px-5 py-20 lg:py-28">
        <Reveal>
          <div className="text-center">
            <div className="kicker">
              <KeyRound className="h-3.5 w-3.5" style={{ color: "#028090" }} /> FAQ
            </div>
            <h2 className="mt-5 text-3xl font-extrabold tracking-tight sm:text-5xl" style={{ color: "#0B2545" }}>
              Frequently asked questions
            </h2>
          </div>
        </Reveal>

        <div className="mt-10 space-y-3">
          {FAQS.map((f, i) => {
            const open = faqOpen === i;
            return (
              <Reveal key={f.q} delay={i * 60}>
                <div className="overflow-hidden rounded-2xl border bg-white shadow-sm transition-all"
                  style={{ borderColor: open ? "rgba(16,79,119,0.32)" : "rgba(16,79,119,0.12)", boxShadow: open ? "0 12px 28px -14px rgba(11,37,69,0.25)" : undefined }}>
                  <button onClick={() => setFaqOpen(open ? null : i)}
                    className="group flex w-full items-center justify-between gap-4 px-6 py-4 text-left">
                    <span className="flex items-center gap-3.5">
                      <span className="gradient-text text-[11px] font-black tracking-widest">0{i + 1}</span>
                      <span className="text-[15px] font-bold transition-colors group-hover:text-[#0F3854]" style={{ color: open ? "#0B2545" : "#0F2545" }}>{f.q}</span>
                    </span>
                    <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-all duration-300 ${open ? "text-white rotate-180" : "text-[#104F77]"}`}
                      style={open ? { background: "linear-gradient(135deg,#028090,#0F4C81)" } : { background: "rgba(16,79,119,0.08)" }}>
                      <ChevronDown className="h-4 w-4" />
                    </span>
                  </button>
                  <div className={`faq-body ${open ? "open" : ""}`}>
                    <div>
                      <div className="px-6 pb-5 pl-[3.6rem] text-[15px] leading-relaxed" style={{ color: "#64748B" }}>{f.a}</div>
                    </div>
                  </div>
                </div>
              </Reveal>
            );
          })}
        </div>

        <Reveal delay={120}>
          <p className="mt-8 text-center text-sm" style={{ color: "#64748B" }}>
            Still have questions?{" "}
            <a href="mailto:kalevedant750@gmail.com?subject=Question%20about%20GraphRAG" className="inline-flex items-center gap-1 font-bold underline-offset-4 hover:underline" style={{ color: "#028090" }}>
              Talk to our team <ArrowRight className="h-3.5 w-3.5" />
            </a>
          </p>
        </Reveal>
      </section>

      {/* ── FINAL CTA (Light Premium) ── */}
      <section className="px-5 pb-20">
        <Reveal>
          <div className="relative mx-auto max-w-6xl overflow-hidden rounded-3xl px-6 py-16 text-center sm:px-12"
            style={{ background: "linear-gradient(135deg, #E8F4FA 0%, #EAF7F3 45%, #E2F5EE 100%)", boxShadow: "0 24px 60px rgba(2,128,144,0.16)", border: "1px solid rgba(16,185,129,0.22)" }}>
            <div className="aurora aurora-a" style={{ width: 420, height: 420, right: "-12%", top: "-30%", opacity: 0.8, background: "radial-gradient(circle at 60% 40%, rgba(2,128,144,0.28), transparent 70%)" }} />
            <div className="aurora aurora-b" style={{ width: 460, height: 460, left: "-10%", bottom: "-40%", opacity: 0.8, background: "radial-gradient(circle at 40% 60%, rgba(16,79,119,0.26), transparent 70%)" }} />
            <div className="pointer-events-none absolute inset-0" style={{ backgroundImage: "radial-gradient(rgba(16,79,119,0.06) 1px, transparent 1px)", backgroundSize: "24px 24px" }} />

            <div className="relative">
              <div className="gradient-ring mx-auto mb-6 inline-flex h-16 w-16 items-center justify-center rounded-[1.6rem] shadow-lg">
                <div className="flex h-full w-full items-center justify-center rounded-[calc(1.6rem-1.5px)] bg-white">
                  <Network className="h-7 w-7" style={{ color: "#028090" }} />
                </div>
              </div>
              <h2 className="mx-auto max-w-2xl text-3xl font-extrabold tracking-tight sm:text-4xl" style={{ color: "#0B2545" }}>
                Ready to meet your knowledge graph?
              </h2>
              <p className="mx-auto mt-4 max-w-xl text-base" style={{ color: "#64748B" }}>
                Try 3 free questions and start getting cited, relationship-aware answers in under a minute.
              </p>
              <div className="mx-auto mt-8 flex max-w-md flex-col items-center justify-center gap-3 sm:flex-row">
                <button
                  onClick={startFree}
                  className="btn-shine inline-flex items-center gap-2 rounded-2xl px-8 py-4 text-base font-bold text-white transition-all hover:-translate-y-0.5"
                  style={{ background: "linear-gradient(135deg,#028090,#0F4C81)", boxShadow: "0 14px 32px rgba(2,128,144,0.30), inset 0 1px 0 rgba(255,255,255,0.16)" }}>
                  Start Free — 3 Questions
                  <ArrowRight className="h-5 w-5" />
                </button>
                <Link href="/login"
                  className="inline-flex items-center gap-2 rounded-2xl border bg-white/80 px-8 py-4 text-base font-bold backdrop-blur transition-all hover:bg-white"
                  style={{ borderColor: "rgba(16,185,129,0.25)", color: "#028090" }}>
                  Log In
                </Link>
              </div>
            </div>
          </div>
        </Reveal>
      </section>

      {/* ── FOOTER ── */}
      <footer className="relative border-t py-14" style={{ borderColor: "rgba(16,79,119,0.12)", background: "rgba(255,255,255,0.82)" }}>
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#028090]/40 to-transparent" />
        <div className="mx-auto max-w-7xl px-5">
          <div className="grid grid-cols-1 gap-12 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
            <div className="max-w-sm">
              <div className="flex items-center gap-2.5">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl text-white shadow-md"
                  style={{ background: "linear-gradient(135deg,#028090,#0F4C81)", boxShadow: "0 6px 16px rgba(2,128,144,0.25)" }}>
                  <Network className="h-4 w-4" />
                </div>
                <span className="text-[15px] font-extrabold tracking-tight" style={{ color: "#0B2545" }}>
                  Neuro-Adaptive GraphRAG
                </span>
              </div>
              <p className="mt-4 text-sm leading-relaxed" style={{ color: "#64748B" }}>
                A self-learning enterprise platform blending vector search, knowledge graphs, and
                benchmark-driven reweighting.
              </p>
              <div className="mt-5 flex items-center gap-2 text-xs font-semibold" style={{ color: "#0F3854" }}>
                <ShieldCheck className="h-4 w-4 text-[#028090]" />
                SOC 2-aligned · Encrypted at rest · Isolated tenants
              </div>
            </div>

            {[
              { h: "Product", links: [["Features", "#features"], ["How It Works", "#how-it-works"], ["Product", "#product"], ["Pricing", "#pricing"]] },
              { h: "Company", links: [["About", "#"], ["Contact", "#"], ["Privacy", "#"], ["Terms", "#"]] },
              { h: "Resources", links: [["FAQ", "#faq"], ["Marketplace", "#"], ["Status", "#"], ["Security", "#"]] },
            ].map((col) => (
              <div key={col.h}>
                <div className="text-xs font-bold uppercase tracking-widest" style={{ color: "#94A3B8" }}>{col.h}</div>
                <ul className="mt-4 space-y-3">
                  {col.links.map(([label, href]) => (
                    <li key={label}>
                      <a href={href} className="text-sm font-medium transition-colors hover:text-[#028090]" style={{ color: "#475569" }}>{label}</a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mt-12 flex flex-col items-center justify-between gap-3 border-t pt-6 text-xs sm:flex-row"
            style={{ borderColor: "rgba(16,79,119,0.10)", color: "#94A3B8" }}>
            <span>© {new Date().getFullYear()} Neuro-Adaptive GraphRAG. All rights reserved.</span>
            <span className="flex items-center gap-1.5">
              Engineered for precision
              <Sparkles className="h-3.5 w-3.5 text-[#028090]" />
              · Every answer verified
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}

/* ── Hero product preview ── */
function PipelinePreview() {
  return (
    <div className="overflow-hidden rounded-xl">
      <div className="flex items-center justify-between px-5 py-3 text-white"
        style={{ background: "linear-gradient(135deg,#028090,#0F4C81)" }}>
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/15">
            <Network className="h-4 w-4" />
          </div>
          <span className="text-sm font-bold">Pipeline Console</span>
        </div>
        <div className="hidden items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-xs font-medium sm:flex">
          <BadgeCheck className="h-3.5 w-3.5 text-emerald-200" />
          Every answer cited &amp; verifiable
        </div>
      </div>

      <div className="grid grid-cols-1 gap-0 p-4 sm:grid-cols-[240px_1fr] sm:gap-4">
        <div className="space-y-2">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-3">
            <div className="flex items-center gap-2 text-xs font-bold text-emerald-900">
              <Zap className="h-3.5 w-3.5" /> Vector Search
            </div>
            <div className="mt-2 space-y-1.5">
              <SkeletonBar w="w-4/5" />
              <SkeletonBar w="w-3/5" />
              <SkeletonBar w="w-full" />
            </div>
          </div>
          <div className="rounded-xl border border-sky-200 bg-sky-50/70 p-3">
            <div className="flex items-center gap-2 text-xs font-bold text-sky-900">
              <GitBranch className="h-3.5 w-3.5" /> Graph Expansion
            </div>
            <div className="mt-2 grid grid-cols-3 gap-1.5">
              {["A", "B", "C", "D", "E", "F"].map((n) => (
                <span key={n} className="flex h-7 items-center justify-center rounded-md bg-white text-[10px] font-bold text-sky-800 ring-1 ring-sky-200">
                  {n}
                </span>
              ))}
            </div>
          </div>
          <div className="rounded-xl border border-green-200 bg-white p-3">
            <div className="flex items-center gap-2 text-xs font-bold text-[#116B50]">
              <BadgeCheck className="h-3.5 w-3.5" /> Re-ranked · 0.94
            </div>
            <div className="mt-2 text-[11px] leading-relaxed text-gray-500">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="mb-1.5 flex gap-1.5">
                  <span className="h-1 w-3 self-center rounded bg-emerald-200" />
                  <span className="h-2 flex-1 rounded bg-gray-200" />
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="flex flex-col rounded-xl border bg-white p-4" style={{ borderColor: "rgba(16,79,119,0.12)" }}>
          <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-xs font-semibold text-gray-700 ring-1 ring-gray-100">
            <Search className="h-3.5 w-3.5 text-[#104F77]" />
            What infrastructure does RAG pipeline optimize at scale?
          </div>

          <div className="mt-3 space-y-1.5 text-[12px] font-semibold text-gray-700">
            <div className="p-2.5"><strong>RAG pipelines</strong> optimize vector indexing, graph traversal, and contract-based re-ranking…</div>
            <div className="px-2.5 py-1.5 text-[10px] font-bold tracking-wide text-[#0F3854]">
              Faithfulness <span className="text-[#028090]">94%</span>
              <span className="mx-2">·</span>
              Relevancy <span className="text-[#028090]">96%</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {["infra_spec.pdf", "graph_guide.md", "rerank_notes.txt"].map((c) => (
                <span key={c} className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-semibold text-emerald-900 ring-1 ring-emerald-200">
                  <FileText className="h-3 w-3" /> {c}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Workspace preview ── */
function WorkspacePreview() {
  return (
    <div className="overflow-hidden rounded-xl">
      <div className="flex items-center justify-between px-5 py-3 text-white"
        style={{ background: "linear-gradient(90deg,#028090,#104F77)" }}>
        <div className="flex items-center gap-2.5 text-sm font-bold">
          <Sliders className="h-4 w-4" /> Knowledge Graph Console
        </div>
        <div className="text-xs text-white/70">Graph topology · 3 documents</div>
      </div>
      <div className="relative bg-[#F7FAFD] p-5">
        <div className="relative mx-auto h-52 w-full max-w-sm sm:h-64">
          <svg viewBox="0 0 200 200" className="h-full w-full">
            <defs>
              <linearGradient id="edgeg" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#104F77" />
                <stop offset="100%" stopColor="#028090" />
              </linearGradient>
            </defs>
            {[
              [100, 110, 30, 50],
              [100, 110, 30, 150],
              [100, 110, 110, 40],
              [100, 110, 160, 90],
              [100, 110, 160, 170],
              [100, 110, 50, 160],
            ].map(([x1, y1, x2, y2], i) => (
              <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#B9DFE8" strokeWidth={i < 3 ? 2.5 : 1.5} />
            ))}
          </svg>
          {[
            { x: "50%", y: "42%", c: "#104F77", s: "h-16 w-16", t: "API Gateway" },
            { x: "18%", y: "28%", c: "#4A9E87", s: "h-9 w-9", t: "Vector Index" },
            { x: "16%", y: "78%", c: "#4A9E87", s: "h-9 w-9", t: "Chunk Store" },
            { x: "58%", y: "16%", c: "#028090", s: "h-9 w-9", t: "Re-ranker" },
            { x: "84%", y: "34%", c: "#4A9E87", s: "h-9 w-9", t: "Graph Map" },
            { x: "86%", y: "80%", c: "#028090", s: "h-9 w-9", t: "AI" },
          ].map((n) => (
            <div key={n.t} className="absolute -translate-x-1/2 -translate-y-1/2 text-center" style={{ left: n.x, top: n.y }}>
              <div
                className={`mx-auto flex items-center justify-center rounded-full text-white shadow-md ring-4 ring-white ${n.s}`}>
                <Network className={n.s === "h-16 w-16" ? "h-7 w-7" : "h-4 w-4"} />
              </div>
              <div className="mt-1.5 whitespace-nowrap rounded-full bg-white px-2 py-0.5 text-[10px] font-bold text-gray-700 shadow-sm ring-1 ring-gray-200">
                {n.t}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SkeletonBar({ w }: { w: string }) {
  return <div className={`${w} h-2 rounded-full bg-gray-200`} />;
}

/* ── Premium Scroll Reveal ── */
function Reveal({
  children,
  delay = 0,
  direction = "up" as "up" | "left" | "right",
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  direction?: "up" | "left" | "right";
  className?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            setVisible(true);
            obs.disconnect();
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const dirClass = direction === "left" ? "reveal-left" : direction === "right" ? "reveal-right" : "";

  return (
    <div
      ref={ref}
      className={`reveal ${dirClass} ${visible ? "is-visible" : ""} ${className}`}
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
    >
      {children}
    </div>
  );
}

/* ── Animated Count-Up Stat ── */
function CountUp({
  value,
  prefix = "",
  suffix = "",
}: {
  value: number;
  prefix?: string;
  suffix?: string;
}) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const [display, setDisplay] = useState(prefix + "0" + suffix);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setDisplay(prefix + value.toLocaleString() + suffix);
      return;
    }
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            obs.disconnect();
            const t0 = performance.now();
            const dur = 1300;
            const tick = (t: number) => {
              const p = Math.min(1, (t - t0) / dur);
              const eased = 1 - Math.pow(1 - p, 4);
              const v = Math.round(eased * value);
              setDisplay(prefix + v.toLocaleString() + suffix);
              if (p < 1) requestAnimationFrame(tick);
            };
            requestAnimationFrame(tick);
          }
        });
      },
      { threshold: 0.4 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [value, prefix, suffix]);

  return <span ref={ref}>{display}</span>;
}
