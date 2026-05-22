"""doc_parse: convert PDF/DOCX/HTML to markdown chunks via docling. No VL inference."""
import hashlib
import json
import re
import time
from pathlib import Path
from tools import _lib

TOOL_META = {
    "summary": "Parse PDF/DOCX/HTML to markdown chunks via docling. Returns chunk index.",
    "args":    '{"path": str, "include_images"?: bool}',
    "returns": '{"doc_id": str, "format": str, "pages": int, "total_chunks": int, "chunk_size": int}',
    "tags":    ["document", "docling"],
    "notes":   "Never uses VL. Call doc_chunk(doc_id, n) to read chunks. Max 1500 chars/chunk.",
}

CHUNK_SIZE  = 1500
CHUNK_OVERLAP = 200
CACHE_DIR   = _lib.ROOT / "runtime" / "doc_cache"
CACHE_TTL   = 3600


def _doc_id(path_str: str) -> str:
    h = hashlib.sha256(path_str.encode()).hexdigest()[:12]
    return h


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def _clean_markdown(md: str) -> str:
    md = re.sub(r"\n{3,}", "\n\n", md)
    lines = []
    prev = ""
    for line in md.splitlines():
        stripped = line.strip()
        if stripped == prev:
            continue
        lines.append(line)
        prev = stripped
    return "\n".join(lines).strip()


def _parse_with_docling(path: Path) -> tuple:
    """Returns (markdown_text, page_count, format_name)."""
    from docling.document_converter import DocumentConverter
    converter = DocumentConverter()
    result = converter.convert(str(path))
    doc = result.document
    md = doc.export_to_markdown()
    pages = len(doc.pages) if hasattr(doc, "pages") else 0
    fmt = path.suffix.lstrip(".").upper() or "DOC"
    return md, pages, fmt


def _parse_fallback(path: Path) -> tuple:
    """Fallback using PyMuPDF for PDFs, plain text read for everything else."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        pages = len(doc)
        parts = []
        for page in doc:
            parts.append(page.get_text())
        doc.close()
        return "\n\n".join(parts), pages, "PDF(fitz)"
    except ImportError:
        pass
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text, 1, path.suffix.lstrip(".").upper()
    except Exception as e:
        raise RuntimeError(f"cannot parse {path}: {e}")


def run(args: dict) -> dict:
    path_str      = (args.get("path") or "").strip()
    include_images = args.get("include_images", False)

    if not path_str:
        return {"error": "path required"}

    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        return {"error": f"file not found: {path}"}
    if not _lib.path_allowed(str(path)):
        return {"error": f"path not allowed: {path}"}

    doc_id    = _doc_id(str(path))
    cache_dir = CACHE_DIR / doc_id

    if cache_dir.exists():
        meta_file = cache_dir / "meta.json"
        if meta_file.exists():
            age = time.time() - meta_file.stat().st_mtime
            if age < CACHE_TTL:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                return {**meta, "cached": True}

    try:
        md, pages, fmt = _parse_with_docling(path)
    except Exception:
        try:
            md, pages, fmt = _parse_fallback(path)
        except Exception as e:
            return {"error": str(e)[:200]}

    md = _clean_markdown(md)
    chunks = _chunk_text(md)

    cache_dir.mkdir(parents=True, exist_ok=True)
    for i, chunk in enumerate(chunks):
        (cache_dir / f"{i:04d}.txt").write_text(chunk, encoding="utf-8")

    meta = {
        "doc_id":       doc_id,
        "path":         str(path),
        "format":       fmt,
        "pages":        pages,
        "total_chunks": len(chunks),
        "chunk_size":   CHUNK_SIZE,
        "cached":       False,
    }
    (cache_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta
