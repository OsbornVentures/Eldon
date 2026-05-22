# Setup

## Requirements

- Windows 10/11 (Linux/macOS: minor path adjustments in `_lib.py` and launcher)
- Python 3.10+
- llama-server (llama.cpp build with Vulkan or CUDA support)
- Gemma 4 E4B GGUF — recommend Bartowski Q8_0 from Hugging Face
- 6 GB+ VRAM (unified memory counts on AMD APUs)

## Steps

### 1. Install Python dependencies

```bash
pip install flask requests chromadb croniter
```

Optional (install what you need):
```bash
pip install playwright && python -m playwright install chromium  # browser tools
pip install docling                                               # PDF/DOCX parsing
```

### 2. Get llama-server

Download a prebuilt llama.cpp release from https://github.com/ggerganov/llama.cpp/releases

Choose the build matching your GPU:
- Vulkan: works on AMD, Intel, most GPUs
- CUDA: NVIDIA only

Extract `llama-server.exe` (Windows) or `llama-server` (Linux/macOS) somewhere on your PATH, or set `ELDON_LLAMA_EXE` to its full path.

### 3. Get the model

Download `gemma-4-e4b-it-Q8_0.gguf` (Bartowski) from Hugging Face.  
Optionally download the matching mmproj file for vision support.

### 4. Configure

Set these environment variables (or edit `launcher/eldon.ps1` defaults):

| Variable         | Required | Purpose                                     |
|------------------|----------|---------------------------------------------|
| ELDON_MODEL      | Yes      | Full path to the .gguf model file           |
| ELDON_LLAMA_EXE  | No       | Full path to llama-server if not on PATH    |
| ELDON_MMPROJ     | No       | Full path to mmproj file (vision)           |
| ELDON_BROWSER_PATH | No     | Path to browser exe for web_search visual   |
| LLAMA_URL        | No       | Completion endpoint (default: 127.0.0.1:8081/completion) |
| GOOGLE_CSE_KEY   | No       | Google Custom Search API key (100 free/day) |
| GOOGLE_CSE_CX    | No       | Google Custom Search Engine ID              |
| EBAY_APP_ID      | No       | eBay developer API key for price lookups    |

### 5. Configure filesystem access

Edit `runtime/fs_roots.txt` — one path per line. The agent can only read/write paths under these roots. The ELDON directory itself is always allowed.

Edit `runtime/allowlist.txt` — shell commands the `shell` tool is permitted to run.

Edit `runtime/blacklist.txt` — regex patterns for shell commands that are always blocked, even if allowlisted.

### 6. Launch

**Windows:**
```powershell
.\launcher\eldon.ps1
```

Or with pre-selected model:
```powershell
.\launcher\eldon.ps1 -ModelPath "C:\path\to\gemma-4-e4b-it-Q8_0.gguf"
```

Fast-launch agent mode (skips all prompts):
```powershell
.\launcher\eldon.ps1 -Agent -ModelPath "C:\path\to\model.gguf"
```

### 7. Verify

Open `http://127.0.0.1:8080` in a browser (agent mode) or send a request to `/v1/chat/completions`. Ask the agent to run `topo` — it should return your hardware snapshot.

## First run notes

- `TOOLS.md` and `grammar.gbnf` are regenerated on every `loop.py` startup from the current tool set. If they are missing, they will be created.
- `memory_db/` is created on first `memory_store` call.
- `logs/` is created automatically.
- `tools/learned/` starts empty. The agent populates it via `skill_make`.
