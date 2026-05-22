#Requires -Version 5.1
<#
.SYNOPSIS
    ELDON launcher — Gemma 4 agent stack
.DESCRIPTION
    Starts llama-server with Gemma 4 E4B, then launches in one of three modes:
      [1] Agent    — proxy on PORT (8080), llama-server on BACKEND_PORT (8081)
      [2] API      — llama-server direct on PORT (8080), browser UI
      [3] Loop     — run a single task via loop.py (no proxy, no browser)
#>
param(
    [string]$ModelPath  = "",   # override model file path
    [string]$Task       = "",   # pre-fill loop task (mode 3)
    [switch]$Agent,             # fast-launch agent mode
    [switch]$LAN                # bind to 0.0.0.0 instead of 127.0.0.1
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "ELDON"

# ==============================================================================
#  PATHS — edit these or set env vars before launching
# ==============================================================================
$ELDON_ROOT    = Split-Path $PSScriptRoot -Parent
$LLAMA_EXE     = if ($env:ELDON_LLAMA_EXE)  { $env:ELDON_LLAMA_EXE  } else { "llama-server.exe" }
$MODEL_FILE    = if ($ModelPath -ne "")      { $ModelPath            } `
                 elseif ($env:ELDON_MODEL)   { $env:ELDON_MODEL      } else { "" }
$MMPROJ_FILE   = if ($env:ELDON_MMPROJ)     { $env:ELDON_MMPROJ     } else { "" }
$TEMPLATE_FILE = Join-Path $ELDON_ROOT "templates\gemma4.jinja"
$PROXY_PY      = Join-Path $ELDON_ROOT "proxy.py"
$LOOP_PY       = Join-Path $ELDON_ROOT "loop.py"
$LOGDIR        = Join-Path $ELDON_ROOT "logs"

$PORT          = if ($env:PROXY_PORT)        { [int]$env:PROXY_PORT  } else { 8080 }
$BACKEND_PORT  = 8081

if (-not (Test-Path $LOGDIR)) { New-Item -ItemType Directory $LOGDIR | Out-Null }

# ==============================================================================
#  UI
# ==============================================================================
function ui-header {
    $eq = "=" * 68
    Write-Host ""
    Write-Host "  +$eq+" -ForegroundColor Cyan
    Write-Host "  |  ELDON  —  Edge Local Deterministic Orchestration Node         |" -ForegroundColor Cyan
    Write-Host "  +$eq+" -ForegroundColor Cyan
    Write-Host ""
}
function ui-ok  { param($m) Write-Host "  [OK]  $m" -ForegroundColor Green }
function ui-inf { param($m) Write-Host "  [..]  $m" -ForegroundColor DarkYellow }
function ui-err { param($m) Write-Host "  [!!]  $m" -ForegroundColor Red }
function ui-sep { Write-Host ("  " + "-" * 66) -ForegroundColor DarkGray }

function Read-Key {
    param([string]$prompt)
    Write-Host "  $prompt " -NoNewline -ForegroundColor White
    $k = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    $c = $k.Character.ToString().ToUpper()
    Write-Host $c -ForegroundColor Yellow
    return $c
}

# ==============================================================================
#  KILL STALE SERVERS
# ==============================================================================
$null = & taskkill /IM llama-server.exe /F 2>$null
Start-Sleep -Milliseconds 800

# ==============================================================================
#  STEP 1 — MODEL FILE
# ==============================================================================
ui-header

if (-not $MODEL_FILE) {
    ui-sep
    Write-Host ""
    Write-Host "  Model file path (GGUF):" -ForegroundColor White
    Write-Host "  Set env ELDON_MODEL or pass -ModelPath to skip this prompt." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Path: " -NoNewline -ForegroundColor White
    $MODEL_FILE = Read-Host
}

if (-not (Test-Path $MODEL_FILE)) {
    ui-err "Model file not found: $MODEL_FILE"
    Write-Host "  Press any key..." -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown"); exit 1
}

$modelName = Split-Path $MODEL_FILE -Leaf
$modelGB   = [math]::Round((Get-Item $MODEL_FILE).Length / 1GB, 2)
ui-ok "Model: $modelName  ($modelGB GB)"

# ==============================================================================
#  STEP 2 — SERVER FLAGS
# ==============================================================================
Write-Host ""
ui-sep
Write-Host ""
Write-Host "  Default flags:" -ForegroundColor DarkGray
Write-Host "    ngl=99  ctx=32768  temp=0.85  tb=8  parallel=1" -ForegroundColor DarkGray
Write-Host ""

$ngl      = 99
$ctx      = 32768
$temp     = "0.85"
$tb       = 8
$parallel = 1

if (-not $Agent) {
    $optKey = Read-Key "Override defaults? [Y/N]:"
    if ($optKey -eq "Y") {
        Write-Host ""
        Write-Host "  ngl      [$ngl]: "  -NoNewline -ForegroundColor White; $inp = Read-Host; if ($inp -match '^\d+$')    { $ngl  = [int]$inp }
        Write-Host "  ctx      [$ctx]: "  -NoNewline -ForegroundColor White; $inp = Read-Host; if ($inp -match '^\d+$')    { $ctx  = [int]$inp }
        Write-Host "  temp     [$temp]: " -NoNewline -ForegroundColor White; $inp = Read-Host; if ($inp -match '^[\d.]+$') { $temp = $inp }
        Write-Host "  tb       [$tb]: "   -NoNewline -ForegroundColor White; $inp = Read-Host; if ($inp -match '^\d+$')    { $tb   = [int]$inp }
    }
}

# ==============================================================================
#  STEP 3 — MODE
# ==============================================================================
Write-Host ""
ui-sep
Write-Host ""
Write-Host "  [1]  " -NoNewline -ForegroundColor White
Write-Host "Agent   " -NoNewline -ForegroundColor Green
Write-Host "proxy on :$PORT, llama on :$BACKEND_PORT  (browser UI + tool loop)" -ForegroundColor DarkGray

Write-Host "  [2]  " -NoNewline -ForegroundColor White
Write-Host "API     " -NoNewline -ForegroundColor Cyan
Write-Host "llama direct on :$PORT  (browser UI, no proxy)" -ForegroundColor DarkGray

Write-Host "  [3]  " -NoNewline -ForegroundColor White
Write-Host "Loop    " -NoNewline -ForegroundColor Yellow
Write-Host "run a task via loop.py  (CLI, no browser)" -ForegroundColor DarkGray

Write-Host ""; ui-sep; Write-Host ""

$modeKey = if ($Agent) { "1" } else { (Read-Key "Mode [1/2/3]:") }

$BIND            = if ($LAN) { "0.0.0.0" } else { "127.0.0.1" }
$LLAMA_PORT      = if ($modeKey -eq "1") { $BACKEND_PORT } else { $PORT }
$HEALTH_URL      = "http://127.0.0.1:$LLAMA_PORT/health"

# ==============================================================================
#  STEP 4 — START LLAMA-SERVER
# ==============================================================================
$mmFlag   = if ($MMPROJ_FILE -and (Test-Path $MMPROJ_FILE)) { "--mmproj `"$MMPROJ_FILE`"" } else { "" }
$tplFlag  = "--jinja --chat-template-file `"$TEMPLATE_FILE`""
$LOGFILE  = "$LOGDIR\llama-server.log"

ui-sep
ui-inf "Starting llama-server  ngl=$ngl  ctx=$ctx  port=$LLAMA_PORT"

$bat = "$env:TEMP\_eldon_llama.bat"
@"
@echo off
"$LLAMA_EXE" -m "$MODEL_FILE" $mmFlag --host $BIND --port $LLAMA_PORT --ctx-size $ctx -ngl $ngl -tb $tb --temp $temp --parallel $parallel --metrics $tplFlag > "$LOGFILE" 2>&1
"@ | Out-File -FilePath $bat -Encoding ascii -Force
Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$bat`"" -WindowStyle Hidden

$tries = 0; $ready = $false
Write-Host "  " -NoNewline
while ($tries -lt 60) {
    Start-Sleep -Seconds 2; $tries++
    try {
        if ((Invoke-WebRequest -Uri $HEALTH_URL -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop).StatusCode -eq 200) {
            $ready = $true; break
        }
    } catch {}
    $f = [math]::Floor($tries * 20 / 60)
    Write-Host "`r  [$(("#" * $f).PadRight(20,"."))  $($tries*2)s]" -NoNewline -ForegroundColor DarkGray
}
Write-Host ""

if (-not $ready) {
    ui-err "Server did not respond after 120s — check $LOGFILE"
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown"); exit 1
}
ui-ok "llama-server ready  http://127.0.0.1:$LLAMA_PORT"

# ==============================================================================
#  MODE 1 — AGENT (proxy)
# ==============================================================================
if ($modeKey -eq "1") {
    $pyExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $pyExe) { ui-err "python not found in PATH"; exit 1 }

    $proxyLog = "$LOGDIR\proxy.log"
    $proxyBat = "$env:TEMP\_eldon_proxy.bat"
    @"
@echo off
set PROXY_HOST=$BIND
set LLAMA_BACKEND=http://127.0.0.1:$BACKEND_PORT
set LLAMA_URL=http://127.0.0.1:$BACKEND_PORT/completion
"$pyExe" "$PROXY_PY" > "$proxyLog" 2>&1
"@ | Out-File -FilePath $proxyBat -Encoding ascii -Force
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$proxyBat`"" -WindowStyle Hidden

    ui-inf "Starting proxy on $BIND`:$PORT ..."
    $pReady = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        try { $null = Invoke-WebRequest "http://127.0.0.1:$PORT/health" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop; $pReady = $true; break } catch {}
    }
    if ($pReady) { ui-ok "Proxy up  http://127.0.0.1:$PORT" } else { ui-inf "Proxy slow — browser may need a moment" }

    Start-Process "http://127.0.0.1:$PORT"

    # Live dashboard
    function fmtBar { param([double]$pct,[int]$w=20); $f=[math]::Min([math]::Max([int]($pct/100*$w),0),$w); "["+("#"*$f)+("."*($w-$f))+"]" }
    function parsePrometheus { param([string]$raw); $tbl=@{}; foreach ($line in ($raw -split "`n")) { if ($line -match '^#') { continue }; if ($line -match '^llamacpp:(\w+)' -and $line -match '\s+([\d.eE+\-]+)\s*$') { $tbl[$Matches[1]]=[double]$Matches[2] } }; return $tbl }

    try {
        while ($true) {
            $mRaw  = ""; try { $mRaw  = (Invoke-WebRequest "http://127.0.0.1:$LLAMA_PORT/metrics" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop).Content } catch {}
            $stats = parsePrometheus $mRaw
            $slots = @(); try { $slots = @(Invoke-RestMethod "http://127.0.0.1:$LLAMA_PORT/slots" -TimeoutSec 2 -ErrorAction Stop) } catch {}
            $os       = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
            $cpuPct   = try { [math]::Round((Get-CimInstance Win32_Processor -ErrorAction Stop | Measure-Object LoadPercentage -Average).Average, 0) } catch { 0 }
            $ramUsedG = if ($os) { [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory)/1MB,1) } else { 0 }
            $ramTotG  = if ($os) { [math]::Round($os.TotalVisibleMemorySize/1MB,1) } else { 0 }
            $ramPct   = if ($os -and $os.TotalVisibleMemorySize -gt 0) { [math]::Round(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/$os.TotalVisibleMemorySize*100,0) } else { 0 }
            $tpsGen   = if ($stats['predicted_tokens_per_second']) { [math]::Round($stats['predicted_tokens_per_second'],1) } else { 0.0 }
            $tokGen   = if ($stats['n_tokens_predicted_total'])    { [int64]$stats['n_tokens_predicted_total'] } else { 0 }
            $pOk      = $false; try { $null = Invoke-WebRequest "http://127.0.0.1:$PORT/health" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop; $pOk=$true } catch {}

            Clear-Host
            $ts = Get-Date -Format "HH:mm:ss"
            Write-Host ""
            Write-Host "  +$("="*68)+" -ForegroundColor Green
            Write-Host "  |  ELDON AGENT   http://127.0.0.1:$PORT$((" "*43)|Out-String -NoNewline)|" -ForegroundColor Green
            Write-Host "  +$("="*68)+" -ForegroundColor Green
            Write-Host ""
            Write-Host "  MODEL    $modelName" -ForegroundColor Yellow
            Write-Host "  BACKEND  http://127.0.0.1:$LLAMA_PORT  (llama-server)" -ForegroundColor DarkGray
            Write-Host "  PROXY    http://127.0.0.1:$PORT  $(if($pOk){'UP'}else{'DOWN'})" -ForegroundColor $(if($pOk){'Green'}else{'Red'})
            Write-Host "  FLAGS    ngl=$ngl  ctx=$ctx  temp=$temp" -ForegroundColor DarkGray
            Write-Host ""
            Write-Host "  tps: $tpsGen gen   tokens: $tokGen total" -ForegroundColor $(if($tpsGen -gt 0){'Green'}else{'DarkGray'})
            Write-Host ""
            if ($slots.Count -gt 0) {
                foreach ($sl in $slots) {
                    $nPast = [int]$sl.n_past; $slPct = if($ctx -gt 0){[math]::Round($nPast/$ctx*100,0)}else{0}
                    $slSt  = switch([int]$sl.state){0{"idle"}1{"gen "}2{"wait"}default{"?   "}}
                    Write-Host ("  Slot {0}  {1,6}/{2} tok  {3} {4,3}%  [{5}]" -f $sl.id,$nPast,$ctx,(fmtBar $slPct),$slPct,$slSt) -ForegroundColor DarkGray
                }
            }
            Write-Host ""
            $cCol = if($cpuPct -gt 90){"Red"}elseif($cpuPct -gt 60){"Yellow"}else{"Green"}
            $rCol = if($ramPct -gt 85){"Red"}elseif($ramPct -gt 65){"Yellow"}else{"Green"}
            Write-Host ("  cpu: {0,3}%  {1}" -f $cpuPct,(fmtBar $cpuPct)) -ForegroundColor $cCol
            Write-Host ("  ram: {0} / {1} GB  {2}  {3}%" -f $ramUsedG,$ramTotG,(fmtBar $ramPct),$ramPct) -ForegroundColor $rCol
            Write-Host ""
            Write-Host "  $ts  .  refresh 4s  .  Ctrl+C to stop" -ForegroundColor DarkGray
            Write-Host ""
            Start-Sleep -Seconds 4
        }
    } finally {
        Write-Host ""; ui-inf "Stopping ELDON..."
        $null = & taskkill /IM python.exe       /F 2>$null
        $null = & taskkill /IM llama-server.exe /F 2>$null
        ui-ok "Done."
    }
    exit 0
}

