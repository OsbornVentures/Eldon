"""Shared helpers for ELDON agent tools. Not loaded as a tool itself."""
import os
import platform
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT      = Path(__file__).parent.parent.resolve()
LLAMA_URL = os.environ.get("LLAMA_URL", "http://127.0.0.1:8081/completion")

TOPO_CACHE   = ROOT / "runtime" / "TOPO.cache"
TOPO_TTL_SEC = 300


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_lines(path: Path) -> list:
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text().splitlines()
            if l.strip() and not l.startswith("#")]


ALLOWLIST          = set(load_lines(ROOT / "runtime" / "allowlist.txt"))
BLACKLIST_PATTERNS = [re.compile(p) for p in load_lines(ROOT / "runtime" / "blacklist.txt")]

FS_ROOTS = []
for _p in load_lines(ROOT / "runtime" / "fs_roots.txt"):
    try:
        FS_ROOTS.append(Path(_p).expanduser().resolve())
    except Exception:
        pass
FS_ROOTS.append(ROOT)


def path_allowed(path_str: str) -> bool:
    try:
        target = Path(path_str).expanduser().resolve()
    except Exception:
        return False
    t = str(target).lower()
    return any(t.startswith(str(root).lower()) for root in FS_ROOTS)


def safe_shell(cmd: str, timeout: int = 8) -> str:
    """Internal helper for topology probes only. Bypasses allowlist."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout, errors="replace")
        return r.stdout.strip()
    except Exception:
        return ""


def build_topo() -> str:
    parts = []
    parts.append(f"HOST:{platform.node()}")
    parts.append(f"OS:{platform.system()} {platform.version()[:40]}")
    parts.append(f"CPU:{platform.processor() or '?'}({os.cpu_count()}c)")

    if platform.system() == "Windows":
        ram_raw = safe_shell(
            'powershell -NoProfile -Command '
            '"(Get-CimInstance Win32_OperatingSystem | '
            'ForEach-Object { \'FreePhysicalMemory=\' + $_.FreePhysicalMemory + \' \' + \'TotalVisibleMemorySize=\' + $_.TotalVisibleMemorySize })"',
            timeout=10,
        )
        try:
            free_kb  = int(re.search(r"FreePhysicalMemory=(\d+)",    ram_raw).group(1))
            total_kb = int(re.search(r"TotalVisibleMemorySize=(\d+)", ram_raw).group(1))
            parts.append(f"RAM:{round(total_kb/1048576,1)}G({round(free_kb/1048576,1)}F)")
        except Exception:
            parts.append("RAM:?")

        gpu_raw = safe_shell(
            'powershell -NoProfile -Command '
            '"Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"',
            timeout=10,
        )
        for g in [l.strip() for l in gpu_raw.splitlines() if l.strip()][:2]:
            parts.append(f"GPU:{g}")

        disk_raw = safe_shell(
            'powershell -NoProfile -Command '
            '"Get-CimInstance Win32_LogicalDisk -Filter \'DeviceID=\\\"C:\\\"\' | '
            'ForEach-Object { \'FreeSpace=\' + $_.FreeSpace + \' Size=\' + $_.Size }"',
            timeout=10,
        )
        try:
            free = int(re.search(r"FreeSpace=(\d+)", disk_raw).group(1))
            size = int(re.search(r"Size=(\d+)",      disk_raw).group(1))
            parts.append(f"DISK:{round((size-free)/1e9,0):.0f}G/{round(size/1e9,0):.0f}G")
        except Exception:
            pass
    else:
        try:
            import psutil
            vm = psutil.virtual_memory()
            parts.append(f"RAM:{round(vm.total/1e9,1)}G({round(vm.available/1e9,1)}F)")
        except Exception:
            parts.append("RAM:?")

    health_url = LLAMA_URL.replace("/completion", "/health")
    health = safe_shell(f"curl -sf {health_url}")
    parts.append(f"LLAMA:{LLAMA_URL.split('//')[-1].split('/')[0]}({health[:40] if health else 'down'})")
    parts.append(f"CWD:{ROOT}")
    parts.append(f"TS:{now()}")
    return "|".join(parts)


def ensure_topo(force: bool = False) -> tuple:
    TOPO_CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not force and TOPO_CACHE.exists():
        age = int(time.time() - TOPO_CACHE.stat().st_mtime)
        if age < TOPO_TTL_SEC:
            return TOPO_CACHE.read_text().strip(), True, age
    snap = build_topo()
    TOPO_CACHE.write_text(snap + "\n")
    return snap, False, 0
