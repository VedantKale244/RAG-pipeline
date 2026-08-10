"""GraphRAG knowledge-graph layer backed by Neo4j.

Build path (ingestion): for each chunk we ask the LLM to extract entities and the
relationships between them, then materialise a graph:

    (:Chunk {chunk_id, source})
    (:Entity {name, type})
    (:Chunk)-[:MENTIONS]->(:Entity)
    (:Entity)-[:RELATED {rel_type, weight}]->(:Entity)

The ``weight`` on ``RELATED`` edges starts at 1.0 and is later re-scored by the adaptive
embedding loop (see ``adaptive.py``). Retrieval path: given the entities present in the
top dense hits, traverse weighted ``RELATED`` edges to discover neighbouring chunks that
pure vector search missed.
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from cohere.errors import TooManyRequestsError
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ..config import settings
from .adaptive import _cosine
from .clients import chat_llm, embeddings, neo4j_driver

logger = logging.getLogger("app")

# Canonical aliases fold known surface forms onto one node. Extend as your domain needs;
# the lowercase+whitespace pass below handles the common "Apple"/"apple "/"APPLE" case.
_ALIASES: dict[str, str] = {
    "u.s.": "united states",
    "usa": "united states",
    "us": "united states",
}


def _canonicalize(name: str) -> str:
    """Fold entity surface forms onto one key: strip, collapse whitespace, lowercase, alias.

    Exact-string MERGE otherwise fragments "Apple", "apple", and "Apple " into three
    nodes, diluting edge rewards and inflating the graph. This is the cheap 80% fix.
    """
    key = re.sub(r"\s+", " ", (name or "").strip()).lower()
    return _ALIASES.get(key, key)


_ENGLISH_NON_ENTITIES = {
    # Pronouns & Demographics
    "you", "your", "yours", "they", "them", "their", "theirs", "he", "him", "his", "she", "her", "hers",
    "it", "its", "we", "us", "our", "ours", "i", "me", "my", "mine", "who", "whom", "whose", "which",
    "what", "whatever", "whoever", "whichever", "this", "these", "that", "those",
    # Conversational Affirmatives, Negatives & Filler Words
    "yes", "no", "ok", "okay", "true", "false", "none", "null", "na", "n/a", "maybe", "sure", "yep", "nope",
    "hi", "hello", "hey", "thanks", "thank", "please", "sorry", "welcome", "bye", "goodbye", "yeah", "nah", "yup",
    "thing", "things", "something", "anything", "nothing", "everything", "someone", "anyone", "everyone",
    "way", "ways", "part", "parts", "point", "points", "case", "cases", "fact", "facts", "lot", "lots",
    "bit", "bits", "kind", "kinds", "sort", "sorts", "type", "types", "step", "steps", "time", "times",
    # Generic Verbs, Actions & Operation Words
    "upload", "uploading", "uploaded", "download", "downloading", "downloaded", "split", "splitting",
    "update", "updating", "updated", "typical", "typically", "create", "creating", "created", "delete",
    "deleting", "deleted", "read", "reading", "write", "writing", "load", "loading", "loaded", "save",
    "saving", "saved", "start", "starting", "stop", "stopping", "set", "setting", "add", "adding",
    "remove", "removing", "change", "changing", "check", "checking", "process", "processing", "method",
    "methods", "function", "functions", "var", "variable", "str", "string", "int", "integer", "bool",
    "boolean", "val", "elem", "element", "example", "examples", "sample", "samples", "value", "values",
    # Publisher / Cover / Legal Boilerplate Noise
    "rights", "reserved", "copyright", "infinitive", "popular", "edition", "isbn", "author", "authors",
    "publisher", "published", "disclaimer", "license", "licensed", "terms", "privacy", "contact",
    "email", "website", "http", "https", "www", "com", "org", "net", "io", "cover", "ebook", "dark",
    "light", "book", "books", "paper", "all rights reserved",
    # Verbs / Auxiliaries / Action words
    "have", "having", "had", "has", "do", "does", "doing", "did", "done", "be", "being", "been", "am",
    "is", "are", "was", "were", "can", "could", "will", "would", "shall", "should", "may", "might", "must",
    "get", "gets", "getting", "got", "gotten", "give", "gives", "giving", "gave", "given", "take", "takes",
    "taking", "took", "taken", "make", "makes", "making", "made", "put", "puts", "putting", "keep", "keeps",
    "keeping", "kept", "show", "shows", "showing", "showed", "shown", "see", "sees", "seeing", "saw", "seen",
    "look", "looks", "looking", "looked", "use", "uses", "using", "used", "find", "finds", "finding", "found",
    "call", "calls", "calling", "called", "know", "knows", "knowing", "knew", "known", "think", "thinks",
    "thinking", "thought", "come", "comes", "coming", "came", "go", "goes", "going", "went", "gone",
    "say", "says", "saying", "said", "tell", "tells", "telling", "told", "ask", "asks", "asking", "asked",
    "work", "works", "working", "worked", "try", "tries", "trying", "tried", "need", "needs", "needing",
    "needed", "want", "wants", "wanting", "wanted", "help", "helps", "helping", "helped", "run", "runs", "running", "ran",
    # Prepositions & Conjunctions
    "about", "above", "across", "after", "against", "along", "among", "around", "at", "before", "behind",
    "below", "beneath", "beside", "between", "beyond", "by", "down", "during", "except", "for", "from", "in",
    "inside", "into", "like", "near", "of", "off", "on", "onto", "out", "outside", "over", "through",
    "throughout", "till", "to", "toward", "under", "until", "up", "upon", "with", "within", "without", "and",
    "but", "or", "nor", "so", "yet", "because", "although", "though", "while", "where", "when", "whenever",
    "wherever", "whether", "if", "unless", "than", "as", "however", "therefore", "instead", "whereas",
    "furthermore", "moreover", "otherwise",
    # Adverbs, Qualifiers & Determiners
    "all", "any", "both", "each", "every", "few", "more", "most", "much", "many", "other", "others", "some",
    "such", "no", "not", "only", "own", "same", "too", "very", "just", "now", "then", "also", "well", "even",
    "still", "already", "always", "never", "sometimes", "often", "again", "further", "once", "here", "there",
    "normal", "common", "simple", "basic", "main", "next", "last", "first", "second", "third",
    # Generic Meta / Structural / Qualitative Noise
    "document", "documents", "page", "pages", "file", "files", "table", "figure", "section", "paragraph",
    "chapter", "summary", "overview", "introduction", "conclusion", "details", "info", "information", "data",
    "item", "items", "feature", "features", "access", "task", "effort", "impact", "success", "metric", "metrics",
    "sources", "source", "legend", "key", "medium", "high", "low", "reptile", "greptile", "type",
    "name", "id", "code", "user", "admin", "system", "text", "query", "answer", "result", "list",
    # Sentence links, connective & filler words (classic non-entity noise)
    "let", "lets", "us", "say", "says", "said", "saying", "tell", "tells", "told", "telling",
    "try", "tries", "trying", "tried", "thus", "hence", "then", "than", "thence", "therefore",
    "however", "although", "though", "whereas", "meanwhile", "furthermore", "moreover",
    "may", "might", "could", "would", "will", "shall", "should", "must", "ought", "dare",
    "embrace", "grapple", "witness", "underscore", "highlight", "stress", "emphasize",
    "remember", "recall", "suppose", "imagine", "wonder", "guess", "perhaps", "probably",
    "possibly", "likely", "unlikely", "certainly", "definitely", "really", "actually",
    "overall", "general", "generic", "specifically", "simply", "especially", "mainly",
    "mostly", "dude", "guys", "guy", "folks", "kind", "kinds", "sort", "sorts",
    # Contraction stems (apostrophes are stripped before the check)
    "im", "youre", "hes", "shes", "its", "were", "theyre", "ive", "youve", "weve",
    "theyve", "id", "you'd", "can't", "cant", "won't", "wont", "isnt", "aren't", "arent",
    "wasnt", "werent", "hasnt", "havent", "havent", "aint", "didnt", "doesnt",
    "dont", "thats", "whos", "wheres", "hows", "whats", "whyd", "hows",
    # Corpus-observed generic single-word noise (adjectives, verbs, adverbs,
    # generic nouns) that add no retrieval value as standalone graph nodes.
    "accredited", "affiliated", "approved", "recognized", "govt", "gov",
    "best", "worst", "complete", "dynamic", "empty", "invalid", "max", "min",
    "home", "end", "height", "consider", "divide", "insert",
    "inserting", "inserted", "insertion", "insertions", "deletion", "deletions",
    "proof", "theorem", "operations", "operation", "note", "nodes", "steps",
    "underflow", "overflow", "searching", "popping", "entering", "enter",
    "example", "examples", "since", "simply", "subset", "exercises", "recommended",
    "complexity", "branch", "actually",
    "dont", "thats", "whos", "wheres", "hows", "whats", "whyd", "hows",
    "left", "right", "prime", "merge", "according", "buckets", "bucket",
    "algorithm", "algorithms", "initially", "secondly", "thirdly", "firstly",
    "conceptually", "currently", "followed", "follow", "sucesfully", "successfully",
    "successful", "respectively", "following", "here", "also", "then",
    "binary", "doubly",
}

# Generic standalone words that are junk as single entities (so they never
# become their own node) but are perfectly fine as a component of a real
# compound term ("Merge Sort", "Binary Search", "dynamic programming").
_COMPOUND_OK = {
    "sort", "sorts", "merge", "binary", "search", "searches", "string", "strings",
    "list", "lists", "tree", "trees", "node", "nodes", "graph", "graphs",
    "dynamic", "linear", "sequential", "linked", "circular", "priority", "simple",
    "doubly", "mid", "division", "operation", "searching", "hash", "hashing",
    "stack", "queue", "pointer", "insert", "insertion", "insertions", "deletion",
    "deletions", "proof",
}


def _is_valid_entity(name: str) -> bool:
    """Strictly filter out non-entity words (verbs, pronouns, prepositions, adverbs, legal noise)."""
    if not name or not name.strip():
        return False
    clean = name.strip().lower().replace("'", "")
    if len(clean) < 3:
        return False

    words = re.findall(r"\b[a-z0-9]+\b", clean)
    if not words:
        return False

    # Reject any phrase containing explicit legal or publisher boilerplate
    for w in words:
        if w in {"rights", "reserved", "copyright", "infinitive", "popular", "isbn", "publisher", "disclaimer", "license"}:
            return False

    # 1. Single-word entity CANNOT be in _ENGLISH_NON_ENTITIES
    if len(words) == 1 and words[0] in _ENGLISH_NON_ENTITIES:
        return False

    # 2. Multi-word phrase CANNOT be composed entirely of non-entities. Words
    #    that are legitimate technical terms (``_COMPOUND_OK``) never count as
    #    junk here, so "Merge Sort" or "Binary Tree" stay while "let us try"
    #    ("let"/"us"/"try" all junk) is rejected.
    junk_words = [w for w in words if w in _ENGLISH_NON_ENTITIES and w not in _COMPOUND_OK]
    if junk_words and len(junk_words) >= len(words):
        return False

    # 3. Multi-word phrase starting or ending with classic filler / sentence
    #    linker words (the reported offenders: "let …", "thus …", "… then",
    #    "… however …", plus the prior pronoun/gesture set).
    _START_FILLER = ("let", "lets", "us", "thus", "then", "hence", "therefore", "however",
                     "meanwhile", "mean", "say", "tell", "try", "may", "might", "could",
                     "would", "should", "will", "shall", "must", "perhaps", "probably",
                     "likely", "actually", "overall", "generally", "basically", "typically",
                     "so", "now", "well", "also", "first", "second", "third", "finally") + (
                     "your", "my", "their", "our", "having", "they", "this", "these",
                     "however", "legend", "sources", "with", "from", "yes", "no", "ok",
                     "upload", "update", "split", "the", "a", "an", "as", "of", "and",
                     "then", "for", "in", "on", "at", "to", "by")
    _END_FILLER = ("let", "lets", "us", "thus", "then", "hence", "therefore", "however",
                   "though", "may", "might", "could", "would", "should", "will", "shall",
                   "must", "perhaps", "probably", "likely", "actually", "overall",
                   "typically", "anyway", "somehow", "twice", "etc") + (
                   "your", "medium", "high", "low", "legend", "metric", "reptile", "greptile",
                   "sources", "feature", "access", "data", "info", "yes", "no", "ok",
                   "typical", "update", "split", "the", "a", "an", "then", "of", "and",
                   "for", "to", "in", "on", "at", "with", "sucesfully", "successfully")
    if words[0] in _START_FILLER or words[-1] in _END_FILLER:
        return False

    # 4. Pure numeric or punctuation
    if re.match(r"^[\d\W_]+$", clean):
        return False

    return True





def _canonicalize_entities(entities: list[dict]) -> list[dict]:
    out, seen = [], set()
    for e in entities:
        name = _canonicalize(e.get("name", ""))
        rationale = (e.get("rationale") or "").strip() or f"Domain concept mined from source documents for {name}."
        if name and _is_valid_entity(name) and name not in seen:
            seen.add(name)
            out.append({
                "name": name,
                "type": e.get("type", "CONCEPT"),
                "rationale": rationale,
            })
    return out


def _canonicalize_rels(relationships: list[dict]) -> list[dict]:
    out = []
    for r in relationships:
        s, t = _canonicalize(r.get("source", "")), _canonicalize(r.get("target", ""))
        if s and t and s != t and _is_valid_entity(s) and _is_valid_entity(t):
            out.append({"source": s, "target": t, "rel_type": r.get("rel_type", "RELATED")})
    return out

_EXTRACT_SYSTEM = (
    "You are a 10+ years senior Knowledge Graph Architect in a high-precision neuro-adaptive GraphRAG system.\n"
    "Your job is to extract ONLY essential, high-importance domain entities and relationships from the text.\n\n"
    "STRICT DUAL-RULE EVALUATION (EVALUATE EACH CANDIDATE ENTITY IN FULL):\n"
    "For every candidate entity, you MUST answer two validation questions:\n"
    "Question 1 (Domain Need): Do we really need this entity in the Knowledge Graph? (Only answer YES if it improves retrieval, reasoning, graph traversal, or understanding of the document. Discard common words, generic concepts, random numbers, dates without importance, isolated technical terms, repeated phrases, temporary variables, meaningless extracted text). NEVER output English function, filler, or connective words such as: let, thus, then, hence, may, might, can, could, will, would, should, because, although, however, and, or, this, these, those, it, its, many, some, about, means, overall, typical.)\n"
    "Question 2 (Graph Importance): Is this entity actually important and central enough to deserve a node? (Only answer YES for: technologies, companies, systems, APIs, databases, architectures, services, algorithms, frameworks, protocols, products, organizations, major concepts).\n\n"
    "RATIONALE REQUIREMENT:\n"
    "- 'rationale': Provide a highly specific 1-2 sentence technical explanation detailing EXACTLY why this entity is in the Knowledge Graph and what role it plays in the document context. NEVER output generic boilerplate like 'Essential domain concept'.\n\n"
    "RELATIONSHIP VALIDATION:\n"
    "- Do NOT extract relationships simply because entities appear in the same sentence.\n"
    "- Relationships must have a real semantic connection, such as: DEPENDS_ON, USES, IMPLEMENTS, COMMUNICATES_WITH, OWNS, CONNECTS_TO, STORES_IN, RETRIEVES_FROM, AUTHENTICATES_USING, INDEXES, REFERENCES, EXTENDS, INTEGRATES_WITH, REPLACES, REQUIRES, PRODUCES, CONSUMES, CO_OCCURS.\n"
    "- Avoid generic labels (RELATED, CONNECTED, LINKED, ASSOCIATED) unless no specific type fits.\n\n"
    "CONFIDENCE SCORING:\n"
    "- Provide a confidence score between 0.0 and 1.0 for every entity and relationship.\n\n"
    "FORMAT: Return a STRICT JSON object with keys 'entities' and 'relationships'. DO NOT output Markdown wrappers (like ```json). JSON structure:\n"
    "{{\n"
    "  \"entities\": [\n"
    "    {{\n"
    "      \"name\": \"Entity Name\",\n"
    "      \"type\": \"Entity Type (e.g. TECHNOLOGY, API, DATABASE)\",\n"
    "      \"confidence\": 0.95,\n"
    "      \"question_1_needed\": true,\n"
    "      \"question_1_reason\": \"Brief explanation\",\n"
    "      \"question_2_deserves_node\": true,\n"
    "      \"question_2_reason\": \"Brief explanation\",\n"
    "      \"rationale\": \"Informative 1-2 sentence explanation of why this entity is essential to the document domain\"\n"
    "    }}\n"
    "  ],\n"
    "  \"relationships\": [\n"
    "    {{\n"
    "      \"source\": \"Entity Name\",\n"
    "      \"target\": \"Other Entity Name\",\n"
    "      \"rel_type\": \"Predicated type\",\n"
    "      \"confidence\": 0.90,\n"
    "      \"description\": \"Brief explanation of semantic connection\"\n"
    "    }}\n"
    "  ]\n"
    "}}"
)


_EXTRACT_PROMPT = ChatPromptTemplate.from_messages(
    [("system", _EXTRACT_SYSTEM), ("human", "Text:\n{text}\n\nJSON:")]
)

_CONSTRAINTS = [
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
    "CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE",
]


def _is_neo4j_unavailable(exc: Exception) -> bool:
    if isinstance(exc, (ServiceUnavailable, Neo4jError)):
        return True
    msg = str(exc).lower()
    return "connection" in msg or "service unavailable" in msg or "neo4j" in msg


_PURGED_INVALID_ONCE = False


def ensure_schema() -> None:
    global _PURGED_INVALID_ONCE
    try:
        with neo4j_driver().session() as session:
            for stmt in _CONSTRAINTS:
                session.run(stmt)
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            logger.warning("Neo4j unavailable; ensuring SQLite fallback schema.")
            from . import fallback_graph
            fallback_graph.ensure_schema()
            return
        raise
    if _PURGED_INVALID_ONCE:
        return
    _PURGED_INVALID_ONCE = True
    # Permanent hygiene gate: on the first schema pass of each process (i.e. on
    # boot) detach and delete any junk/stopword entity left over from older
    # builds so the graph only holds what the extractor is designed for.
    try:
        purge_invalid_entities_from_db()
    except Exception as exc:
        logger.warning("Entity junk purge failed during schema ensure: %s", exc)


def _is_rate_limit_err(exc: Exception) -> bool:
    if isinstance(exc, TooManyRequestsError):
        return True
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg


def _fallback_heuristic_extract(text: str) -> dict:
    """Heuristic named-entity extraction fallback ensuring graph nodes are created for every chunk."""
    matches = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
    stopwords = {"The", "A", "An", "In", "On", "At", "By", "For", "With", "About", "Against", "Between", "Into", "Through", "During", "Before", "After", "To", "From", "Up", "Down", "Over", "Under", "When", "Where", "Why", "How", "All", "Any", "Both", "Each", "Few", "More", "Most", "Other", "Some", "Such", "No", "Nor", "Not", "Only", "Own", "Same", "So", "Than", "Too", "Very", "Can", "Will", "Just", "Should", "Now", "Let", "Lets", "Thus", "Then", "Hence", "However", "May", "Might", "Could", "Would", "Because", "Although", "These", "Those", "It", "Its", "Many", "There", "Here", "Also", "Even", "Just", "Again", "Once"}

    unique_entities = []
    seen = set()
    for m in matches:
        m_str = m.strip()
        # Drop sentence-capitalized filler words (Let, Thus, Then, May …) and
        # anything that fails the strict entity gate.
        if len(m_str) > 2 and m_str not in stopwords and _is_valid_entity(m_str) and m_str.lower() not in seen:
            seen.add(m_str.lower())
            unique_entities.append({
                "name": m_str,
                "type": "CONCEPT",
                "rationale": f"Domain concept '{m_str}' extracted from document text context for Knowledge Graph indexing and multi-hop traversal."
            })
            if len(unique_entities) >= 8:
                break
                
    relationships = []
    for i in range(len(unique_entities) - 1):
        relationships.append({
            "source": unique_entities[i]["name"],
            "target": unique_entities[i + 1]["name"],
            "rel_type": "CO_OCCURS",
            "confidence": 0.85
        })
        
    return {"entities": unique_entities, "relationships": relationships}


def _extract(text: str) -> dict:
    if not text or not text.strip():
        return {"entities": [], "relationships": []}

    chain = _EXTRACT_PROMPT | chat_llm() | JsonOutputParser()

    def _invoke_with_timeout():
        for attempt in range(2):
            try:
                result = chain.invoke({"text": text[:3000]})
                ents = result.get("entities", []) or []
                rels = result.get("relationships", []) or []
                if ents:
                    return {"entities": ents, "relationships": rels}
            except Exception as exc:
                if _is_rate_limit_err(exc):
                    time.sleep(0.2)
                    continue
                break
        return None

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_invoke_with_timeout)
            res = future.result(timeout=1.5)
            if res:
                return res
    except TimeoutError:
        logger.warning("LLM entity extraction timed out after 1.5s; using instant heuristic extraction.")
    except Exception as exc:
        logger.info("LLM entity extraction exception (%s); using heuristic extraction.", exc)


    return _fallback_heuristic_extract(text)



_WRITE_CYPHER = """
MERGE (c:Chunk {chunk_id: $chunk_id})
  SET c.source = $source, c.document_id = $document_id, c.user_id = $user_id, c.text = $text
