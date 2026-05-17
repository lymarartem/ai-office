import logging
from datetime import datetime
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

logger = logging.getLogger(__name__)

CHROMA_DIR = Path("chroma_db")
CHROMA_DIR.mkdir(exist_ok=True)

_client     = chromadb.PersistentClient(path=str(CHROMA_DIR))
_embed_fn   = DefaultEmbeddingFunction()

# Коллекции
_memories   = _client.get_or_create_collection("memories",   embedding_function=_embed_fn)
_decisions  = _client.get_or_create_collection("decisions",  embedding_function=_embed_fn)
_proposals  = _client.get_or_create_collection("proposals",  embedding_function=_embed_fn)


def store_memory(text: str, source: str = "chat", meta: dict = None) -> str:
    uid = f"mem_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    _memories.add(
        documents=[text],
        metadatas=[{"source": source, "date": datetime.now().isoformat(), **(meta or {})}],
        ids=[uid],
    )
    logger.info(f"[VectorMem] Сохранено: {text[:60]}...")
    return uid


def store_decision(text: str, proposal_id: str = None) -> str:
    uid = f"dec_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    _decisions.add(
        documents=[text],
        metadatas=[{"date": datetime.now().isoformat(), "proposal_id": proposal_id or ""}],
        ids=[uid],
    )
    return uid


def store_proposal_context(pid: str, title: str, what: str, why: str) -> None:
    text = f"Proposal {pid}: {title}. Что: {what}. Зачем: {why}"
    try:
        _proposals.add(
            documents=[text],
            metadatas=[{"pid": pid, "date": datetime.now().isoformat()}],
            ids=[f"prop_{pid}"],
        )
    except Exception:
        pass  # уже существует


def search(query: str, n: int = 3, collection: str = "memories") -> list[dict]:
    col = {"memories": _memories, "decisions": _decisions, "proposals": _proposals}.get(
        collection, _memories
    )
    try:
        results = col.query(query_texts=[query], n_results=min(n, col.count()))
        docs  = results["documents"][0] if results["documents"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []
        return [{"text": d, "meta": m} for d, m in zip(docs, metas)]
    except Exception as e:
        logger.error(f"[VectorMem] Search error: {e}")
        return []


def search_all(query: str, n: int = 3) -> list[dict]:
    results = []
    for col_name in ["decisions", "memories", "proposals"]:
        found = search(query, n=2, collection=col_name)
        for item in found:
            item["collection"] = col_name
        results.extend(found)
    return results[:n]


def build_context(query: str) -> str:
    results = search_all(query, n=4)
    if not results:
        return ""
    lines = "\n".join(
        f"[{r['collection']} / {r['meta'].get('date', '')[:10]}] {r['text']}"
        for r in results
    )
    return f"Релевантный контекст из прошлого:\n{lines}"


def count() -> dict:
    return {
        "memories":  _memories.count(),
        "decisions": _decisions.count(),
        "proposals": _proposals.count(),
    }