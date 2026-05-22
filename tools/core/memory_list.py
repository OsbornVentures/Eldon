"""memory_list: list stored memories with categories and previews."""
import chromadb
from pathlib import Path

def run(args: dict) -> dict:
    try:
        db_path = str(Path(__file__).parent.parent.parent / "memory_db")
        client = chromadb.PersistentClient(path=db_path)
        collection = client.get_or_create_collection(name="agent_memory")
        count = collection.count()
        if count == 0:
            return {"count": 0, "memories": []}
        limit = min(count, int(args.get("limit", 50)))
        results = collection.get(limit=limit, include=["documents", "metadatas"])
        memories = [
            {"category": m.get("category", "?"), "preview": d[:120]}
            for d, m in zip(results["documents"], results["metadatas"])
        ]
        return {"count": count, "shown": len(memories), "memories": memories}
    except Exception as e:
        return {"error": str(e)[:200]}