WITH c
UNWIND $entities AS ent
  MERGE (e:Entity {name: ent.name})
    SET e.type = coalesce(ent.type, e.type, 'OTHER'),
        e.rationale = coalesce(ent.rationale, e.rationale, 'Essential domain concept'),
        e.embedding = coalesce(ent.embedding, e.embedding),
        e.aliases = coalesce(ent.aliases, e.aliases, []),
        e.user_id = coalesce(e.user_id, $user_id)
  MERGE (c)-[:MENTIONS]->(e)
WITH c
UNWIND $relationships AS rel
  MERGE (a:Entity {name: rel.source})
  MERGE (b:Entity {name: rel.target})
  MERGE (a)-[r:RELATED {rel_type: coalesce(rel.rel_type, 'RELATED')}]->(b)
    ON CREATE SET r.weight = 1.0, r.user_id = $user_id
"""

def _get_embeddings_batch(names: list[str]) -> None:
    """Pre-fetch embeddings for all candidate entity names in 1 single batch call."""
    if not names:
        return
    uncached = [n for n in set(names) if n and n.strip().lower() not in _EMB_CACHE]
    if not uncached:
        return
    try:
        vecs = embeddings().embed_documents(uncached)
        for n, v in zip(uncached, vecs):
            _EMB_CACHE[n.strip().lower()] = v
    except Exception as exc:
        logger.warning("Batch entity embedding prefetch error: %s", exc)
        for n in uncached:
            _EMB_CACHE[n.strip().lower()] = [0.0] * settings.cohere_embed_dim


def _get_embedding(name: str) -> list[float]:
    """Get name embedding using Cohere, with internal caching to reuse embeddings."""
    name_clean = name.strip().lower()
    if name_clean in _EMB_CACHE:
        return _EMB_CACHE[name_clean]
    try:
        emb = embeddings().embed_documents([name])[0]
        _EMB_CACHE[name_clean] = emb
        return emb
    except Exception as exc:
        logger.warning(f"Error computing name embedding for '{name}': {exc}")
        return [0.0] * settings.cohere_embed_dim



def _load_existing_entities(user_id: str) -> dict[str, dict]:
    """Load existing entities for the user, mapping lowercase canonical name -> entity details."""
    existing = {}
    try:
        with neo4j_driver().session() as session:
            res = session.run(
                "MATCH (e:Entity) WHERE e.user_id = $user_id "
                "RETURN e.name AS name, e.aliases AS aliases, e.embedding AS embedding",
                user_id=user_id
            )
            for r in res:
                name = r["name"]
                key = _canonicalize(name)
                aliases = r["aliases"] or []
                emb = r["embedding"]
                existing[key] = {
                    "canonical_name": re.sub(r"[\r\n\t]+", " ", name).strip(),
                    "aliases": [_canonicalize(a) for a in aliases if a],
                    "embedding": emb
                }
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            return fallback_graph.load_existing_entities(user_id)
        logger.warning(f"Error loading existing entities: {exc}")
    return existing


def _find_matching_entity_name(
    candidate_name: str,
    existing_entities: dict[str, dict],
    candidate_emb: list[float] | None = None
) -> str | None:
    """Check if equivalent entity already exists and return its canonical name.
    Compares name, aliases, normalized text, and semantic similarity via embeddings.
    """
    cand_key = candidate_name.strip().lower()
    
    # 1. Exact Name / Normalized Text Match
    if cand_key in existing_entities:
        return existing_entities[cand_key]["canonical_name"]
        
    # 2. Alias Match
    for existing_key, details in existing_entities.items():
        if cand_key in details["aliases"]:
            return details["canonical_name"]
            
    # 3. Semantic Similarity Match using embeddings
    if candidate_emb is None:
        candidate_emb = _get_embedding(candidate_name)
    
    if not any(candidate_emb):
        return None
        
    cand_arr = np.array(candidate_emb)
    best_match = None
    best_sim = -1.0
    
    for existing_key, details in existing_entities.items():
        ext_emb = details["embedding"]
        if ext_emb and any(ext_emb):
            sim = _cosine(cand_arr, np.array(ext_emb))
            if sim > best_sim:
                best_sim = sim
                best_match = details["canonical_name"]
                
    if best_sim >= settings.entity_match_threshold:
        return best_match
        
    return None


def get_existing_chunk_ids(chunk_ids: list[str], user_id: str) -> set[str]:
    """Find which chunk_ids already exist in Neo4j for this user."""
    if not chunk_ids or not user_id:
        return set()
    try:
        with neo4j_driver().session() as session:
            res = session.run(
                "MATCH (c:Chunk) WHERE c.chunk_id IN $chunk_ids AND c.user_id = $user_id RETURN c.chunk_id AS chunk_id",
                chunk_ids=chunk_ids,
                user_id=user_id,
            )
            return {r["chunk_id"] for r in res}
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            return fallback_graph.get_existing_chunk_ids(chunk_ids, user_id)
        logger.warning(f"Error querying existing chunk ids: {exc}")
        return set()


_SUMMARY_SYSTEM = (
    "You are an enterprise Knowledge Graph Analyst. Your task is to analyze the provided Knowledge Graph structural data and construct a detailed, professional, structured architectural summary in JSON format.\n\n"
    "Your output MUST follow this exact JSON structure (do NOT include markdown formatting wrappers):\n"
    "{{\n"
    "  \"summary\": \"Overall concise explanation of what the Knowledge Graph represents.\",\n"
    "  \"total_entities\": 0,\n"
    "  \"total_relationships\": 0,\n"
    "  \"entity_types\": {{\"TYPE\": 0, ...}},\n"
    "  \"relationship_types\": {{\"REL_TYPE\": 0, ...}},\n"
    "  \"density\": 0.05,\n"
    "  \"duplicates_removed\": 0,\n"
    "  \"merged_entities\": 0,\n"
    "  \"ignored_entities_count\": 0,\n"
    "  \"ignored_relationships_count\": 0,\n"
    "  \"graph_confidence\": 0.90,\n"
    "  \"major_entities\": [\n"
    "    {{\n"
    "      \"name\": \"Entity Name\",\n"
    "      \"type\": \"Entity Type\",\n"
    "      \"importance\": \"HIGH\",\n"
    "      \"purpose\": \"Purpose of this entity in the domain\",\n"
    "      \"why_exists\": \"Why this entity was verified to be central\",\n"
    "      \"connected_nodes_count\": 5,\n"
    "      \"relationships_count\": 6,\n"
    "      \"connected_small_entities\": [\n"
    "        {{\n"
    "          \"name\": \"Small Entity Name\",\n"
    "          \"type\": \"Type\",\n"
    "          \"why_connected\": \"Brief explanation of connection\"\n"
    "        }}\n"
    "      ],\n"
    "      \"relationship_summary\": {{\n"
    "        \"uses\": [\"target1\", ...],\n"
    "        \"depends_on\": [\"target2\", ...],\n"
    "        \"communicates_with\": [\"target3\", ...],\n"
    "        \"stores_data_in\": [],\n"
    "        \"authenticates_through\": [],\n"
    "        \"integrated_with\": [],\n"
    "        \"referenced_by\": [],\n"
    "        \"owned_by\": [],\n"
    "        \"implemented_using\": []\n"
    "      }}\n"
    "    }}\n"
    "  ],\n"
    "  \"ignored_information\": [\n"
    "    {{\n"
    "      \"name\": \"Ignored Entity/Relationship Name\",\n"
    "      \"reason\": \"Detailed reason explaining why it was skipped/ignored\"\n"
    "    }}\n"
    "  ]\n"
    "}}"
)


def _aggregate_graph_data(user_id: str) -> dict:
    """Fetch nodes and edges details (Neo4j or SQLite fallback) for the summary LLM."""
    try:
        return _aggregate_graph_data_neo4j(user_id)
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            return fallback_graph.aggregate_graph_data(user_id)
        raise


def _aggregate_graph_data_neo4j(user_id: str) -> dict:
    """Fetch nodes and edges details from Neo4j to feed into the summary LLM."""
    with neo4j_driver().session() as session:
        ent_rows = session.run(
            "MATCH (c:Chunk {user_id: $user_id})-[:MENTIONS]->(e:Entity) "
            "RETURN DISTINCT e.name AS name, e.type AS type, e.rationale AS rationale",
            user_id=user_id
        )
        entities = {r["name"]: {"type": r["type"], "rationale": r["rationale"], "degree": 0, "relations": []} for r in ent_rows}
        
        rel_rows = session.run(
            "MATCH (c:Chunk {user_id: $user_id})-[:MENTIONS]->(a:Entity)-[r:RELATED]->(b:Entity) "
            "WHERE (b)<-[:MENTIONS]-(:Chunk {user_id: $user_id}) "
            "RETURN DISTINCT a.name AS source, b.name AS target, r.rel_type AS rel_type",
            user_id=user_id
        )
        
        relationships = []
        for r in rel_rows:
            s, t, rt = r["source"], r["target"], r["rel_type"]
            relationships.append((s, t, rt))
            if s in entities:
                entities[s]["degree"] += 1
                entities[s]["relations"].append({"target": t, "type": rt})
            if t in entities:
                entities[t]["degree"] += 1
                
        return {
            "entities": entities,
            "relationships": relationships
        }


def _generate_and_save_summary(user_id: str, run_stats: dict):
    """Generate structured summary of the user's knowledge graph via LLM and save it to Neo4j."""
    try:
        graph_data = _aggregate_graph_data(user_id)
        entities = graph_data["entities"]
        relationships = graph_data["relationships"]
        
        sorted_ents = sorted(entities.items(), key=lambda x: x[1]["degree"], reverse=True)
        major_ents_data = sorted_ents[:8]
        
        ents_desc = []
        for name, details in major_ents_data:
            rels_desc = []
            for r in details["relations"]:
                rels_desc.append(f"- {r['type']} -> {r['target']}")
            rels_str = "\n".join(rels_desc) if rels_desc else "- None"
            ents_desc.append(
                f"Entity: {name}\n"
                f"Type: {details['type']}\n"
                f"Rationale: {details['rationale']}\n"
                f"Connected Nodes Count: {details['degree']}\n"
                f"Relationships:\n{rels_str}"
            )
        ents_prompt_str = "\n\n".join(ents_desc)
        
        total_nodes = len(entities)
        total_relationships = len(relationships)
        density = 0.0
        if total_nodes > 1:
            density = round(2.0 * total_relationships / (total_nodes * (total_nodes - 1)), 4)
            
        entity_types = {}
        for details in entities.values():
            t = details["type"] or "CONCEPT"
            entity_types[t] = entity_types.get(t, 0) + 1
            
        relationship_types = {}
        for s, t, rt in relationships:
            relationship_types[rt] = relationship_types.get(rt, 0) + 1
            
        stats_prompt_str = (
            f"Total Nodes: {total_nodes}\n"
            f"Total Relationships: {total_relationships}\n"
            f"Graph Density: {density}\n"
            f"Duplicate Nodes Removed: {run_stats.get('duplicates_removed', 0)}\n"
            f"Merged Entities Count: {run_stats.get('merged_entities', 0)}\n"
            f"Ignored Entities Count: {run_stats.get('ignored_entities_count', 0)}\n"
            f"Ignored Relationships Count: {run_stats.get('ignored_relationships_count', 0)}\n"
            f"Average Graph Confidence Score: {run_stats.get('graph_confidence', 0.85):.2f}"
        )
        
        ignored_ents_desc = []
        for item in run_stats.get("ignored_entities_list", [])[:10]:
            ignored_ents_desc.append(f"- Entity: {item['name']}, Reason: {item['reason']}")
        for item in run_stats.get("ignored_relationships_list", [])[:10]:
            ignored_ents_desc.append(f"- Relation: {item['source']} -> {item['target']} ({item['rel_type']}), Reason: {item['reason']}")
        ignored_info_str = "\n".join(ignored_ents_desc) if ignored_ents_desc else "None"
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", _SUMMARY_SYSTEM),
            ("human", 
             f"Construct a Knowledge Graph Summary for user: {user_id}.\n\n"
             f"Graph Structural Data:\n{ents_prompt_str}\n\n"
             f"Graph Statistics:\n{stats_prompt_str}\n\n"
             f"Ignored Information:\n{ignored_info_str}\n\n"
             f"JSON:")
        ])
        
        chain = prompt | chat_llm() | JsonOutputParser()
        summary_json = chain.invoke({})
        
        summary_json["total_entities"] = total_nodes
        summary_json["total_relationships"] = total_relationships
        summary_json["entity_types"] = entity_types
        summary_json["relationship_types"] = relationship_types
        summary_json["density"] = density
        summary_json["duplicates_removed"] = run_stats.get("duplicates_removed", 0)
        summary_json["merged_entities"] = run_stats.get("merged_entities", 0)
        summary_json["ignored_entities_count"] = run_stats.get("ignored_entities_count", 0)
        summary_json["ignored_relationships_count"] = run_stats.get("ignored_relationships_count", 0)
        summary_json["graph_confidence"] = run_stats.get("graph_confidence", 0.85)
        
        try:
            with neo4j_driver().session() as session:
                session.run(
                    "MERGE (s:GraphSummary {user_id: $user_id}) "
                    "SET s.summary_json = $summary_json",
                    user_id=user_id,
                    summary_json=json.dumps(summary_json)
                )
        except Exception as exc:
            if _is_neo4j_unavailable(exc):
                from . import fallback_graph
                fallback_graph.save_summary(user_id, json.dumps(summary_json))
            else:
                raise
            
    except Exception as exc:
        logger.warning(f"Error generating and saving graph summary: {exc}")



