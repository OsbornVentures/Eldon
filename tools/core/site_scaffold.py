"""site_scaffold: Generate a starter website (index.html, style.css, app.js).
templates: basic | bootstrap | tailwind
"""
from pathlib import Path

_T = {
    "basic": {
        "index.html": (
            '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            '  <meta charset="UTF-8" />\n'
            '  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
            '  <title>SITENAME</title>\n'
            '  <link rel="stylesheet" href="style.css" />\n'
            '</head>\n<body>\n'
            '  <header><h1>SITENAME</h1></header>\n'
            '  <main>\n    <p>Welcome to <strong>SITENAME</strong>.</p>\n  </main>\n'
            '  <footer><p>&copy; 2025 SITENAME</p></footer>\n'
            '  <script src="app.js"></script>\n</body>\n</html>\n'
        ),
        "style.css": (
            "*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n"
            "body { font-family: system-ui, sans-serif; line-height: 1.6; "
            "color: #222; background: #f8f8f8; }\n"
            "header { background: #1a1a2e; color: #fff; padding: 1.5rem 2rem; }\n"
            "main { max-width: 900px; margin: 2rem auto; padding: 0 1rem; }\n"
            "footer { text-align: center; padding: 1rem; color: #888; "
            "font-size: .875rem; margin-top: 2rem; }\n"
        ),
        "app.js": (
            "'use strict';\n"
            "document.addEventListener('DOMContentLoaded', () => {\n"
            "  console.log('SITENAME loaded');\n"
            "});\n"
        ),
    },
    "bootstrap": {
        "index.html": (
            '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            '  <meta charset="UTF-8" />\n'
            '  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
            '  <title>SITENAME</title>\n'
            '  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"'
            ' rel="stylesheet" />\n'
            '  <link rel="stylesheet" href="style.css" />\n'
            '</head>\n<body>\n'
            '  <nav class="navbar navbar-dark bg-dark px-3">\n'
            '    <span class="navbar-brand">SITENAME</span>\n  </nav>\n'
            '  <div class="container py-4">\n'
            '    <h1 class="mb-3">SITENAME</h1>\n'
            '    <p class="lead">Welcome to <strong>SITENAME</strong>.</p>\n  </div>\n'
            '  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/'
            'bootstrap.bundle.min.js"></script>\n'
            '  <script src="app.js"></script>\n</body>\n</html>\n'
        ),
        "style.css": "/* Custom styles for SITENAME */\nbody { background: #f8f9fa; }\n",
        "app.js": "'use strict';\nconsole.log('SITENAME ready');\n",
    },
    "tailwind": {
        "index.html": (
            '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            '  <meta charset="UTF-8" />\n'
            '  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
            '  <title>SITENAME</title>\n'
            '  <script src="https://cdn.tailwindcss.com"></script>\n'
            '  <link rel="stylesheet" href="style.css" />\n'
            '</head>\n<body class="bg-gray-50 text-gray-900 font-sans">\n'
            '  <header class="bg-indigo-700 text-white p-6">\n'
            '    <h1 class="text-2xl font-bold">SITENAME</h1>\n  </header>\n'
            '  <main class="max-w-3xl mx-auto p-6">\n'
            '    <p>Welcome to <strong>SITENAME</strong>.</p>\n  </main>\n'
            '  <script src="app.js"></script>\n</body>\n</html>\n'
        ),
        "style.css": "/* Custom styles — prefer Tailwind utility classes in HTML */\n",
        "app.js": "'use strict';\nconsole.log('SITENAME ready');\n",
    },
}


def run(args: dict) -> dict:
    name     = args.get("name", "MyApp").strip() or "MyApp"
    path     = args.get("path", "").strip()
    template = args.get("template", "basic").lower()

    if template not in _T:
        return {"error": f"unknown template '{template}'. Choose: {', '.join(_T)}"}

    dest = Path(path) if path else Path.cwd() / name.lower().replace(" ", "-")
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"error": f"cannot create directory {dest}: {e}"}

    written = []
    for filename, content in _T[template].items():
        fpath = dest / filename
        fpath.write_text(content.replace("SITENAME", name), encoding="utf-8")
        written.append(str(fpath))

    return {
        "name":      name,
        "template":  template,
        "directory": str(dest),
        "files":     written,
        "message":   f"Created '{name}' at {dest} — open index.html to preview.",
    }
