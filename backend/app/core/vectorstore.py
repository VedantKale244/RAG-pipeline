"""Pinecone vector store wrapper.

Chunks are embedded with Cohere and upserted with their text + source stored in
metadata so retrieval can return citations without a second round-trip.
"""
from __future__ import annotations

from ..errors import SearchUnavailable
from .clients import (
    EmbeddingUnavailable,
    pinecone_index,
    safe_embed_documents,
    safe_embed_query,
)

_BATCH = 100


def _build_filter(user_id: str | None, version: str | None = None) -> dict:
    """Pinecone metadata filter shared by live and shadow queries.

    Live (``version`` is None) needs ``selfopt_version = {"$exists": False}`` —
    production vectors have *no* such field at all, so ``{"$eq": None}`` is both
    wrong (Pinecone doesn't index null as a value) and would miss every live row.
    Shadow (``version`` set) pins exactly that version's vectors.
    """
    f: dict = {"user_id": user_id}
    if version is None:
        f["selfopt_version"] = {"$exists": False}
    else:
        f["selfopt_version"] = version
    return f


def upsert_chunks(chunks: list[dict], version: str | None = None) -> int:
    """Embed and upsert chunk dicts. Each dict needs chunk_id/text/source/document_id/user_id.

    ``version`` (shadow rebuild) writes under a prefixed id
    ``sel{version}-{document_id}-{n}`` plus a ``selfopt_version`` metadata tag, so
    the existing prefix-scan teardown can remove a shadow generation (Spec §7.1).
    """
    if not chunks:
        return 0

    index = pinecone_index()

    total = 0
    for start in range(0, len(chunks), _BATCH):
        batch = chunks[start : start + _BATCH]
        vectors = safe_embed_documents([c["text"] for c in batch])

        payload = []
        for n, (c, vec) in enumerate(zip(batch, vectors)):
            metadata = {
                "text": c["text"],
                "source": c["source"],
                "document_id": c["document_id"],
                "user_id": c.get("user_id", "guest"),
            }
            cid = c["chunk_id"]
            if version is not None:
                metadata["selfopt_version"] = version
                cid = f"sel{version}-{c['document_id']}-{n}"
            payload.append({"id": cid, "values": vec, "metadata": metadata})
        index.upsert(vectors=payload)
        total += len(payload)
    return total


def clear_user_vectors(user_id: str) -> int:
    """Delete all vectors for a user from Pinecone."""
    if not user_id:
        return 0
    index = pinecone_index()
    try:
        index.delete(filter={"user_id": user_id})
        return 1
    except Exception:
        return 0


def delete_by_document(document_id: str) -> int:
    """Delete all vectors for a document. Returns the count removed."""
    index = pinecone_index()
    deleted = 0
    try:
        # Delete by metadata filter first for reliable cleanup
        index.delete(filter={"document_id": document_id})
    except Exception:
        pass
    try:
        # Pass limit=100 so Pinecone returns prefix matches in 1 fast HTTP roundtrip
        for ids in index.list(prefix=f"{document_id}-", limit=100):
            if ids:
                index.delete(ids=ids)
                deleted += len(ids)
    except Exception:
        pass
    return deleted



def delete_shadow(version: str) -> int:
    """Delete a shadow generation's vectors (prefix `sel{version}-`)."""
    index = pinecone_index()
    deleted = 0
    try:
        for ids in index.list(prefix=f"sel{version}-", limit=100):
            if ids:
                index.delete(ids=ids)
                deleted += len(ids)
    except Exception:
        pass
    return deleted


def query(text: str, top_k: int, user_id: str | None = None, version: str | None = None) -> list[dict]:
    """Dense similarity search scoped strictly by user_id (+ optional shadow version).

    Returns candidate dicts with score + metadata. ``version`` is None ⇒ live
    search: shadow vectors are excluded both by the filter and by a second
    in-loop guard — the bare except fallback may drop the filter, and without
    that guard a fallback would silently leak shadow vectors into live answers.
    """
    if not user_id:
        return []
    try:
        index = pinecone_index()
        vec = safe_embed_query(text)
        target_user = user_id

        filter_dict = _build_filter(target_user, version)

        try:
            res = index.query(vector=vec, top_k=top_k, include_metadata=True, filter=filter_dict)
        except Exception:
            # Fallback if index lacks filter metadata schema. The in-loop guard
            # below still enforces the version boundary on whatever comes back.
            res = index.query(vector=vec, top_k=top_k, include_metadata=True)
    except EmbeddingUnavailable:
        # Hard failure: without a query vector there is no search at all. Propagate so the
        # caller reports it, instead of returning [] and rendering as "no information found".
        raise
    except Exception as exc:
        import logging
        logging.getLogger("app").warning(f"Vector search query failed safely (e.g. rate limit): {exc}")
        # Do NOT swallow infrastructure failure as "no results" — that produced misleading
        # "I couldn't find any relevant context" answers for users who HAD uploaded documents.
        # Let the caller distinguish a broken search from a genuinely empty result set.
        raise SearchUnavailable(f"Vector search is temporarily unavailable: {exc}") from exc

    out: list[dict] = []
    for match in res.get("matches", []):
        md = match.get("metadata", {})
        chunk_user = md.get("user_id")
        # Enforce strict user boundary: skip any chunk whose user_id doesn't match.
        if not chunk_user or chunk_user != target_user:
            continue
        match_version = (md.get("selfopt_version") or None)
        # Enforce the version boundary against the fallback's unfiltered results.
        if version is None:
            if match_version is not None:
                continue  # a shadow vector leaked through the fallback → drop it
        elif match_version != version:
            continue
        out.append(
            {
                "chunk_id": match["id"],
                "text": md.get("text", ""),
                "source": md.get("source", "unknown"),
                "user_id": chunk_user,
                "document_id": md.get("document_id", ""),
                "score": float(match.get("score", 0.0)),
                "via_graph": False,
            }
        )
    return out


def delete_by_user(user_id: str) -> int:
    """Delete all vectors for a specific user_id in Pinecone."""
    if not user_id:
        return 0
    index = pinecone_index()
    try:
        index.delete(filter={"user_id": user_id})
        return 1
    except Exception as exc:
        import logging
        logging.getLogger("app").warning(f"Pinecone delete_by_user failed for {user_id}: {exc}")
        return 0


def purge_legacy_guest_data() -> int:
    """Purge legacy 'guest' vectors from Pinecone."""
    index = pinecone_index()
    try:
        index.delete(filter={"user_id": "guest"})
        return 1
    except Exception:
        return 0



def fetch_by_ids(chunk_ids: list[str]) -> list[dict]:
    """Fetch chunks by id (used by graph expansion to hydrate linked chunks)."""
    if not chunk_ids:
        return []
    index = pinecone_index()
    res = index.fetch(ids=chunk_ids)
    # FetchResponse is attribute-style (res.vectors: dict[id, Vector]), NOT dict-like —
    # res.get(...) raises AttributeError on the pinecone v7 SDK.
    out: list[dict] = []
    for cid, vec in (res.vectors or {}).items():
        md = vec.metadata or {}
        out.append(
            {
                "chunk_id": cid,
                "text": md.get("text", ""),
                "source": md.get("source", "unknown"),
                "document_id": md.get("document_id", ""),
                "score": 0.0,
                "via_graph": True,
            }
        )
    return out