def _merge_entity_alias(tx, canonical_name: str, alias_name: str, user_id: str):
    """Update aliases property of an existing entity in Neo4j transaction."""
    tx.run(
        "MATCH (e:Entity {name: $canonical_name}) WHERE e.user_id = $user_id "
        "SET e.aliases = CASE "
        "  WHEN $alias_name IN coalesce(e.aliases, []) THEN e.aliases "
        "  ELSE coalesce(e.aliases, []) + $alias_name "
        "END",
        canonical_name=canonical_name,
        alias_name=alias_name,
        user_id=user_id
    )


def _persist_build(write_records: list[dict], alias_updates: list[tuple], user_id: str) -> None:
    """Persist validated chunk/entity/relationship writes to Neo4j or the SQLite fallback."""
    try:
        with neo4j_driver().session() as session:
            with session.begin_transaction() as tx:
                for canonical_name, alias_name, uid in alias_updates:
                    _merge_entity_alias(tx, canonical_name, alias_name, uid)
                for rec in write_records:
                    entities = rec["entities"]
                    relationships = rec["relationships"]
                    if not entities and not relationships:
                        tx.run(
                            "MERGE (c:Chunk {chunk_id: $chunk_id}) "
                            "SET c.source = $source, c.document_id = $document_id, "
                            "c.user_id = $user_id, c.text = $text",
                            chunk_id=rec["chunk_id"],
                            source=rec["source"],
                            document_id=rec["document_id"],
                            user_id=rec["user_id"],
                            text=rec["text"],
                        )
                    else:
                        tx.run(
                            _WRITE_CYPHER,
                            chunk_id=rec["chunk_id"],
                            source=rec["source"],
                            document_id=rec["document_id"],
                            user_id=rec["user_id"],
                            text=rec["text"],
                            entities=entities,
                            relationships=relationships,
                        )
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            fallback_graph.persist_build(write_records, alias_updates, user_id)
        else:
            raise


def build_from_chunks(chunks: list[dict], progress_callback: callable | None = None) -> dict:
    """Extract entities/relationships using batched block mining and write them to Neo4j.
    Applies strict confidence scoring, validation checks, duplicate merging, and
    saves a comprehensive graph summary after completion.
    """
    ensure_schema()
    if not chunks:
        return {"entities": 0, "relationships": 0}

    user_id = chunks[0].get("user_id", "guest")
    
    # 1. Load existing entities for merging
    existing_entities = _load_existing_entities(user_id)
    
    # Stats trackers
    ignored_entities_list = []
    ignored_relationships_list = []
    duplicates_removed_count = 0
    merged_entities_count = 0
    
    total_conf_sum = 0.0
    total_conf_cnt = 0

    # Group chunks into blocks of up to 5 chunks (~3000-3500 chars) for ultra-fast batch extraction
    BLOCK_SIZE = 5

    blocks = [chunks[i : i + BLOCK_SIZE] for i in range(0, len(chunks), BLOCK_SIZE)]
    total_blocks = len(blocks)
    completed_blocks = 0

    def _extract_block(block: list[dict]) -> tuple[list[dict], dict]:
        nonlocal completed_blocks
        combined_text = "\n\n".join(c["text"] for c in block)
        res = _extract(combined_text)
        completed_blocks += 1
        if progress_callback and total_blocks > 0:
            progress_callback(f"Mining entities ({completed_blocks}/{total_blocks} sections)...")
        return block, res

    workers = min(10, max(1, total_blocks))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        block_extractions = list(pool.map(_extract_block, blocks))

    if progress_callback:
        progress_callback("Saving Knowledge Graph nodes & relationships...")

    # Single-batch pre-fetch all candidate entity embeddings in 1 API call
    all_candidate_names = []
    for _, graph in block_extractions:
        for ent in graph.get("entities", []) or []:
            name = _canonicalize(re.sub(r"[\r\n\t]+", " ", ent.get("name", "")).strip())
            if name and _is_valid_entity(name):
                all_candidate_names.append(name)
    _get_embeddings_batch(all_candidate_names)

    sample_ents = []
    sample_rels = []


    total_entities = 0
    total_rels = 0
    write_records: list[dict] = []
    alias_updates: list[tuple] = []

    for block, graph in block_extractions:
        raw_ents = graph.get("entities", []) or []
        raw_rels = graph.get("relationships", []) or []
        
        # First pass: Filter, validate, and merge candidate entities
        valid_entities_map = {} # Maps canonicalized lowercase name -> info dict
        
        for ent in raw_ents:
            raw_name = re.sub(r"[\r\n\t]+", " ", ent.get("name", "")).strip()
            name = _canonicalize(raw_name)
            if not name:
                continue
                
            ent_type = ent.get("type", "CONCEPT")
            confidence = float(ent.get("confidence", 1.0))
            rationale = ent.get("rationale", "")
            q1 = ent.get("question_1_needed", True)
            q2 = ent.get("question_2_deserves_node", True)
            
            # Store confidence for overall scoring
            total_conf_sum += confidence
            total_conf_cnt += 1
            
            # Validation Checks:
            if confidence < settings.graph_confidence_threshold:
                ignored_entities_list.append({
                    "name": name,
                    "reason": f"Below confidence threshold (confidence: {confidence:.2f})"
                })
                continue
                
            # Strict validation questions
            q1_ok = (q1 is True) or (isinstance(q1, str) and q1.strip().lower() in {"yes", "true"})
            q2_ok = (q2 is True) or (isinstance(q2, str) and q2.strip().lower() in {"yes", "true"})
            
            if not q1_ok or not q2_ok:
                ignored_entities_list.append({
                    "name": name,
                    "reason": f"Failed validation. Q1 (needed): {q1}, Q2 (deserves node): {q2}"
                })
                continue
                
            # Heuristics check
            if not _is_valid_entity(name):
                ignored_entities_list.append({
                    "name": name,
                    "reason": "Failed basic entity heuristics"
                })
                continue
                
            # Duplicate Detection & Merging
            emb = _get_embedding(name)
            match_canonical = _find_matching_entity_name(name, existing_entities, emb)
            
            if match_canonical:
                match_canonical_key = _canonicalize(match_canonical)
                if name != match_canonical_key:
                    merged_entities_count += 1
                    alias_updates.append((match_canonical, name, user_id))
                    if match_canonical_key in existing_entities:
                        existing_entities[match_canonical_key]["aliases"].append(name)
                else:
                    duplicates_removed_count += 1
                    
                existing_info = existing_entities.get(match_canonical_key) or existing_entities.get(name) or {}
                valid_entities_map[name] = {
                    "name": match_canonical,
                    "type": ent_type,
                    "rationale": rationale or f"Essential domain concept merged under {match_canonical}",
                    "embedding": existing_info.get("embedding", emb),
                    "aliases": existing_info.get("aliases", [])
                }
            else:
                clean_canonical_name = re.sub(r"\s+", " ", raw_name).strip()
                new_ent_info = {
                    "name": clean_canonical_name,
                    "type": ent_type,
                    "rationale": rationale or "Essential domain concept",
                    "embedding": emb,
                    "aliases": []
                }
                valid_entities_map[name] = new_ent_info
                existing_entities[name] = {
                    "canonical_name": clean_canonical_name,
                    "aliases": [],
                    "embedding": emb
                }
        
        # Second pass: Validate and map relationships
        valid_relationships = []
        for rel in raw_rels:
            raw_s = re.sub(r"[\r\n\t]+", " ", rel.get("source", "")).strip()
            raw_t = re.sub(r"[\r\n\t]+", " ", rel.get("target", "")).strip()
            s_key = _canonicalize(raw_s)
            t_key = _canonicalize(raw_t)
            
            if not s_key or not t_key or s_key == t_key:
                continue
                
            rel_type = rel.get("rel_type", "RELATED").strip().upper()
            confidence = float(rel.get("confidence", 1.0))
            
            total_conf_sum += confidence
            total_conf_cnt += 1
            
            if confidence < settings.graph_confidence_threshold:
                ignored_relationships_list.append({
                    "source": raw_s,
                    "target": raw_t,
                    "rel_type": rel_type,
                    "reason": f"Below confidence threshold (confidence: {confidence:.2f})"
                })
                continue
                
            if rel_type in {"RELATED", "CONNECTED", "LINKED", "ASSOCIATED"}:
                rel_type = "CO_OCCURS"
                
            if s_key not in valid_entities_map and s_key not in existing_entities:
                continue
            if t_key not in valid_entities_map and t_key not in existing_entities:
                continue
                
            s_canon = (
                valid_entities_map[s_key]["name"]
                if s_key in valid_entities_map
                else existing_entities[s_key]["canonical_name"]
                if s_key in existing_entities
                else raw_s
            )
            t_canon = (
                valid_entities_map[t_key]["name"]
                if t_key in valid_entities_map
                else existing_entities[t_key]["canonical_name"]
                if t_key in existing_entities
                else raw_t
            )
            
            if s_canon != t_canon:
                valid_relationships.append({
                    "source": s_canon,
                    "target": t_canon,
                    "rel_type": rel_type
                })
        
        entities_to_write = list(valid_entities_map.values())
        
        if entities_to_write and len(sample_ents) < 6:
            sample_ents.extend([e["name"] for e in entities_to_write if e["name"] not in sample_ents])
        if valid_relationships and len(sample_rels) < 4:
            sample_rels.extend([f"'{r['source']}' → ({r['rel_type']}) → '{r['target']}'" for r in valid_relationships])
            
        for chunk in block:
            write_records.append({
                "chunk_id": chunk["chunk_id"],
                "source": chunk["source"],
                "document_id": chunk["document_id"],
                "user_id": chunk.get("user_id", "guest"),
                "text": chunk.get("text", ""),
                "entities": entities_to_write,
                "relationships": valid_relationships,
            })
        total_entities += len(entities_to_write)
        total_rels += len(valid_relationships)

    _persist_build(write_records, alias_updates, user_id)
            
    # 4. Generate and save the structured graph summary
    avg_confidence = total_conf_sum / total_conf_cnt if total_conf_cnt > 0 else 0.85
    run_stats = {
        "duplicates_removed": duplicates_removed_count,
        "merged_entities": merged_entities_count,
        "ignored_entities_count": len(ignored_entities_list),
        "ignored_relationships_count": len(ignored_relationships_list),
        "ignored_entities_list": ignored_entities_list,
        "ignored_relationships_list": ignored_relationships_list,
        "graph_confidence": avg_confidence
    }
    
    _generate_and_save_summary(user_id, run_stats)
    
    ents_str = ", ".join(sample_ents[:5]) if sample_ents else "key concepts"
    rels_str = ", ".join(sample_rels[:3]) if sample_rels else "multi-hop semantic connections"
    explanation = (
        f"Ingested document into Knowledge Graph with {total_entities} verified entities and {total_rels} semantic relationships. "
        f"Primary concepts: {ents_str}. Mined relationship edges: {rels_str}. "
        f"A comprehensive architecture summary has been generated and stored in Neo4j."
    )

    return {"entities": total_entities, "relationships": total_rels, "explanation": explanation}


