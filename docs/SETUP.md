# Setup & Run Guide

## 1. Prerequisites

- Python 3.11+
- Node.js 20+
- Docker (for Neo4j)
- API keys: Groq, Pinecone, Cohere, LangSmith

## 2. Configure

```bash
cp .env.example .env
# edit .env and paste your real keys
```

## 3. Start Neo4j

```bash
docker compose up -d neo4j
# Neo4j browser: http://localhost:7474  (user: neo4j)
```

## 4. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Check it: `curl http://localhost:8000/health`

> The Pinecone index is created automatically on first use with the dimension of
> `embed-english-v3.0` (1024). Change `COHERE_EMBED_MODEL`/`COHERE_EMBED_DIM` together
> if you swap the embedding model — an existing index keeps its old dimension, so a
> model swap needs a new index name.

## 5. Frontend

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
# UI: http://localhost:3000
```

## 6. Try the full loop

1. **Upload** → ingest `examples/sample.txt`. Watch the chunk/entity/relationship counts.
2. **Chat** → ask *"How does the adaptive loop use RAGAS feedback?"* with graph expansion
   on. Inspect citations (graph-sourced ones are tagged) and the LangSmith trace link.
3. **Knowledge Graph** → see the extracted entities and current edge weights.
4. **Evaluation** → paste `examples/golden_set.json`, run RAGAS. The scores reweight the
   graph edges; re-open the Graph tab to see the updated weights.

## Run everything in Docker

```bash
docker compose --profile full up --build
```

## Architecture recap

| Stage            | Module                              |
| ---------------- | ----------------------------------- |
| Ingestion        | `backend/app/core/ingestion.py`     |
| Vector store     | `backend/app/core/vectorstore.py`   |
| Knowledge graph  | `backend/app/core/graphrag.py`      |
| Retrieval+Rerank | `backend/app/core/retrieval.py`     |
| Generation       | `backend/app/core/generation.py`    |
| Adaptive loop    | `backend/app/core/adaptive.py`      |
| Evaluation       | `backend/app/eval/ragas_eval.py`    |
| Observability    | `backend/app/observability.py`      |

## Troubleshooting

- **`API offline` banner** — backend isn't running on `:8000`, or CORS origin mismatch
  (`BACKEND_CORS_ORIGINS` must include `http://localhost:3000`).
- **Graph tab empty** — you haven't ingested a document yet, or Neo4j isn't up.
- **Eval errors** — RAGAS needs the Gemini key; ensure the golden set is valid JSON.
