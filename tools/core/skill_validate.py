"""skill_validate: validate a tool/skill in tools/learned/ — AST safety check + smoke run."""
import ast
import importlib
import json
import time
from pathlib import Path
from tools import _lib

TOOL_META = {
    "summary": "Validate a learned skill: AST safety check + smoke run with test args.",
    "args":    '{"name": str, "smoke_args"?: str}',
    "returns": '{"valid": bool, "errors": list, "warnings": list, "smoke_result"?: dict, "elapsed_ms"?: int}',
    "tags":    ["skill", "validation"],
}

_FORBIDDEN = [
    ("sys.exit",    "may terminate the process"),
    ("os.system",   "bypasses shell security layer"),
    ("eval(",       "arbitrary code execution risk"),
    ("exec(",       "arbitrary code execution risk"),
    ("__import__",  "dynamic import, prefer explicit imports"),
    ("subprocess.Popen", "use tools._lib.safe_shell or shell tool instead"),
]


def _ast_check(source: str) -> tuple:
    errors   = []
    warnings = []

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return errors + [f"SyntaxError: {e}"], warnings

    source_lines = source.splitlines()

    has_run = any(
        isinstance(n, ast.FunctionDef) and n.name == "run"
        for n in ast.walk(tree)
    )
    if not has_run:
        errors.append("missing run(args: dict) -> dict function")

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            warnings.append(f"bare except at line {node.lineno} — catches all exceptions including KeyboardInterrupt")

    for pattern, reason in _FORBIDDEN:
        for i, line in enumerate(source_lines, 1):
            if pattern in line and not line.strip().startswith("#"):
                warnings.append(f"line {i}: '{pattern}' — {reason}")

    return errors, warnings


def run(args: dict) -> dict:
    name       = (args.get("name") or "").strip()
    smoke_args = (args.get("smoke_args") or "{}").strip()

    if not name:
        return {"error": "name required"}

    skill_path = _lib.ROOT / "tools" / "learned" / f"{name}.py"
    core_path  = _lib.ROOT / "tools" / "core"    / f"{name}.py"

    found_path = skill_path if skill_path.exists() else (core_path if core_path.exists() else None)
    if not found_path:
        return {"error": f"skill not found: {name} (checked learned/ and core/)"}

    source = found_path.read_text(encoding="utf-8")
    errors, warnings = _ast_check(source)

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    try:
        parsed_args = json.loads(smoke_args)
    except Exception:
        parsed_args = {}

    smoke_result = None
    elapsed_ms   = None
    try:
        subpkg = "learned" if skill_path.exists() else "core"
        mod    = importlib.import_module(f"tools.{subpkg}.{name}")
        mod    = importlib.reload(mod)

        if not callable(getattr(mod, "run", None)):
            errors.append("module has no callable run()")
            return {"valid": False, "errors": errors, "warnings": warnings}

        t0 = time.perf_counter()
        smoke_result = mod.run(parsed_args)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        if not isinstance(smoke_result, dict):
            errors.append(f"run() must return dict, got {type(smoke_result).__name__}")
    except Exception as e:
        errors.append(f"import/run error: {str(e)[:120]}")

    return {
        "valid":        not errors,
        "errors":       errors,
        "warnings":     warnings,
        "smoke_result": smoke_result,
        "elapsed_ms":   elapsed_ms,
    }
