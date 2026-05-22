"""doc_chunk: retrieve one chunk from a parsed document by doc_id + chunk_id."""
import json
from pathlib import Path
from tools import _lib

TOOL_META = {
    "summary": "Retrieve a single chunk from a doc_parse result by index.",
    "args":    '{"doc_id": str, "chunk_id": int}',
    "returns": '{"doc_id": str, "chunk_id": int, "text": str, "tokens": int, "total_chunks": int, "has_next": bool}',
    "tags":    ["document", "docling"],
    "notes":   "Call doc_parse first to get doc_id and total_chunks.",
}

CACHE_DIR = _lib.ROOT / "runtime" / "doc_cache"
_CHARS_PER_TOKEN = 4


def run(args: dict) -> dict:
    doc_id   = (args.get("doc_id") or "").strip()
    chunk_id = int(args.get("chunk_id", 0))

    if not doc_id:
        return {"error": "doc_id required"}

    cache_dir = CACHE_DIR / doc_id
    if not cache_dir.exists():
        return {"error": f"doc_id not found in cache: {doc_id} — call doc_parse first"}

    meta_file = cache_dir / "meta.json"
    if not meta_file.exists():
        return {"error": "cache corrupted: missing meta.json"}

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    total = meta.get("total_chunks", 0)

    if chunk_id < 0 or chunk_id >= total:
        return {"error": f"chunk_id {chunk_id} out of range (0..{total-1})"}

    chunk_file = cache_dir / f"{chunk_id:04d}.txt"
    if not chunk_file.exists():
        return {"error": f"chunk file missing: {chunk_file.name}"}

    text = chunk_file.read_text(encoding="utf-8")
    tokens = max(1, len(text) // _CHARS_PER_TOKEN)

    return {
        "doc_id":       doc_id,
        "chunk_id":     chunk_id,
        "text":         text,
        "tokens":       tokens,
        "total_chunks": total,
        "has_next":     chunk_id < total - 1,
    }
