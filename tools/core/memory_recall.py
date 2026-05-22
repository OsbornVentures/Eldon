"""memory_recall: semantic vector search of past memories and checklists."""
import chromadb
from pathlib import Path

def run(args: dict) -> dict:
    try:
        db_path = str(Path(__file__).parent.parent.parent / "memory_db")
        client = chromadb.PersistentClient(path=db_path)
        collection = client.get_or_create_collection(name="agent_memory")

        query = args.get("query", "").strip()
        
        # Handle cases where the LLM might pass n_results as a string
        try:
            n_results = int(args.get("n_results", 3))
        except ValueError:
            n_results = 3

        if not query:
            return {"error": "query cannot be empty"}

        count = collection.count()
        if count == 0:
            return {"matches": [], "message": "Memory is empty."}
        n_results = min(n_results, count)

        results = collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        if not results["documents"] or not results["documents"][0]:
            return {"matches": [], "message": "No relevant memories found."}

        # Format output cleanly for the LLM context window
        matches = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            matches.append({
                "category": meta.get("category", "unknown"),
                "content": doc
            })
            
        return {"matches": matches}
        
    except Exception as e:
        return {"error": f"Memory recall failed: {str(e)}"}