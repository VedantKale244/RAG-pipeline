// Typed client for the Neuro-Adaptive GraphRAG backend.
//
// Use the same-origin /api proxy by default. This keeps browser requests and
// EventSource streams working when the UI is opened from a non-localhost host
// (or deployed behind a reverse proxy), and avoids exposing the backend URL in
// the compiled client bundle. An explicit public URL remains supported for
// installations that intentionally expose their API separately.
const BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/+$/, "");
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";

export function apiBase(): string {
  return BASE;
}

let guestTokenMemory: string | null = null;

export function getOrInitGuestSessionToken(): string {
  if (typeof window === "undefined") return "guest";
  if (!guestTokenMemory) {
    const stored = sessionStorage.getItem("graphrag_active_guest_token");
    if (stored) {
      guestTokenMemory = stored;
    } else {
      guestTokenMemory = `guest_sess_${Math.random().toString(36).slice(2, 10)}_${Date.now()}`;
      sessionStorage.setItem("graphrag_active_guest_token", guestTokenMemory);
    }
  }
  return guestTokenMemory;
}

export async function cleanupGuestSession(tokenToClean?: string): Promise<void> {
  const token = tokenToClean || guestTokenMemory || (typeof window !== "undefined" ? sessionStorage.getItem("graphrag_active_guest_token") : null);
  if (token && token.startsWith("guest")) {
    try {
      await fetch(`${BASE}/guest/cleanup`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        keepalive: true
      });
    } catch (e) {
      console.warn("Guest session cleanup notification failed", e);
    }
  }
  if (typeof window !== "undefined") {
    sessionStorage.removeItem("graphrag_active_guest_token");
  }
  if (!tokenToClean || tokenToClean === guestTokenMemory) {
    guestTokenMemory = null;
  }
}

export function resetGuestSession(): string {
  const oldToken = guestTokenMemory || (typeof window !== "undefined" ? sessionStorage.getItem("graphrag_active_guest_token") : null);
  if (oldToken) {
    cleanupGuestSession(oldToken);
  }
  guestTokenMemory = `guest_sess_${Math.random().toString(36).slice(2, 10)}_${Date.now()}`;
  if (typeof window !== "undefined") {
    sessionStorage.setItem("graphrag_active_guest_token", guestTokenMemory);
  }
  return guestTokenMemory;
}

export function getActiveSessionToken(): string {
  if (typeof window !== "undefined") {
    const userToken = localStorage.getItem("graphrag_user_token");
    if (userToken) return userToken;
    return getOrInitGuestSessionToken();
  }
  return "guest";
}

// Header for authenticated fetch calls. Empty when no key is configured, which
// matches the backend's fail-open behaviour for local dev.
function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = API_KEY ? { "X-API-Key": API_KEY } : {};
  if (typeof window !== "undefined") {
    const token = getActiveSessionToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }
  return headers;
}

// The browser EventSource API can't send custom headers, so the SSE endpoint
// takes the key as a query param instead. Returns "" when no key is set.
export function apiKeyQuery(): string {
  return API_KEY ? `&api_key=${encodeURIComponent(API_KEY)}` : "";
}

export interface Citation {
  chunk_id: string;
  source: string;
  text: string;
  score: number;
  via_graph: boolean;
}

export type Edge = [string, string];

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  trace_url: string | null;
  latency_ms: number;
  edges: Edge[];
}

export interface IngestResponse {
  document_id: string;
  filename: string;
  chunks: number;
  entities: number;
  relationships: number;
  explanation?: string | null;
}

export interface IngestJob {
  job_id: string;
  status: string;
  filename: string;
}

export interface IngestStatus extends IngestJob {
  progress?: string | null;
  result: IngestResponse | null;
  error: string | null;
}


export interface EvalResponse {
  scores: {
    faithfulness: number;
    answer_relevancy: number;
    context_precision: number;
    context_recall: number;
  };
  per_sample: Array<Record<string, unknown>>;
  updated_edges: number;
  graph_lift: number | null;
}

