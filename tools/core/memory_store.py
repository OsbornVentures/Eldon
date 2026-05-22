"""memory_store: vectorize and store text/checklists for persistent memory."""
import chromadb
import uuid
from pathlib import Path

def run(args: dict) -> dict:
    try:
        # Resolves to C:\Users\Dekker\gemma\memory_db
        db_path = str(Path(__file__).parent.parent.parent / "memory_db")
        client = chromadb.PersistentClient(path=db_path)
        
        # We use a single collection for the agent's procedural/semantic memory
        collection = client.get_or_create_collection(name="agent_memory")

        content = args.get("content", "").strip()
        category = args.get("category", "general").strip()

        if not content:
            return {"error": "content cannot be empty"}

        doc_id = str(uuid.uuid4())
        
        collection.add(
            documents=[content],
            metadatas=[{"category": category}],
            ids=[doc_id]
        )
        return {
            "status": "success",
            "id": doc_id,
            "message": f"Memory stored in category: {category}"
        }
    except Exception as e:
        return {"error": f"Memory store failed: {str(e)}"}