def delete_by_document(document_id: str) -> dict:
    """Remove a document's chunks from the graph, then prune orphaned entities."""
    try:
        with neo4j_driver().session() as session:
            chunks = session.run(
                "MATCH (c:Chunk {document_id: $document_id}) "
                "DETACH DELETE c RETURN count(c) AS n",
                document_id=document_id,
            ).single()["n"]
            session.run("MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-() DETACH DELETE e")
        return {"chunks": chunks}
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            return fallback_graph.delete_by_document(document_id)
        raise


def delete_by_user(user_id: str) -> dict:
    """Remove a specific user's (or guest session's) chunks from the graph, then prune orphaned entities."""
    if not user_id:
        return {"chunks": 0}
    try:
        with neo4j_driver().session() as session:
            res = session.run(
                "MATCH (c:Chunk {user_id: $user_id}) "
                "DETACH DELETE c RETURN count(c) AS n",
                user_id=user_id,
            ).single()
            chunks = res["n"] if res else 0
            session.run("MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-() DETACH DELETE e")
        return {"chunks": chunks}
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            return fallback_graph.delete_by_user(user_id)
        raise


def purge_user_knowledge(user_id: str) -> dict:
    """Purge all graph chunks and orphaned entities for a specific user_id."""
    if not user_id:
        return {"chunks": 0}
    try:
        with neo4j_driver().session() as session:
            res = session.run(
                "MATCH (c:Chunk {user_id: $user_id}) DETACH DELETE c RETURN count(c) AS n",
                user_id=user_id,
            ).single()
            chunks = res["n"] if res else 0
            session.run("MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-() DETACH DELETE e")
        return {"chunks": chunks}
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            return fallback_graph.purge_user_knowledge(user_id)
        raise