export interface EvalRun {
  ts: number;
  scores: EvalResponse["scores"];
  updated_edges: number;
  graph_lift: number | null;
  n_samples: number;
}

export interface GraphSnapshot {
  nodes: { id: string; kind?: string }[];
  edges: { source: string; target: string; rel_type: string; weight: number }[];
  explanation?: string | null;
}

export interface AdminDoc {
  source: string;
  document_id: string;
  chunk_count: number;
}

export interface AdminStats {
  documents: AdminDoc[];
  total_documents: number;
  total_chunks: number;
  total_nodes: number;
  total_edges: number;
  users: {
    total_users: number;
    verified_users: number;
    by_plan: Record<string, number>;
    total_conversations: number;
    total_messages: number;
    active_sessions: number;
  };
  config: {
    llm: string;
    embeddings: string;
    embed_dim: number;
    vector_store: string;
    reranker: string;
    top_k: number;
    graph_fanout: number;
    rerank_floor: number;
  };
}

export interface AdminUser {
  id: string;
  full_name: string;
  email: string;
  plan: string;
  is_email_verified: boolean;
  auth_provider: string;
  created_at: number;
  conversation_count: number;
  message_count: number;
  last_active: number;
  stripe_subscription_id: string | null;
}

export interface AdminUsersResponse {
  users: AdminUser[];
  stats: AdminStats["users"];
}

export interface SelfOptStatus {
  enabled: boolean;
  tombstoned: boolean;
  champion_version: string | null;
  champion: Record<string, unknown> | null;
  lifecycle_stage: string;
  consecutive_failures: number;
  active_version: string | null;
  next_trigger: string | null;
  rebuild_fence_clear: boolean;
}

export interface DeleteDocResponse {
  status: string;
  document_id: string;
  vectors_deleted: number;
  graph_stats: Record<string, unknown>;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export async function health(): Promise<Record<string, unknown>> {
  return handle(await fetch(`${BASE}/health`));
}

export async function ingest(file: File, clearPrevious: boolean = false): Promise<IngestJob> {
  const form = new FormData();
  form.append("file", file);
  return handle(await fetch(`${BASE}/ingest?clear_previous=${clearPrevious}`, { method: "POST", body: form, headers: authHeaders() }));
}

export async function checkDuplicate(filename: string): Promise<{ exists: boolean; filename: string }> {
  return handle(await fetch(`${BASE}/ingest/check-duplicate?filename=${encodeURIComponent(filename)}`, { headers: authHeaders() }));
}

export async function getUserDocuments(): Promise<{ documents: any[]; total: number }> {
  return handle(await fetch(`${BASE}/ingest/user-documents`, { headers: authHeaders() }));
}

export async function ingestStatus(jobId: string): Promise<IngestStatus> {
  return handle(await fetch(`${BASE}/ingest/status/${jobId}`, { headers: authHeaders() }));
}


export async function sendFeedback(
  question: string,
  helpful: boolean,
  edges: Edge[]
): Promise<{ updated_edges: number }> {
  return handle(
    await fetch(`${BASE}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ question, helpful, edges }),
    })
  );
}

export async function evalHistory(): Promise<{ runs: EvalRun[] }> {
  const token = getActiveSessionToken();
  const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : "";
  return handle(await fetch(`${BASE}/eval/history${tokenQuery}`, { headers: authHeaders() }));
}

export async function chat(
  question: string,
  useGraph: boolean
): Promise<ChatResponse> {
  return handle(
    await fetch(`${BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ question, use_graph: useGraph }),
    })
  );
}

export async function runEval(
  samples: { question: string; ground_truth: string }[]
): Promise<EvalResponse> {
  return handle(
    await fetch(`${BASE}/eval`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ samples }),
    })
  );
}

export interface EntityDetailRelationship {
  neighbor: string;
  rel_type: string;
  weight: number;
}

