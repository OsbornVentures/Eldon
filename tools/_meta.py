"""Registry helpers: regenerate TOOLS.md and grammar.gbnf from current tool files."""
import importlib
from tools import _lib


def list_tools() -> dict:
    """{name: (subpkg, TOOL_META_or_None, docstring_or_None)} for every tool file."""
    importlib.invalidate_caches()
    found = {}
    for subpkg in ("core", "learned"):
        d = _lib.ROOT / "tools" / subpkg
        if not d.exists():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_") or f.stem == "__init__":
                continue
            try:
                mod = importlib.import_module(f"tools.{subpkg}.{f.stem}")
            except Exception:
                continue
            if not callable(getattr(mod, "run", None)):
                continue
            found[f.stem] = (subpkg, getattr(mod, "TOOL_META", None), mod.__doc__)
    return found


def regenerate_tools_md() -> int:
    tools = list_tools()
    rows = []
    for name in sorted(tools.keys()):
        subpkg, meta, doc = tools[name]
        if meta:
            args    = meta.get("args", "-")
            returns = meta.get("returns", "-")
            summary = meta.get("summary", "")
            tags    = " ".join(f"`{t}`" for t in meta.get("tags", []))
        else:
            args = returns = "-"
            summary = (doc or "").strip().splitlines()[0] if doc else "(no docstring)"
            tags = ""
        row = f"| {name} | `{args}` | `{returns}` | {summary} ({subpkg})"
        if tags:
            row += f" [{tags}]"
        row += " |"
        rows.append(row)

    out = (
        "# Tool Registry\n\n"
        "*Auto-generated from TOOL_META. Do not edit by hand.*\n\n"
        "| name | args | returns | description |\n"
        "|------|------|---------|-------------|\n"
        + "\n".join(rows) + "\n"
    )
    (_lib.ROOT / "TOOLS.md").write_text(out, encoding="utf-8")
    return len(tools)


def regenerate_grammar() -> int:
    template_file = _lib.ROOT / "runtime" / "grammar.template"
    if not template_file.exists():
        return 0
    template = template_file.read_text(encoding="utf-8")
    tools = list_tools()
    if not tools:
        return 0
    enum = " | ".join(f'"{n}"' for n in sorted(tools.keys()))
    (_lib.ROOT / "runtime" / "grammar.gbnf").write_text(
        template.replace("__TOOL_NAMES__", enum), encoding="utf-8"
    )
    return len(tools)


def regenerate_all() -> int:
    n = regenerate_tools_md()
    regenerate_grammar()
    return n