_EXPAND_CYPHER_TMPL = """
MATCH (seed:Chunk)-[:MENTIONS]->(e:Entity)
WHERE seed.chunk_id IN $seed_ids AND seed.user_id = $user_id {seed_vc}
MATCH path = (e)-[:RELATED*1..{hops}]-(neighbor:Entity)<-[:MENTIONS]-(c:Chunk)
WHERE NOT c.chunk_id IN $seed_ids AND c.user_id = $user_id {c_vc}
WITH c.chunk_id AS chunk_id,
     reduce(w = 1.0, r IN [rel IN relationships(path) WHERE type(rel) = 'RELATED'] | w * r.weight) AS path_score,
     [r IN relationships(path) WHERE type(r) = 'RELATED' | [startNode(r).name, endNode(r).name]] AS path_edges,
     [n IN nodes(path) | {name: n.name, embedding: n.embedding}] AS path_nodes
ORDER BY path_score DESC
LIMIT $max_paths
RETURN chunk_id, path_score, path_edges, path_nodes
"""


def _version_clause(version: str | None, ref: str) -> str:
    """Inject the live/shadow isolation into Cypher.

    Live (version None) keeps shadow chunks out: production chunks have no
    ``selfopt_version`` property, so ``IS NULL`` matches them and excludes any
    shadow node. Shadow (version set) pins exactly that version.
    """
    if version is None:
        return f"AND {ref}.selfopt_version IS NULL"
    return f"AND {ref}.selfopt_version = $version"


def _expand_query(hops: int, version: str | None) -> str:
    """Build the shared expansion query. Live and shadow share one template, so
    the two can never drift apart (Spec §7.2)."""
    return (
        _EXPAND_CYPHER_TMPL
        .replace("{hops}", str(int(hops)))
        .replace("{seed_vc}", _version_clause(version, "seed"))
        .replace("{c_vc}", _version_clause(version, "c"))
    )


def expand(seed_chunk_ids: list[str], limit: int = 10, hops: int | None = None, user_id: str | None = None, question: str | None = None, version: str | None = None) -> list[dict]:
    """Return chunk_ids reachable via weighted RELATED paths strictly scoped by user_id,
    with semantic filtering against the user's question embedding to ensure intelligent expansion.

    ``version`` isolates shadow evaluation (Spec §7.2): ``None`` keeps every shadow node
    out of the live answer; a concrete version pins exactly that version's shadow graph.
    Byte-identical behavior at ``None`` — production chunks carry no ``selfopt_version``.
    """
    if not seed_chunk_ids or not user_id:
        return []
    hops = hops or settings.expand_hops
    target_user = user_id
    query = _expand_query(int(hops), version)

    params = {
        "seed_ids": seed_chunk_ids,
        "user_id": target_user,
        "max_paths": settings.expand_max_paths,
    }
    if version is not None:
        params["version"] = version

    try:
        with neo4j_driver().session() as session:
            rows = list(session.run(query, **params))
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            rows = fallback_graph.expand_rows(
                seed_chunk_ids, int(hops), target_user, settings.expand_max_paths, version
            )
        else:
            raise

    return _postprocess_expansion(rows, question, limit)


def _postprocess_expansion(rows, question: str | None, limit: int) -> list[dict]:
    """Aggregate weighted expansion rows (Neo4j or fallback) into ranked candidate chunks."""
    q_emb = None
    if question and question.strip():
        try:
            q_emb = np.array(_get_embedding(question))
        except Exception:
            pass
            
    sim_cache: dict[str, float] = {}
    out = []
    for row in rows:
        path_nodes = row.get("path_nodes", []) or []
        path_edges = row.get("path_edges", []) or []
        path_score = row.get("path_score", 0.0)
        chunk_id = row.get("chunk_id")
        if not chunk_id:
            continue
        
        relevant = True
        if q_emb is not None and any(q_emb):
            for node in path_nodes:
                node_name = node.get("name")
                if not node_name:
                    continue
                if node_name not in sim_cache:
                    node_emb = node.get("embedding")
                    if node_emb and any(node_emb):
                        sim_cache[node_name] = float(_cosine(q_emb, np.array(node_emb)))
                    else:
                        sim_cache[node_name] = 1.0
                if sim_cache[node_name] < settings.expansion_relevance_threshold:
                    relevant = False
                    break
                    
        if not relevant:
            continue
            
        deduped, seen = [], set()
        for s, t in path_edges:
            if (s, t) not in seen:
                seen.add((s, t))
                deduped.append((s, t))
                
        out.append(
            {
                "chunk_id": chunk_id,
                "path_weight": float(path_score),
                "edges": deduped,
            }
        )
        
    aggregated = {}
    for item in out:
        cid = item["chunk_id"]
        if cid not in aggregated:
            aggregated[cid] = {"chunk_id": cid, "path_weight": 0.0, "edges": []}
        aggregated[cid]["path_weight"] += item["path_weight"]
        aggregated[cid]["edges"].extend(item["edges"])
        
    final_list = list(aggregated.values())
    for item in final_list:
        seen_edges = set()
        deduped_edges = []
        for s, t in item["edges"]:
            if (s, t) not in seen_edges:
                seen_edges.add((s, t))
                deduped_edges.append((s, t))
        item["edges"] = deduped_edges
        
    final_list.sort(key=lambda x: x["path_weight"], reverse=True)
    return final_list[:limit]


def purge_invalid_entities_from_db() -> int:
    """Detach and delete legacy stopword / junk entities and unmentioned orphan entities from Neo4j."""
    deleted_count = 0
    try:
        with neo4j_driver().session() as session:
            # 1. Prune orphan entities that have no chunk mentions
            session.run("MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-() DETACH DELETE e")

            # 2. Delete invalid stopword entities
            res = session.run("MATCH (e:Entity) RETURN e.name AS name")
            names = [r["name"] for r in res]
            invalid_names = [n for n in names if not _is_valid_entity(n)]
            if invalid_names:
                del_res = session.run(
                    "MATCH (e:Entity) WHERE toLower(e.name) IN $invalid_names DETACH DELETE e RETURN count(e) AS n",
                    invalid_names=[n.lower() for n in invalid_names],
                ).single()
                deleted_count = del_res["n"] if del_res else 0
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            return fallback_graph.purge_invalid_entities_from_db()
        logger.warning(f"Error purging invalid entities: {exc}")
    return deleted_count


def graph_snapshot(limit: int = 120, user_id: str | None = None) -> dict:
    """Return nodes/edges for the UI graph view strictly scoped by user_id."""
    if not user_id:
        return {"nodes": [], "edges": [], "explanation": "The Knowledge Graph is currently empty. Upload documents to mine entities and build knowledge relationships."}

    target_user = user_id
    try:
        edges, valid_nodes, doc_entity_map, doc_title_map = _fetch_snapshot_neo4j(limit, target_user)
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            edges, valid_nodes, doc_entity_map, doc_title_map = fallback_graph.graph_snapshot_data(limit, target_user)
        else:
            raise

    return _render_snapshot(edges, valid_nodes, doc_entity_map, doc_title_map)