# ==============================================================================
#  MODE 2 — API SERVER
# ==============================================================================
if ($modeKey -eq "2") {
    Write-Host ""
    $openKey = Read-Key "Open browser UI? [Y/N]:"
    if ($openKey -eq "Y") { Start-Process "http://127.0.0.1:$PORT" }
    Write-Host ""
    ui-inf "API server running on http://127.0.0.1:$PORT  —  Ctrl+C to stop"
    try { while ($true) { Start-Sleep -Seconds 10 } }
    finally {
        Write-Host ""; ui-inf "Stopping..."
        $null = & taskkill /IM llama-server.exe /F 2>$null
        ui-ok "Done."
    }
    exit 0
}

# ==============================================================================
#  MODE 3 — LOOP (direct)
# ==============================================================================
if ($modeKey -eq "3") {
    $pyExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $pyExe) { ui-err "python not found in PATH"; exit 1 }

    if ($Task -eq "") {
        Write-Host ""
        Write-Host "  Task: " -NoNewline -ForegroundColor White
        $Task = Read-Host
    }
    if ($Task -eq "") { ui-err "No task provided."; exit 1 }

    Write-Host ""
    ui-inf "Running loop.py..."
    Write-Host ""

    $env:LLAMA_URL = "http://127.0.0.1:$LLAMA_PORT/completion"
    & $pyExe $LOOP_PY $Task

    Write-Host ""
    ui-ok "Loop complete."
    Write-Host "  Press any key..." -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

    $null = & taskkill /IM llama-server.exe /F 2>$null
    exit 0
}
