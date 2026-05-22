"""lint_code: Lint Python or JavaScript/TypeScript source.
Python: ruff (primary, fast), flake8 (fallback), plus compile() syntax check.
JS/TS:  eslint (requires: npm install -g eslint).
Pass inline 'code' string or a file 'path'; set 'lang' to 'python' or 'javascript'.
"""
import json
import os
import subprocess
import sys
import tempfile


def run(args: dict) -> dict:
    code = args.get("code", "")
    path = args.get("path", "")
    lang = args.get("lang", "").lower()

    if path:
        if not os.path.isfile(path):
            return {"error": f"file not found: {path}"}
        with open(path, encoding="utf-8", errors="replace") as f:
            code = f.read()
        if not lang:
            ext  = os.path.splitext(path)[1].lower()
            lang = {".py": "python", ".js": "javascript", ".ts": "typescript",
                    ".jsx": "javascript", ".tsx": "typescript"}.get(ext, "")

    if not code.strip():
        return {"error": "provide 'code' string or 'path' to a file"}

    if not lang:
        lang = "python"

    if lang in ("python", "py"):
        return _lint_python(code)
    elif lang in ("javascript", "js", "typescript", "ts", "jsx", "tsx"):
        return _lint_js(code, lang)
    else:
        return {"error": f"unsupported language '{lang}'. Use python or javascript."}


def _lint_python(code: str) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w",
                                     encoding="utf-8", delete=False) as f:
        f.write(code)
        tmp = f.name
    try:
        issues    = []
        tool_used = None

        # ruff (fast, preferred)
        try:
            r = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "--output-format=json", tmp],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode in (0, 1):
                for item in json.loads(r.stdout or "[]"):
                    fix = (item.get("fix") or {}).get("message", "")
                    issues.append({
                        "line": (item.get("location") or {}).get("row"),
                        "col":  (item.get("location") or {}).get("column"),
                        "code": item.get("code", ""),
                        "msg":  item.get("message", ""),
                        "fix":  fix,
                    })
                tool_used = "ruff"
        except Exception:
            pass

        # flake8 fallback
        if tool_used is None:
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "flake8",
                     "--format=%(row)d:%(col)d:%(code)s:%(text)s", tmp],
                    capture_output=True, text=True, timeout=15,
                )
                for line in r.stdout.splitlines():
                    parts = line.strip().split(":", 3)
                    if len(parts) >= 4:
                        issues.append({"line": int(parts[0]), "col": int(parts[1]),
                                       "code": parts[2], "msg": parts[3]})
                tool_used = "flake8"
            except Exception:
                pass

        # Always do a syntax check via compile()
        syntax_ok  = True
        syntax_err = None
        try:
            compile(code, "<string>", "exec")
        except SyntaxError as e:
            syntax_ok  = False
            syntax_err = f"SyntaxError at line {e.lineno}: {e.msg}"
            if not any(i.get("code") == "SyntaxError" for i in issues):
                issues.insert(0, {"line": e.lineno, "col": e.offset,
                                   "code": "SyntaxError", "msg": e.msg})

        return {
            "lang":        "python",
            "tool":        tool_used or "compile-only",
            "syntax_ok":   syntax_ok,
            "syntax_err":  syntax_err,
            "issue_count": len(issues),
            "issues":      issues[:50],
        }
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _lint_js(code: str, lang: str) -> dict:
    ext = ".ts" if lang in ("typescript", "ts", "tsx") else ".js"
    with tempfile.NamedTemporaryFile(suffix=ext, mode="w",
                                     encoding="utf-8", delete=False) as f:
        f.write(code)
        tmp = f.name
    try:
        try:
            r = subprocess.run(
                ["eslint", "--format=json", tmp],
                capture_output=True, text=True, timeout=20,
            )
        except FileNotFoundError:
            return {"error": "eslint not found. Install with: npm install -g eslint"}

        try:
            data = json.loads(r.stdout or "[]")
        except Exception:
            return {"error": f"eslint output parse failed. stderr: {r.stderr[:200]}"}

        issues = []
        for file_result in data:
            for msg in file_result.get("messages", []):
                issues.append({
                    "line":     msg.get("line"),
                    "col":      msg.get("column"),
                    "severity": "error" if msg.get("severity") == 2 else "warning",
                    "rule":     msg.get("ruleId", ""),
                    "msg":      msg.get("message", ""),
                })

        return {"lang": lang, "tool": "eslint", "issue_count": len(issues), "issues": issues[:50]}
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
