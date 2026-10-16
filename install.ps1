# ============================================================
# OpenKitsune · 安装依赖脚本（Windows PowerShell）
# 1) 创建 .venv 并安装 Python 依赖（uv 优先，回退 pip）
# 2) 安装前端 npm 依赖并构建 Web 前端（apps/setup-center/dist-web）
# 用法：powershell -ExecutionPolicy Bypass -File install.ps1
# ============================================================
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Step([string]$T) { Write-Host "`n==> $T" -ForegroundColor Cyan }
function Ok([string]$M)    { Write-Host "    [OK] $M" -ForegroundColor Green }
function Fail([string]$M)  { Write-Host "    [FAIL] $M" -ForegroundColor Red }

Write-Host ""
Write-Host "  OpenKitsune · 安装依赖" -ForegroundColor Magenta
Write-Host "  ================================"

# ---------- 1. Python 检查 ----------
Step "检查 Python 3.11+"
$py = $null
foreach ($cand in @("python", "py")) {
    try {
        if ($cand -eq "py") { $v = & $cand -3.13 --version 2>&1 } else { $v = & $cand --version 2>&1 }
        if ($LASTEXITCODE -eq 0 -and "$v" -match "Python (\d+)\.(\d+)") {
            $py = $cand; $pyVer = "$($Matches[1]).$($Matches[2])"; break
        }
    } catch { }
}
if (-not $py) {
    Fail "未找到 Python 3.11+，请先安装（https://www.python.org/downloads/）"
    exit 1
}
Ok "Python $pyVer 可用"

# ---------- 2. uv / pip ----------
Step "检查包管理器"
$uv = (Get-Command uv -ErrorAction SilentlyContinue) -ne $null
if ($uv) { Ok "uv 可用（推荐，更快）" } else { Write-Host "    [i] uv 不可用，回退使用 pip" -ForegroundColor Yellow }

# ---------- 3. 创建 venv ----------
Step "创建虚拟环境 .venv"
if (Test-Path ".venv\Scripts\python.exe") { Ok ".venv 已存在" }
else {
    if ($uv) { uv venv .venv | Out-Null } else { & $py -m venv .venv }
    if (Test-Path ".venv\Scripts\python.exe") { Ok ".venv 创建完成" }
    else { Fail ".venv 创建失败"; exit 1 }
}

# ---------- 4. 安装 Python 依赖 ----------
Step "安装 Python 依赖（pip install -e .）"
if ($uv) {
    uv pip install -e . --python .venv
    if ($LASTEXITCODE -ne 0) { Fail "uv 安装失败"; exit 1 }
} else {
    & ".venv\Scripts\python.exe" -m pip install -U pip setuptools wheel | Out-Null
    & ".venv\Scripts\python.exe" -m pip install -e .
    if ($LASTEXITCODE -ne 0) { Fail "pip 安装失败"; exit 1 }
}
Ok "Python 依赖安装完成"

# ---------- 5. 前端依赖与构建 ----------
Step "安装前端依赖并构建 Web（apps/setup-center）"
$sc = Join-Path $ProjectRoot "apps\setup-center"
Set-Location $sc
if (-not (Test-Path "node_modules")) {
    npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { Fail "npm install 失败"; exit 1 }
}
Ok "npm 依赖就绪"
if (-not (Test-Path "dist-web\index.html")) {
    npm run build:web
    if ($LASTEXITCODE -ne 0) { Fail "前端构建失败"; exit 1 }
}
Ok "Web 前端构建完成（dist-web）"

# ---------- 完成 ----------
Set-Location $ProjectRoot
Write-Host ""
Write-Host "  ================================" -ForegroundColor Green
Write-Host "  安装完成。启动：powershell -ExecutionPolicy Bypass -File start.ps1" -ForegroundColor Green
Write-Host ""
