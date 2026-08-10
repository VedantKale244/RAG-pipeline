from __future__ import annotations

import re
import unicodedata
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from ..config import settings
from .clients import chat_llm

_SYSTEM = (
    "You are an accurate, highly intelligent domain research assistant. Synthesize a clear, direct, "
    "and precise answer to the user's question using the provided numbered context passages (which include document excerpts and Knowledge Graph entity summaries).\n\n"
    "CRITICAL RULES:\n"
    "1. STRICT ACCURACY: Answer strictly based on facts stated in the provided context passages. Do not invent or extrapolate outside what is stated.\n"
    "2. CONTEXT SYNTHESIS: Address all parts of the user's question using the provided context passages. Synthesize information from Knowledge Graph entity summaries and document passages into a complete response.\n"
    "3. CITATIONS: Cite source passages using bracketed numbers like [1] or [2] immediately following cited statements. Use separate brackets like [1][2] for multiple sources.\n"
    "4. CLEAN PROSE: Write clean, well-formatted paragraphs and bullet points. Never repeat words, characters, or symbols endlessly.\n"
)

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM),
        ("human", "Question:\n{question}\n\nContext passages:\n{context}\n\nAnswer:"),
    ]
)

# Returned (never LLM-generated) when retrieval genuinely found zero relevant passages.
# It explains the likely causes instead of the old terse "couldn't find context" line,
# which users reported as a dead-end even when they had uploaded documents.
_NO_CONTEXT_MSG = (
    "I couldn't find a relevant passage to answer that question in the documents "
    "currently attached to this session. Likely causes: the document is still indexing, "
    "the question doesn't closely match the uploaded content, or the upload happened "
    "under a different session/account than this one. Try waiting a moment and re-asking, "
    "rephrasing your question, or re-uploading the document."
)


def _format_context(candidates: list[dict]) -> str:
    if not candidates:
        return ""
    # Share a bounded context budget among reranked passages. This avoids a
    # large prompt turning a short interactive answer into a long request.
    per_passage = max(400, settings.chat_context_max_chars // len(candidates))
    lines = []
    for i, c in enumerate(candidates, start=1):
        tag = " (via graph)" if c.get("via_graph") else ""
        source = c.get("source") or "Document"
        raw_text = c.get("text")
        text = (raw_text if isinstance(raw_text, str) else str(raw_text or "")).strip()[:per_passage]
        lines.append(f"[{i}] source={source}{tag}\n{text}")
    return "\n\n".join(lines)


def _clean_token(token: str) -> str:
    """Sanitize token string: strip Latin-1 artifacts (Â, â, Ã, etc.), non-breaking spaces (\xa0), and control chars."""
    if not token:
        return ""
    # Strip Latin-1 artifacts like Â (U+00C2), â (U+00E2), Ã (U+00C3), non-breaking spaces (\xa0)
    token = token.replace("\xa0", " ")
    token = re.sub(r"[\u00C0-\u00FF]", "", token)
    token = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd]", "", token)
    return token


def _guard_repetition(text: str) -> str:
    """Detect and collapse runaway repetitive character loops like 'ÂÂÂÂÂ...' or '.....'."""
    if not text:
        return ""
    # Remove repetitive extended Latin artifacts
    text = re.sub(r"[\u00C0-\u00FF]", "", text)
    # Collapse any character repeating 4 or more times continuously
    text = re.sub(r"(.)\1{3,}", r"\1\1", text)
    return text.strip()


def generate_answer(question: str, candidates: list[dict]) -> str:
    """Run the LLM chain. Traced automatically by LangSmith when enabled."""
    return generate_answer_with_run_id(question, candidates)[0]


def generate_answer_with_run_id(
    question: str, candidates: list[dict]
) -> tuple[str, str | None]:
    """Like generate_answer, but also returns the LangSmith run id of this invocation."""
    if not candidates:
        return _NO_CONTEXT_MSG, None

    from langchain_core.tracers.context import collect_runs

    chain = _PROMPT | chat_llm() | StrOutputParser()
    with collect_runs() as cb:
        raw_answer = chain.invoke(
            {"question": question, "context": _format_context(candidates)}
        )
        run_id = str(cb.traced_runs[0].id) if cb.traced_runs else None

    clean_answer = _guard_repetition(_clean_token(raw_answer))
    return clean_answer, run_id


def stream_answer(question: str, candidates: list[dict]):
    """Yield answer tokens as a streaming generator with token sanitization and repetition guard."""
    if not candidates:
        yield _NO_CONTEXT_MSG
        return

    try:
        chain = _PROMPT | chat_llm() | StrOutputParser()

        recent_non_space_chars: list[str] = []
        for raw_token in chain.stream(
            {"question": question, "context": _format_context(candidates)}
        ):
            token = _clean_token(str(raw_token))
            if not token:
                continue

            for char in token:
                if not char.isspace():
                    recent_non_space_chars.append(char)
                    if len(recent_non_space_chars) > 12:
                        recent_non_space_chars.pop(0)

            # Halt if 4 or more identical non-whitespace characters repeat in a row
            if (
                len(recent_non_space_chars) >= 4
                and len(set(recent_non_space_chars[-4:])) == 1
            ):
                break

            yield token
    except Exception as exc:
        import logging
        logging.getLogger("app").error(f"Error streaming LLM tokens: {exc}")
        yield f"\n\n[Note: LLM generation encountered an issue: {exc}]"