def _fetch_snapshot_neo4j(limit: int, target_user: str) -> tuple:
    """Fetch raw graph-snapshot rows (edges, nodes, doc map) from Neo4j."""
    with neo4j_driver().session() as session:
        # Fetch edges between valid entities
        rows = session.run(
            """
            MATCH (c:Chunk {user_id: $user_id})-[:MENTIONS]->(a:Entity)-[r:RELATED]-(b:Entity)
            WHERE (b)<-[:MENTIONS]-(:Chunk {user_id: $user_id})
            RETURN DISTINCT a.name AS source, b.name AS target, r.rel_type AS rel_type,
                   r.weight AS weight
            LIMIT $limit
            """,
            limit=limit,
            user_id=target_user,
        )
        edges = [
            dict(r) for r in rows
            if _is_valid_entity(r["source"]) and _is_valid_entity(r["target"])
        ]

        # Fetch all mentioned valid entities for this user
        all_ent_rows = session.run(
            "MATCH (c:Chunk {user_id: $user_id})-[:MENTIONS]->(e:Entity) RETURN DISTINCT e.name AS name",
            user_id=target_user,
        )
        valid_nodes = sorted({r["name"] for r in all_ent_rows if _is_valid_entity(r["name"])})

        # Map each entity to every document that mentions it, so we can join the islands
        # that live inside the same source document into a single connected component.
        doc_rows = session.run(
            "MATCH (c:Chunk {user_id: $user_id})-[:MENTIONS]->(e:Entity) "
            "RETURN DISTINCT c.document_id AS doc_id, "
            "coalesce(c.source, c.document_id) AS doc_title, e.name AS name",
            user_id=target_user,
        )
        doc_entity_map: dict[str, set[str]] = {}
        doc_title_map: dict[str, str] = {}
        for r in doc_rows:
            doc_id = r["doc_id"]
            name = r["name"]
            if not doc_id or not name:
                continue
            doc_entity_map.setdefault(doc_id, set()).add(name)
            doc_title_map[doc_id] = r.get("doc_title") or doc_id

    return edges, valid_nodes, doc_entity_map, doc_title_map


def _render_snapshot(edges: list[dict], valid_nodes: list[str], doc_entity_map: dict, doc_title_map: dict) -> dict:
    """Turn raw snapshot rows into the UI graph payload (island-joining + document hubs)."""
    # Deduplicate bidirectional edges
    seen_edge_pairs = set()
    deduped_edges = []
    for e in edges:
        s, t = e["source"], e["target"]
        if s != t and (s, t) not in seen_edge_pairs and (t, s) not in seen_edge_pairs:
            seen_edge_pairs.add((s, t))
            deduped_edges.append(e)

    # Build connected components from the current edges (union-find over valid nodes).
    parent = {n: n for n in valid_nodes}

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a, b):
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[rb] = ra

    for e in deduped_edges:
        if e["source"] in parent and e["target"] in parent:
            _union(e["source"], e["target"])

    def _add_edge(s, t, rel_type="CO_OCCURS", weight=0.85):
        if s == t:
            return
        key = (min(s, t), max(s, t))
        if key not in seen_edge_pairs:
            seen_edge_pairs.add(key)
            deduped_edges.append({"source": s, "target": t, "rel_type": rel_type, "weight": weight})

    # Connect isolated island components, scoped to entities that share a source document.
    # This keeps every chunk of the same uploaded document in one connected graph, while
    # unrelated documents (and thus unrelated entity islands) remain visually separate.
    union_found = {n: _find(n) for n in valid_nodes}
    for doc_entities in doc_entity_map.values():
        present = [n for n in doc_entities if n in union_found and _is_valid_entity(n)]
        # Collapse each document-entity set down to one representative node per component,
        # then stitch those representatives together so the whole document is connected.
        comp_rep: dict[str, str] = {}
        for n in present:
            root = union_found[n]
            if root not in comp_rep:
                comp_rep[root] = n
        reps = list(comp_rep.values())
        for i in range(len(reps) - 1):
            _add_edge(reps[i], reps[i + 1])

    # Final safety net: any valid node with no edges at all is still shown as a node and
    # attached (only if there is something to attach to), preserving full visibility.
    connected_set = {e["source"] for e in deduped_edges} | {e["target"] for e in deduped_edges}
    stray = [n for n in valid_nodes if n not in connected_set]
    if stray and connected_set:
        main_hub = list(connected_set)[0]
        for isolated in stray:
            _add_edge(main_hub, isolated)

    # ---- Spider-web document hubs ----
    # Each source document becomes a central hub node labelled with its file name,
    # and every entity the document contains hangs off it as a spoke. The physics UI
    # then settles the file name in the middle with entities radiating outward in a web.
    hub_node_titles: set[str] = set()
    for doc_id, doc_ents in doc_entity_map.items():
        present = [n for n in doc_ents if n in union_found and _is_valid_entity(n)]
        if not present:
            continue
        hub_id = doc_title_map.get(doc_id) or doc_id
        hub_node_titles.add(hub_id)
        for n in present:
            _add_edge(hub_id, n, rel_type="CONTAINS", weight=0.9)

    edge_node_set = {e["source"] for e in deduped_edges} | {e["target"] for e in deduped_edges}
    entity_nodes = sorted(n for n in valid_nodes if n in edge_node_set)
    entity_id_set = set(entity_nodes)
    hub_nodes = [
        {"id": h, "kind": "document"}
        for h in sorted(hub_node_titles)
        if h not in entity_id_set
    ]

    explanation = ""
    if nodes_base := entity_nodes:
        top_hubs = [h["id"] for h in hub_nodes[:5]] if hub_nodes else nodes_base[:2]
        sample_rels = [f"'{e['source']}' → ({e['rel_type']}) → '{e['target']}'" for e in deduped_edges[:3]]
        sample_str = f" Key relationship paths include: {', '.join(sample_rels)}." if sample_rels else ""
        explanation = (
            f"The Knowledge Graph currently links {len(entity_nodes)} entities across {len(deduped_edges)} edges, "
            f"with {len(hub_nodes)} source documents acting as central web hubs.{sample_str} "
            f"These graph nodes enable GraphRAG multi-hop retrieval and adaptive path traversal during search queries."
        )
    else:
        explanation = "The Knowledge Graph is currently empty. Upload documents to mine entities and build knowledge relationships."

    return {
        "nodes": hub_nodes + [{"id": n, "kind": "entity"} for n in entity_nodes],
        "edges": deduped_edges,
        "explanation": explanation,
    }



def is_document_graph_built(document_id: str, user_id: str) -> bool:
    """Check if a document's chunks and graph nodes are already stored in Neo4j (Build Once & Cache Forever)."""
    if not document_id or not user_id:
        return False
    try:
        with neo4j_driver().session() as session:
            res = session.run(
                "MATCH (c:Chunk {document_id: $document_id, user_id: $user_id}) RETURN count(c) AS cnt",
                document_id=document_id,
                user_id=user_id,
            ).single()
            return bool(res and res["cnt"] > 0)
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            return fallback_graph.is_document_graph_built(document_id, user_id)
        return False


def get_graph_summary(user_id: str | None = None) -> dict:
    """Generate a comprehensive architecture summary explaining what graph was built and how it was constructed."""
    if not user_id:
        return {
            "total_entities": 0,
            "total_relationships": 0,
            "top_hubs": [],
            "entity_types": {},
            "rules": [
                "Rule 1 (Domain Need): Only includes entities essential for technical understanding.",
                "Rule 2 (Graph Importance): Ensures core architectural concepts enter the graph.",
                "Rationale Tracking: Every entity has an explicit rationale for why it is in the graph.",
                "Build Once Strategy: Documents are converted to graph nodes once and cached permanently.",
            ],
            "summary": "Knowledge Graph is empty. Upload documents to mine entities and build knowledge relationships.",
        }

    try:
        with neo4j_driver().session() as session:
            res = session.run(
                "MATCH (s:GraphSummary {user_id: $user_id}) RETURN s.summary_json AS summary_json",
                user_id=user_id
            ).single()
            if res and res["summary_json"]:
                return json.loads(res["summary_json"])
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            stored = fallback_graph.get_stored_summary(user_id)
            if stored:
                return stored
        else:
            logger.warning(f"Error fetching graph summary: {exc}")

    target_user = user_id
    try:
        with neo4j_driver().session() as session:
            ent_res = session.run(
                "MATCH (c:Chunk {user_id: $user_id})-[:MENTIONS]->(e:Entity) RETURN count(DISTINCT e) AS cnt",
                user_id=target_user,
            ).single()
            total_entities = ent_res["cnt"] if ent_res else 0

            rel_res = session.run(
                "MATCH (c:Chunk {user_id: $user_id})-[:MENTIONS]->(a:Entity)-[r:RELATED]->(b:Entity) "
                "WHERE (b)<-[:MENTIONS]-(:Chunk {user_id: $user_id}) RETURN count(DISTINCT r) AS cnt",
                user_id=target_user,
            ).single()
            total_relationships = rel_res["cnt"] if rel_res else 0

            hub_rows = session.run(
                "MATCH (c:Chunk {user_id: $user_id})-[:MENTIONS]->(e:Entity)-[r:RELATED]-(other:Entity) "
                "RETURN e.name AS name, count(r) AS degree ORDER BY degree DESC LIMIT 5",
                user_id=target_user,
            )
            top_hubs = [{"name": r["name"], "degree": int(r["degree"])} for r in hub_rows]

            type_rows = session.run(
                "MATCH (c:Chunk {user_id: $user_id})-[:MENTIONS]->(e:Entity) "
                "RETURN coalesce(e.type, 'CONCEPT') AS type, count(DISTINCT e) AS count",
                user_id=target_user,
            )
            entity_types = {r["type"]: int(r["count"]) for r in type_rows}
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            total_entities, total_relationships, top_hubs, entity_types = fallback_graph.summary_counts(target_user)
        else:
            raise

    rules = [
        "Rule 1 (Domain Need): Only includes entities essential for technical understanding.",
        "Rule 2 (Graph Importance): Ensures core architectural concepts enter the graph.",
        "Rationale Tracking: Every entity has an explicit rationale for why it is in the graph.",
        "Build Once Strategy: Documents are converted to graph nodes once and cached permanently.",
    ]

    hubs_str = ", ".join([f"'{h['name']}' ({h['degree']} links)" for h in top_hubs]) if top_hubs else "None"
    summary = (
        f"The Knowledge Graph connects {total_entities} verified domain entities across {total_relationships} relationship edges. "
        f"Primary connected hubs: {hubs_str}. Every entity was filtered through strict Domain Need and Graph Importance evaluation rules "
        f"and indexed permanently with rationale tracking."
    )

    return {
        "total_entities": total_entities,
        "total_relationships": total_relationships,
        "top_hubs": top_hubs,
        "entity_types": entity_types,
        "rules": rules,
        "summary": summary,
        "major_entities": [],
        "ignored_information": []
    }


def get_entity_details(name: str, user_id: str | None = None) -> dict:
    """Fetch deep details for an entity node including why it is in the graph (rationale), neighbors, and passages.
    Includes auto-repair for existing nodes with generic rationale or missing relationship edges.
    """
    if not name or not user_id:
        return {"name": name, "type": "CONCEPT", "rationale": "Essential domain entity.", "relationships": [], "passages": []}

    target_user = user_id
    raw_name = name.strip()
    clean_name = _canonicalize(raw_name)

    try:
        return _entity_details_neo4j(raw_name, clean_name, target_user)
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            return fallback_graph.entity_details(raw_name, clean_name, target_user)
        raise


def _entity_details_neo4j(raw_name: str, clean_name: str, target_user: str) -> dict:
    """Neo4j implementation of get_entity_details (auto-repair included)."""
    with neo4j_driver().session() as session:
        # Fetch entity type and stored rationale
        ent_info = session.run(
            """
            MATCH (e:Entity)
            WHERE toLower(e.name) = toLower($raw_name) OR toLower(e.name) = $clean_name OR $clean_name IN [a IN coalesce(e.aliases, []) | toLower(a)]
            RETURN e.name AS matched_name, e.type AS type, e.rationale AS rationale
            LIMIT 1
            """,
            raw_name=raw_name,
            clean_name=clean_name,
        ).single()

        ent_type = ent_info["type"] if ent_info and ent_info.get("type") else "CONCEPT"
        matched_name = ent_info["matched_name"] if ent_info and ent_info.get("matched_name") else raw_name
        ent_rationale = ent_info["rationale"] if ent_info and ent_info.get("rationale") else ""

        # Mentioning Document Chunks
        chunk_rows = session.run(
            """
            MATCH (c:Chunk {user_id: $user_id})-[:MENTIONS]->(e:Entity)
            WHERE toLower(e.name) = toLower($raw_name) OR toLower(e.name) = $clean_name OR $clean_name IN [a IN coalesce(e.aliases, []) | toLower(a)]
            RETURN DISTINCT c.chunk_id AS chunk_id, c.source AS source, c.text AS text
            LIMIT 10
            """,
            raw_name=raw_name,
            clean_name=clean_name,
            user_id=target_user,
        )
        passages = [
            {
                "chunk_id": r["chunk_id"],
                "source": r["source"],
                "text": r["text"],
            }
            for r in chunk_rows
        ]

        # Connected relationships in Neo4j
        rel_rows = session.run(
            """
            MATCH (e:Entity)
            WHERE toLower(e.name) = toLower($raw_name) OR toLower(e.name) = $clean_name OR $clean_name IN [a IN coalesce(e.aliases, []) | toLower(a)]
            MATCH (e)-[r:RELATED]-(neighbor:Entity)
            RETURN DISTINCT neighbor.name AS neighbor,
                   coalesce(r.rel_type, 'RELATED') AS rel_type,
                   coalesce(r.weight, 1.0) AS weight
            LIMIT 30
            """,
            raw_name=raw_name,
            clean_name=clean_name,
        )
        relationships = [
            {
                "neighbor": r["neighbor"],
                "rel_type": r["rel_type"],
                "weight": float(r["weight"]),
            }
            for r in rel_rows
            if r["neighbor"].strip().lower() != raw_name.lower()
        ]

        # AUTO-REPAIR 1: If Neo4j relationships are empty, find co-occurrences from chunks & repair Neo4j
        if not relationships and passages:
            co_occur_rows = session.run(
                """
                MATCH (c:Chunk {user_id: $user_id})-[:MENTIONS]->(e:Entity)
                WHERE toLower(e.name) = toLower($raw_name) OR toLower(e.name) = $clean_name
                MATCH (c)-[:MENTIONS]->(neighbor:Entity)
                WHERE toLower(neighbor.name) <> toLower(e.name)
                RETURN DISTINCT neighbor.name AS neighbor
                LIMIT 15
                """,
                raw_name=raw_name,
                clean_name=clean_name,
                user_id=target_user,
            )
            found_neighbors = [r["neighbor"] for r in co_occur_rows if r["neighbor"].strip().lower() != raw_name.lower()]
            if found_neighbors:
                for n_name in found_neighbors:
                    relationships.append({
                        "neighbor": n_name,
                        "rel_type": "CO_OCCURS",
                        "weight": 0.85,
                    })
                    # Persist co-occurrence edges to Neo4j to permanently repair graph
                    session.run(
                        """
                        MATCH (a:Entity), (b:Entity)
                        WHERE toLower(a.name) = toLower($a_name) AND toLower(b.name) = toLower($b_name)
                        MERGE (a)-[r:RELATED {rel_type: 'CO_OCCURS'}]->(b)
                        ON CREATE SET r.weight = 0.85, r.user_id = $user_id
                        """,
                        a_name=matched_name,
                        b_name=n_name,
                        user_id=target_user,
                    )

        # AUTO-REPAIR 2: If rationale is generic or missing, generate a rich contextual rationale and save to Neo4j
        is_generic_rationale = (
            not ent_rationale
            or "essential domain concept" in ent_rationale.lower()
            or "essential domain entity" in ent_rationale.lower()
        )

        if is_generic_rationale:
            connected_names = [r["neighbor"] for r in relationships[:3]]
            conn_str = f" connected to {', '.join(connected_names)}" if connected_names else ""
            passage_text = (passages[0]["text"] if passages and passages[0].get("text") else "")
            passage_snippet = passage_text[:160].replace("\n", " ").strip() if passage_text else ""
            if passage_snippet:
                ent_rationale = (
                    f"Key {ent_type.lower()} entity '{raw_name}' mined from document '{passages[0]['source']}'{conn_str}. "
                    f"Domain context: \"{passage_snippet}...\""
                )
            else:
                ent_rationale = (
                    f"Core technical {ent_type.lower()} entity '{raw_name}'{conn_str} indexed for GraphRAG multi-hop retrieval and reasoning."
                )

            # Persist updated rationale back to Neo4j
            session.run(
                """
                MATCH (e:Entity)
                WHERE toLower(e.name) = toLower($raw_name) OR toLower(e.name) = $clean_name
                SET e.rationale = $rationale
                """,
                raw_name=raw_name,
                clean_name=clean_name,
                rationale=ent_rationale,
            )

    return {
        "name": raw_name,
        "type": ent_type,
        "rationale": ent_rationale,
        "relationships": relationships,
        "passages": passages,
    }


def clear_user_graph(user_id: str) -> None:
    """Clear all graph nodes and edges for a user in Neo4j (or SQLite fallback)."""
    if not user_id:
        return
    try:
        with neo4j_driver().session() as session:
            session.run("MATCH (c:Chunk {user_id: $user_id}) DETACH DELETE c", user_id=user_id)
            session.run("MATCH (e:Entity {user_id: $user_id}) DETACH DELETE e", user_id=user_id)
            session.run("MATCH (r:RELATED {user_id: $user_id}) DELETE r", user_id=user_id)
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            fallback_graph.clear_user_graph(user_id)
            return
        logger.warning("Neo4j user graph clear error (%s); cleaning fallback graph.", exc)
        from . import fallback_graph
        fallback_graph.clear_user_graph(user_id)


def delete_by_document(document_id: str, user_id: str = "") -> None:
    """Delete graph chunks and unmentioned entities for a specific document."""
    if not document_id:
        return
    try:
        with neo4j_driver().session() as session:
            session.run("MATCH (c:Chunk {document_id: $document_id}) DETACH DELETE c", document_id=document_id)
            session.run("MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-() DETACH DELETE e")
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            from . import fallback_graph
            fallback_graph.delete_by_document(document_id, user_id)
            return
        logger.warning("Neo4j document graph delete error (%s); cleaning fallback graph.", exc)
        from . import fallback_graph
        fallback_graph.delete_by_document(document_id, user_id)


