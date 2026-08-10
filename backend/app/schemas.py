"""Pydantic request/response schemas shared across the API and core layers."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Citation(BaseModel):
    chunk_id: str
    source: str
    text: str
    score: float = Field(description="Post-rerank relevance score")
    via_graph: bool = Field(default=False, description="Surfaced via graph expansion")


class ChatRequest(BaseModel):
    question: str
    top_k: int | None = None
    use_graph: bool = True


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    trace_url: str | None = None
    latency_ms: int
    edges: list[tuple[str, str]] = Field(
        default_factory=list,
        description="surviving_edges: graph paths that fed this answer (for provenance + feedback)",
    )


class IngestResponse(BaseModel):
    document_id: str
    filename: str
    chunks: int
    entities: int
    relationships: int
    explanation: str | None = Field(default=None, description="AI explanation of the extracted knowledge graph structure")


class IngestJobResponse(BaseModel):
    """Returned immediately by POST /ingest; poll /ingest/status/{job_id} for the result."""

    job_id: str
    status: str
    filename: str


class IngestStatusResponse(BaseModel):
    job_id: str
    status: str  # queued | running | done | failed
    filename: str
    progress: str | None = None
    result: IngestResponse | None = None
    error: str | None = None



class EvalRequest(BaseModel):
    """A small golden set of question/ground-truth pairs for RAGAS."""

    samples: list[dict] = Field(
        max_length=50,  # ponytail: cap fan-out — /eval runs LLM+RAGAS per sample
        description="Each item: {'question': str, 'ground_truth': str}",
    )


class EvalScore(BaseModel):
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float


class EvalResponse(BaseModel):
    scores: EvalScore
    per_sample: list[dict]
    updated_edges: int = Field(description="Graph edges reweighted from this eval run")
    graph_lift: float | None = Field(
        default=None,
        description="Measured RAGAS composite delta (graph-on minus graph-off); null if not run",
    )


class FeedbackRequest(BaseModel):
    """Inline thumbs up/down on an answer, feeding the same edge-reward loop as RAGAS."""

    question: str
    helpful: bool = Field(description="True = thumbs up, False = thumbs down")
    edges: list[tuple[str, str]] = Field(
        default_factory=list,
        max_length=200,
        description="surviving_edges from the answer's retrieval trace, (source, target) pairs",
    )


class FeedbackResponse(BaseModel):
    updated_edges: int


class SignUpRequest(BaseModel):
    full_name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserProfile(BaseModel):
    id: str
    full_name: str
    email: str
    created_at: float
    plan: str = "free"


class AuthResponse(BaseModel):
    token: str
    user: UserProfile


class SendOtpRequest(BaseModel):
    email: str


class VerifyOtpSignUpRequest(BaseModel):
    full_name: str
    email: str
    password: str
    otp: str


class GoogleAuthRequest(BaseModel):
    email: str
    full_name: str
    google_token: str | None = None


class SupabaseAuthRequest(BaseModel):
    access_token: str | None = Field(default=None, description="Supabase OAuth access token")
    id_token: str | None = Field(default=None, description="Google OAuth ID token")
    email: str | None = Field(default=None, description="User email address")
    full_name: str | None = Field(default=None, description="User full name")




