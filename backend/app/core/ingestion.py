"""Document ingestion: load → chunk → embed → (vector upsert + graph build).

This is the write path. Given a raw file, it produces chunks that are stored in Pinecone
and simultaneously fed to the GraphRAG builder so the knowledge graph and the vector
index stay in sync (linked by a shared ``chunk_id``).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings
from . import graphrag, vectorstore

_SUPPORTED = {".txt", ".md", ".pdf", ".docx"}


def _token_len(text: str) -> int:
    """Token count via tiktoken (cl100k_base) as a model-agnostic size proxy.

    Cohere has its own tokenizer, but that's a network call per chunk; tiktoken is a
    close-enough local proxy for *sizing*. Falls back to a chars/4 estimate if tiktoken
    can't load its encoding (e.g. offline first run).
    """
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:  # ponytail: offline/no-tiktoken → chars/4 heuristic, good enough for sizing
        return max(1, len(text) // 4)


def _make_splitter() -> RecursiveCharacterTextSplitter:
    """Token-aware, structure-aware splitter.

    Sizes are counted in tokens (not characters), so chunks are semantically sized
    regardless of text density. Separators prefer paragraph → line → sentence breaks,
    so we split on structure before falling back to mid-word cuts.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=_token_len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def _load_text(path: Path) -> str:
    suffix = path.suffix.lower()
    text = ""
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        import docx

        doc = docx.Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    # Validate extracted text content: check if text contains readable alphanumeric content
    import re
    clean_words = re.findall(r"\b[a-zA-Z0-9]{2,}\b", text or "")
    if len(clean_words) < 5 or len(text.strip()) < 20:
        raise ValueError(
            "This document contains no readable text (it may be an image-only PDF, scanned document, blank file, or unreadable format). Ingestion cannot proceed with this document."
        )

    return text



def _chunk_id(document_id: str, text: str, idx: int) -> str:
    digest = hashlib.sha1(f"{document_id}:{idx}:{text[:64]}".encode()).hexdigest()[:12]
    return f"{document_id}-{digest}"


def document_id_for(user_id: str, name: str) -> str:
    """Public stable document id for a user+filename pair (mirrors ingest_file)."""
    return _document_id(f"{user_id}:{name}")


def _document_id(name: str) -> str:
    """Stable identity for a source, keyed by filename.

    Re-uploading the same filename yields the same document_id, which is what lets
    ingest wipe the prior copy (delete_by_document) instead of accumulating duplicate
    chunks across repeated uploads. Editing a file's contents but keeping its name
    intentionally replaces the old version.
    """
    return hashlib.sha1(name.encode()).hexdigest()[:10]


def _make_chunks(raw: str, name: str, document_id: str, user_id: str) -> list[dict]:
    """Split extracted text into chunk records."""
    pieces = _make_splitter().split_text(raw)
    return [
        {
            "chunk_id": _chunk_id(document_id, piece, i),
            "text": piece,
            "source": name,
            "document_id": document_id,
            "user_id": user_id,
        }
        for i, piece in enumerate(pieces)
        if piece.strip()
    ]


def ingest_file(
    path: str | Path,
    filename: str | None = None,
    user_id: str = "guest",
    progress_callback: callable | None = None,
) -> dict:
    """Ingest one file end-to-end. Returns counts for the API response."""
    path = Path(path)
    if path.suffix.lower() not in _SUPPORTED:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    name = filename or path.name
    document_id = _document_id(f"{user_id}:{name}")

    if progress_callback:
        progress_callback("Extracting document text...")
    raw = _load_text(path)

    if progress_callback:
        progress_callback("Splitting document into chunks...")
    pieces = _make_splitter().split_text(raw)

    chunks = _make_chunks(raw=raw, name=name, document_id=document_id, user_id=user_id)

    # Check which chunks are already stored in Neo4j to support incremental updates
    existing_ids = graphrag.get_existing_chunk_ids([c["chunk_id"] for c in chunks], user_id)
    new_chunks = [c for c in chunks if c["chunk_id"] not in existing_ids]

    if new_chunks:
        # Write path 1: vector store for new chunks — this is the retrieval-critical
        # path and MUST complete even if the knowledge graph is unavailable.
        if progress_callback:
            progress_callback(f"Indexing & embedding {len(new_chunks)} document chunks...")

        vectorstore.upsert_chunks(new_chunks)

        # Write path 2: knowledge graph (best-effort). If Neo4j is down or the LLM
        # graph-mining errors out, the vectors above are already saved and answers
        # still work via dense retrieval — so ingestion must not fail here. Returning
        # correct entities=0/relationships=0 keeps the job "done" and the doc usable.
        if progress_callback:
            progress_callback(f"Incremental Update: Mining entities & relationships ({len(new_chunks)} new chunks)...")
        try:
            graph_stats = graphrag.build_from_chunks(new_chunks, progress_callback=progress_callback)
        except Exception as exc:
            if progress_callback:
                progress_callback("Knowledge graph build skipped (graph service unavailable). Vectors committed.")
            graph_stats = {
                "entities": 0,
                "relationships": 0,
                "explanation": f"Knowledge graph could not be updated ('{name}' is searchable via vector retrieval). Graph service unavailable.",
            }
    else:
        if progress_callback:
            progress_callback("All document chunks are already processed. Preserving graph nodes.")
        graph_stats = {
            "entities": 0,
            "relationships": 0,
            "explanation": f"Knowledge Graph for '{name}' is already up-to-date. No new chunks detected.",
        }

    return {
        "document_id": document_id,
        "filename": name,
        "chunks": len(chunks),
        "entities": graph_stats["entities"],
        "relationships": graph_stats["relationships"],
        "explanation": graph_stats.get("explanation", ""),
    }

