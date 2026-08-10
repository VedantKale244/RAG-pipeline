# 🌊 Neuro-Adaptive GraphRAG Platform
> **An Intelligent, Self-Learning Enterprise RAG System Powered by Vector Search, Knowledge Graphs, and Adaptive Feedback Loops.**

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Next.js](https://img.shields.io/badge/next.js-14-black.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688.svg)
![Neo4j](https://img.shields.io/badge/Neo4j-GraphRAG-008CC1.svg)

---

## 🌟 Overview: What Makes This Special?

**Neuro-Adaptive GraphRAG** is not just another standard document Q&A bot. Traditional RAG systems rely solely on vector search, which often misses the complex relationships, context, and multi-hop connections hidden across enterprise documents.

This project bridges **semantic vector search (Pinecone)** with a **structured Knowledge Graph (Neo4j)** and introduces a **self-improving feedback loop**. Every question answered, citation verified, and user feedback received helps the system dynamically reweight graph connections—meaning the intelligence gets smarter with every interaction.

Whether you're exploring complex domain documents, inspecting multi-hop graph entities in real time, or analyzing golden-set benchmark performance, **Neuro-Adaptive GraphRAG** delivers precise, citeable answers with speed and transparency.

---

## 🚀 Key Highlights & Features

### 🔍 1. Hybrid Multi-Hop Retrieval
- **Pinecone Vector Search**: Instantly retrieves semantically similar passages using Cohere 1024-dimensional embeddings.
- **Neo4j Graph Expansion**: Expands search candidates across multi-hop entity relationships to surface hidden, cross-document context.
- **Cohere Cross-Encoder Reranking**: Filters and scores candidate passages with Cohere Rerank v3 to guarantee maximum accuracy.

### 🧠 2. Adaptive Learning Loop
- **RAGAS Benchmark Evaluation**: Automatically evaluates answer faithfulness, relevancy, and context precision.
- **GraphSAGE Edge Reweighting**: Feedback loops dynamically adjust graph edge weights so high-performing factual connections receive higher priority in future queries.

### 🔒 3. Enterprise Security & Privacy
- **Isolated Sessions**: Instant guest access with auto-expiring temporary vector/graph data.
- **User Authentication**: Complete email registration, 6-digit OTP verification, and authentic Google OAuth login.
- **Thread Isolation**: Multi-tenant isolation ensuring conversation threads and data stay strictly private.

### 🎨 4. Ultra-Modern Aesthetic
- **Ocean Blue Glassmorphic UI**: Beautiful, responsive interface designed with Next.js 14 and TailwindCSS.
- **Real-Time Physics Graph Visualizer**: Interactive HTML5 Canvas visualizer to explore entities, relationships, and graph paths live.

---

## 🛠️ Technology Stack

| Domain | Technology |
| :--- | :--- |
| **Frontend UI** | Next.js 14 (App Router), React, TailwindCSS, Lucide Icons, Canvas 2D Physics |
| **Backend API** | FastAPI, Python 3.11, Pydantic v2, Starlette |
| **Vector Database** | Pinecone Serverless (`embed-english-v3.0`, 1024-dim) |
| **Knowledge Graph** | Neo4j Graph Database (Cypher & APOC) |
| **LLM & Embeddings** | Cohere API (`command-a-03-2025` / `rerank-english-v3.0`) |
| **Database & Sessions** | SQLite (WAL mode) with argon2/pbkdf2 password hashing |
| **Evaluation & Tracing** | RAGAS Framework + LangSmith Tracing |

---

## 🚦 Getting Started

### 1. Prerequisites
- **Python 3.11+**
- **Node.js 18+**
- **Docker** (for running Neo4j locally)

### 2. Quick Setup

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
cd YOUR_REPOSITORY

# 1. Start Neo4j via Docker
docker compose up -d neo4j

# 2. Configure Environment Variables
cp .env.example .env

# 3. Setup & Start Backend API
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 4. Setup & Start Frontend UI (in a new terminal)
cd ../frontend
npm install
npm run dev
```

Visit `http://localhost:3000` to start exploring! 🚀

---

## 🧪 Testing & Quality Assurance

Run the comprehensive test suite (including 200+ unit, integration, and security verification tests):

```bash
cd backend
pytest -v
```

---

## 📄 License
Distributed under the MIT License. See `LICENSE` for more information.
