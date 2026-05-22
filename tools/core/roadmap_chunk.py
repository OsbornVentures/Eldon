"""roadmap_chunk: break a large spec/roadmap file into wiggum-compatible job manifest."""
import json
import re
import uuid
from pathlib import Path
from tools import _lib

TOOL_META = {
    "summary": "Parse a large spec/roadmap by headers into a job manifest for wiggum.",
    "args":    '{"path": str, "chunk_size_tokens"?: int}',
    "returns": '{"manifest_path": str, "total_jobs": int, "jobs": list}',
    "tags":    ["wiggum", "planning", "document"],
    "notes":   "Splits on H1/H2/H3 Markdown headers. Each section = one job.",
}

MANIFEST_DIR    = _lib.ROOT / "runtime" / "manifests"
_CHARS_PER_TOKEN = 4


def _extract_sections(text: str, chunk_size_tokens: int) -> list:
    char_limit = chunk_size_tokens * _CHARS_PER_TOKEN
    sections = []
    current_title = "Introduction"
    current_body  = []

    for line in text.splitlines():
        h = re.match(r"^(#{1,3})\s+(.+)", line)
        if h:
            if current_body:
                body = "\n".join(current_body).strip()
                if body:
                    sections.append((current_title, body))
            current_title = h.group(2).strip()
            current_body  = []
        else:
            current_body.append(line)

    if current_body:
        body = "\n".join(current_body).strip()
        if body:
            sections.append((current_title, body))

    jobs = []
    for i, (title, body) in enumerate(sections, 1):
        truncated = body[:char_limit]
        jobs.append({
            "id":         f"JOB-{i:03d}",
            "title":      title[:120],
            "context":    truncated,
            "steps":      [],
            "budget":     chunk_size_tokens,
            "max_turns":  20,
            "status":     "pending",
        })
    return jobs


def run(args: dict) -> dict:
    path_str          = (args.get("path") or "").strip()
    chunk_size_tokens = int(args.get("chunk_size_tokens", 1500))

    if not path_str:
        return {"error": "path required"}

    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        return {"error": f"file not found: {path}"}
    if not _lib.path_allowed(str(path)):
        return {"error": f"path not allowed: {path}"}

    text = path.read_text(encoding="utf-8", errors="replace")
    jobs = _extract_sections(text, chunk_size_tokens)

    if not jobs:
        jobs = [{
            "id":         "JOB-001",
            "title":      path.stem,
            "context":    text[:chunk_size_tokens * _CHARS_PER_TOKEN],
            "steps":      [],
            "budget":     chunk_size_tokens,
            "max_turns":  20,
            "status":     "pending",
        }]

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    manifest_id   = str(uuid.uuid4())[:8]
    manifest_path = MANIFEST_DIR / f"{manifest_id}.json"
    manifest = {
        "id":      manifest_id,
        "source":  str(path),
        "goal":    f"Process: {path.name}",
        "jobs":    jobs,
        "created": _lib.now(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "manifest_path": str(manifest_path),
        "total_jobs":    len(jobs),
        "jobs":          [{k: v for k, v in j.items() if k != "context"} for j in jobs],
    }
