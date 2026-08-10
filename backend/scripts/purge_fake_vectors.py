"""Delete fabricated hash-based embeddings from Pinecone.

A previous `_deterministic_vector` fallback wrote sha256-derived vectors whenever the
Cohere API failed. They are structurally invalid (a 32-float unit tiled to fill the
dimension) and can never match a real query, so any chunk stored with one is dead
weight that silently degrades search.

This finds them by that tiling signature and deletes them. Affected documents must be
re-uploaded (with a working COHERE_API_KEY) to be searchable again.

    python backend/scripts/purge_fake_vectors.py          # report only
    python backend/scripts/purge_fake_vectors.py --delete # actually delete
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.clients import pinecone_index  # noqa: E402

_UNIT = 32  # sha256 digest length that _deterministic_vector tiled


def is_fabricated(values: list[float]) -> bool:
    """True if the vector is a tiled 32-float unit (the fallback's signature)."""
    if len(values) <= _UNIT:
        return False
    return all(abs(values[i] - values[i % _UNIT]) < 1e-9 for i in range(len(values)))


def main() -> int:
    delete = "--delete" in sys.argv
    index = pinecone_index()

    ids: list[str] = []
    for page in index.list(limit=100):
        ids.extend(page)
    if not ids:
        print("Index is empty.")
        return 0

    bad: list[str] = []
    sources: dict[str, int] = {}
    for start in range(0, len(ids), 100):
        res = index.fetch(ids=ids[start : start + 100])
        for cid, vec in (res.vectors or {}).items():
            if is_fabricated(list(vec.values or [])):
                bad.append(cid)
                src = (vec.metadata or {}).get("source", "unknown")
                sources[src] = sources.get(src, 0) + 1

    print(f"Scanned {len(ids)} vectors; {len(bad)} fabricated.")
    for src, n in sorted(sources.items()):
        print(f"  {src}: {n}")

    if not bad:
        return 0
    if not delete:
        print("\nRe-run with --delete to remove them, then re-upload those documents.")
        return 0

    for start in range(0, len(bad), 100):
        index.delete(ids=bad[start : start + 100])
    print(f"\nDeleted {len(bad)} fabricated vectors. Re-upload the documents listed above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