export interface EntityDetailPassage {
  chunk_id: string;
  source: string;
  text: string;
}

export interface EntityDetailsResponse {
  name: string;
  type: string;
  rationale?: string;
  relationships: EntityDetailRelationship[];
  passages: EntityDetailPassage[];
}

export interface GraphSummaryResponse {
  total_entities: number;
  total_relationships: number;
  top_hubs: { name: string; degree: number }[];
  entity_types: Record<string, number>;
  rules: string[];
  summary: string;
  relationship_types?: Record<string, number> | null;
  density?: number | null;
  duplicates_removed?: number | null;
  merged_entities?: number | null;
  ignored_entities_count?: number | null;
  ignored_relationships_count?: number | null;
  graph_confidence?: number | null;
  major_entities?: Array<{
    name: string;
    type: string;
    importance: string;
    purpose: string;
    why_exists: string;
    connected_nodes_count: number;
    relationships_count: number;
    connected_small_entities: Array<{ name: string; type: string; why_connected: string }>;
    relationship_summary: Record<string, string[]>;
  }> | null;
  ignored_information?: Array<{ name: string; reason: string }> | null;
}

export async function graph(): Promise<GraphSnapshot> {
  const token = getActiveSessionToken();
  const tokenQuery = token ? `&token=${encodeURIComponent(token)}` : "";
  return handle(await fetch(`${BASE}/graph?limit=120${tokenQuery}`, { headers: authHeaders() }));
}

export async function getEntityDetails(name: string): Promise<EntityDetailsResponse> {
  const token = getActiveSessionToken();
  const tokenQuery = token ? `&token=${encodeURIComponent(token)}` : "";
  return handle(await fetch(`${BASE}/graph/entity-details?name=${encodeURIComponent(name)}${tokenQuery}`, { headers: authHeaders() }));
}

export async function getGraphSummary(): Promise<GraphSummaryResponse> {
  const token = getActiveSessionToken();
  const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : "";
  return handle(await fetch(`${BASE}/graph/summary${tokenQuery}`, { headers: authHeaders() }));
}


export async function verifyAdminPassword(password: string): Promise<{ status: string; valid: boolean }> {
  return handle(
    await fetch(`${BASE}/admin/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    })
  );
}

export async function adminStats(passcode?: string): Promise<AdminStats> {
  const headers = { ...authHeaders(), ...(passcode ? { "X-Admin-Password": passcode } : {}) };
  return handle(await fetch(`${BASE}/admin/stats`, { headers }));
}

export async function deleteDocument(documentId: string, passcode?: string): Promise<DeleteDocResponse> {
  const headers = { ...authHeaders(), ...(passcode ? { "X-Admin-Password": passcode } : {}) };
  return handle(
    await fetch(`${BASE}/admin/documents/${encodeURIComponent(documentId)}`, {
      method: "DELETE",
      headers,
    })
  );
}

export async function adminUsers(passcode?: string): Promise<AdminUsersResponse> {
  const headers = { ...authHeaders(), ...(passcode ? { "X-Admin-Password": passcode } : {}) };
  return handle(await fetch(`${BASE}/admin/users`, { headers }));
}

export async function selfoptStatus(passcode?: string): Promise<SelfOptStatus> {
  const headers = { ...authHeaders(), ...(passcode ? { "X-Admin-Password": passcode } : {}) };
  return handle(await fetch(`${BASE}/admin/selfopt/status`, { headers }));
}

export interface SelfOptRepair {
  id?: number;
  fingerprint: string;
  endpoint: string | null;
  count: number;
  status: string;
  first_seen: number;
  last_seen: number;
  traceback?: string;
}

export async function selfoptErrors(passcode?: string): Promise<{ repairs: SelfOptRepair[] }> {
  const headers = { ...authHeaders(), ...(passcode ? { "X-Admin-Password": passcode } : {}) };
  return handle(await fetch(`${BASE}/admin/selfopt/errors`, { headers }));
}

export interface UserProfile {
  id: string;
  full_name: string;
  email: string;
  created_at: number;
  plan?: string;
}

export interface AuthResponse {
  token: string;
  user: UserProfile;
}

export interface OtpResponse {
  status: string;
  message: string;
  sent: boolean;
  dev_otp?: string | null;
}

export async function sendOtp(email: string): Promise<OtpResponse> {
  return handle(
    await fetch(`${BASE}/auth/send-otp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    })
  );
}

