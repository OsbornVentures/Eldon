"""skill_make: write a new skill to tools/learned/. Code must define run(args:dict)->dict."""
import ast
from pathlib import Path
from tools._lib import ROOT

LEARNED = ROOT / "tools" / "learned"

def run(args: dict) -> dict:
    name = args.get("name", "").strip().replace(" ", "_")
    code = args.get("code", "").strip()
    desc = args.get("description", "").strip()

    if not name or not code:
        return {"error": "name and code required"}
    if not name.replace("_", "").isalnum():
        return {"error": "name must be alphanumeric/underscore"}

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"error": f"syntax: {e}"}

    funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    if "run" not in funcs:
        return {"error": "code must define run(args: dict) -> dict"}

    LEARNED.mkdir(parents=True, exist_ok=True)
    path = LEARNED / f"{name}.py"
    header = f'"""{desc}"""\n' if desc else ""
    path.write_text(header + code, encoding="utf-8")
    return {"status": "ok", "skill": name, "path": str(path)}
