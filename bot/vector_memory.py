import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_client     = None
_embed_fn   = None
_memories   = None
_decisions  = None
_proposals  = None


def _init():
    global _client, _embed_fn, _memories, _decisions, _proposals
    if _memories:
        return True
    try:
        import chromadb
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        Path("chroma_db").mkdir(exist_ok=True)
        _client   = chromadb.PersistentClient(path="chroma_db")
        _embed_fn = DefaultEmbeddingFunction()
        _memories  = _client.get_or_create_collection("memories",  embedding_function=_embed_fn)
        _decisions = _client.get_or_create_collection("decisions", embedding_function=_embed_fn)
        _proposals = _client.get_or_create_collection("proposals", embedding_function=_embed_fn)
        return True
    except Exception as e:
        logger.warning(f"[VectorMem] ChromaDB недоступен: {e}")
        return False


_BLACKLIST = ("spring boot", "spring-boot", "spring framework")


def store_memory(text: str, source: str = "chat", meta: dict = None) -> str:
    if not _init():
        return ""
    # Не сохраняем галлюцинации Llama (Spring Boot не из нашего стека)
    low = (text or "").lower()
    if any(b in low for b in _BLACKLIST):
        logger.info(f"[VectorMem] Пропущено (blacklist): {text[:60]}...")
        return ""
    uid = f"mem_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    try:
        _memories.add(
            documents=[text],
            metadatas=[{"source": source, "date": datetime.now().isoformat(), **(meta or {})}],
            ids=[uid],
        )
        logger.info(f"[VectorMem] Сохранено: {text[:60]}...")
    except Exception as e:
        logger.error(f"[VectorMem] store_memory error: {e}")
    return uid


def reset_all() -> dict:
    """Полностью стирает все коллекции — chat memory, decisions, proposals."""
    if not _init():
        return {"ok": False, "error": "ChromaDB не инициализирован"}
    cleared = {}
    try:
        from chromadb.config import Settings
        global _memories, _decisions, _proposals
        for name, coll in (("memories", _memories), ("decisions", _decisions), ("proposals", _proposals)):
            try:
                # Стираем все документы коллекции
                all_ids = coll.get().get("ids", [])
                if all_ids:
                    coll.delete(ids=all_ids)
                cleared[name] = len(all_ids)
            except Exception as e:
                cleared[name] = f"err: {e}"
        logger.info(f"[VectorMem] reset_all: {cleared}")
        return {"ok": True, "cleared": cleared}
    except Exception as e:
        logger.error(f"[VectorMem] reset_all error: {e}")
        return {"ok": False, "error": str(e)}


def store_decision(text: str, proposal_id: str = None) -> str:
    if not _init():
        return ""
    uid = f"dec_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    try:
        _decisions.add(
            documents=[text],
            metadatas=[{"date": datetime.now().isoformat(), "proposal_id": proposal_id or ""}],
            ids=[uid],
        )
    except Exception as e:
        logger.error(f"[VectorMem] store_decision error: {e}")
    return uid


def store_proposal_context(pid: str, title: str, what: str, why: str) -> None:
    if not _init():
        return
    text = f"Proposal {pid}: {title}. Что: {what}. Зачем: {why}"
    try:
        _proposals.add(
            documents=[text],
            metadatas=[{"pid": pid, "date": datetime.now().isoformat()}],
            ids=[f"prop_{pid}"],
        )
    except Exception:
        pass


def search(query: str, n: int = 3, collection: str = "memories") -> list[dict]:
    if not _init():
        return []

    col = {"memories": _memories, "decisions": _decisions, "proposals": _proposals}.get(
        collection, _memories
    )

    if not col or col.count() == 0:
        return []

    try:
        actual_n = min(n, col.count())
        if actual_n <= 0:
            return []

        results = col.query(query_texts=[query], n_results=actual_n)
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
    if not _init():
        return {"memories": 0, "decisions": 0, "proposals": 0}
    return {
        "memories":  _memories.count()  if _memories  else 0,
        "decisions": _decisions.count() if _decisions else 0,
        "proposals": _proposals.count() if _proposals else 0,
    }