export async function verifyOtpSignUp(
  full_name: string,
  email: string,
  password: string,
  otp: string
): Promise<AuthResponse> {
  return handle(
    await fetch(`${BASE}/auth/verify-otp-signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name, email, password, otp }),
    })
  );
}

export async function googleAuth(email: string, full_name: string, googleToken?: string): Promise<AuthResponse> {
  return handle(
    await fetch(`${BASE}/auth/google`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, full_name, google_token: googleToken }),
    })
  );
}

/**
 * Fetch public Supabase configuration from backend if needed.
 */
export async function getSupabaseConfig(): Promise<{ supabaseUrl: string; supabaseAnonKey: string }> {
  return handle(await fetch(`${BASE}/auth/supabase-config`));
}

/**
 * Exchange a Supabase Google OAuth access token or session token for a backend session token.
 */
export async function supabaseGoogleAuth(accessToken: string, email?: string, fullName?: string): Promise<AuthResponse> {
  return handle(
    await fetch(`${BASE}/auth/supabase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        access_token: accessToken,
        email: email || null,
        full_name: fullName || null,
      }),
    })
  );
}


export async function signUp(full_name: string, email: string, password: string): Promise<AuthResponse> {
  return handle(
    await fetch(`${BASE}/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name, email, password }),
    })
  );
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  return handle(
    await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    })
  );
}

export async function getMe(token: string): Promise<UserProfile> {
  return handle(
    await fetch(`${BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
  );
}

export async function logout(token: string): Promise<{ status: string }> {
  return handle(
    await fetch(`${BASE}/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    })
  );
}

export interface UsageSnapshot {
  plan: string;
  completed_plan: string;
  is_guest: boolean;
  unlimited: boolean;
  trial: {
    questions_limit: number;
    questions_remaining: number;
  };
  daily: {
    uploads_limit: number;
    uploads_used_today: number;
    questions_per_doc_limit: number;
  };
}

export async function getUsage(): Promise<UsageSnapshot> {
  return handle(await fetch(`${BASE}/usage`, { headers: authHeaders() }));
}

export async function createCheckout(plan: string): Promise<{ url: string; session_id: string; plan: string }> {
  return handle(
    await fetch(`${BASE}/account/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ plan }),
    })
  );
}

export async function downgradePlan(): Promise<{ status: string; plan: string }> {
  return handle(
    await fetch(`${BASE}/account/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ plan: "free" }),
    })
  );
}

export interface ConversationMeta {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
}

export interface ChatHistoryMessage {
  id: string;
  query: string;
  answer: string;
  citations: Citation[];
  edges: Edge[];
  created_at: number;
}

export interface ConversationDetails {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  messages: ChatHistoryMessage[];
}

export async function listConversations(token: string): Promise<{ conversations: ConversationMeta[] }> {
  return handle(await fetch(`${BASE}/chat/conversations?token=${encodeURIComponent(token)}`));
}

export async function getConversation(id: string, token: string): Promise<ConversationDetails> {
  return handle(await fetch(`${BASE}/chat/conversations/${encodeURIComponent(id)}?token=${encodeURIComponent(token)}`));
}

export async function deleteConversation(id: string, token: string): Promise<{ status: string }> {
  return handle(
    await fetch(`${BASE}/chat/conversations/${encodeURIComponent(id)}?token=${encodeURIComponent(token)}`, {
      method: "DELETE",
    })
  );
}
