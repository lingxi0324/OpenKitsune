<#
.SYNOPSIS
  OpenKitsune 一键安装脚本（PyPI，Windows PowerShell）
.DESCRIPTION
  - 创建独立的 venv（默认在 %USERPROFILE%\.openkitsune\venv）
  - 安装 openkitsune（可选 extras、可选镜像）
  - 可选安装 Playwright 浏览器
  - 可选运行 openkitsune init（在 AppDir 目录生成 .env / data / identity）

默认用法（最简单）：
  irm https://raw.githubusercontent.com/openkitsune/openkitsune/main/scripts/quickstart.ps1 | iex

推荐用法（可传参数）：
  irm https://raw.githubusercontent.com/openkitsune/openkitsune/main/scripts/quickstart.ps1 -OutFile quickstart.ps1
  .\quickstart.ps1 -Extras all -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple
#>

[CmdletBinding()]
param(
  [string]$AppDir = "$env:USERPROFILE\.openkitsune\app",
  [string]$VenvDir = "$env:USERPROFILE\.openkitsune\venv",
  [string]$Extras = "",
  [ValidateSet("cpu","skip")] [string]$Torch = "cpu",
  [string]$IndexUrl = "",
  [switch]$NoPlaywright,
  [switch]$NoInit,
  [switch]$NoWrapper,
  [switch]$ForceWrapper
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Color {
  param([string]$Text, [string]$Color = "White")
  Write-Host $Text -ForegroundColor $Color
}

function Get-PythonCommand {
  # Prefer Python Launcher (py) for selecting 3.11+
  try {
    $pyVer = & py -3.11 -c "import sys; print(sys.version)" 2>$null
    if ($LASTEXITCODE -eq 0) { return @("py","-3.11") }
  } catch {}

  foreach ($cmd in @("python","python3")) {
    try {
      $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
      if ($LASTEXITCODE -ne 0) { continue }
      $parts = $ver.Split(".")
      if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) {
        return @($cmd)
      }
    } catch {}
  }
  return $null
}

$py = Get-PythonCommand
if ($null -eq $py) {
  Write-Color "Error: Python 3.11+ 未检测到。请先安装 Python 3.11+（建议勾选 Add to PATH）。" Red
  Write-Host "https://www.python.org/downloads/"
  exit 1
}

Write-Color "=== OpenKitsune One-Click Install ===" Cyan
Write-Color "AppDir: $AppDir" Cyan
Write-Color "VenvDir: $VenvDir" Cyan
if (-not [string]::IsNullOrWhiteSpace($Extras)) { Write-Color "Extras: $Extras" Cyan }
if (-not [string]::IsNullOrWhiteSpace($IndexUrl)) { Write-Color "pip IndexUrl: $IndexUrl" Cyan }
Write-Host ""

New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path $VenvDir -Parent) -Force | Out-Null

Write-Color "Creating virtual environment..." Yellow
if ((Test-Path $VenvDir) -and -not (Test-Path (Join-Path $VenvDir "Scripts\Activate.ps1"))) {
  Write-Color "Found incomplete venv; recreating..." Yellow
  Remove-Item -Recurse -Force $VenvDir
}
if (-not (Test-Path $VenvDir)) {
  & $py -m venv $VenvDir
}
Write-Color "OK venv ready" Green
Write-Host ""

# Activate venv (for `openkitsune` entrypoint)
& (Join-Path $VenvDir "Scripts\Activate.ps1")

Write-Color "Upgrading pip..." Yellow
python -m pip install -U pip setuptools wheel | Out-Null

if ($Torch -eq "cpu") {
  Write-Color "Installing PyTorch (CPU-only)..." Yellow
  python -m pip install -U torch --index-url https://download.pytorch.org/whl/cpu | Out-Null
}

$pkg = "openkitsune"
if (-not [string]::IsNullOrWhiteSpace($Extras)) {
  $pkg = "openkitsune[$Extras]"
}

Write-Color "Installing $pkg ..." Yellow
if ([string]::IsNullOrWhiteSpace($IndexUrl)) {
  python -m pip install -U $pkg
} else {
  python -m pip install -U $pkg -i $IndexUrl
}
Write-Color "OK OpenKitsune installed" Green
Write-Host ""

if (-not $NoPlaywright) {
  Write-Color "Installing Playwright browsers (optional)..." Yellow
  try { python -m playwright install chromium | Out-Null } catch {}
}

if (-not $NoInit) {
  Write-Color "Running setup wizard (openkitsune init)..." Cyan
  Push-Location $AppDir
  try { openkitsune init } finally { Pop-Location }
}

if (-not $NoWrapper) {
  $binDir = "$env:USERPROFILE\.openkitsune\bin"
  New-Item -ItemType Directory -Path $binDir -Force | Out-Null
  $cmdPath = Join-Path $binDir "openkitsune.cmd"

  if ((Test-Path $cmdPath) -and (-not $ForceWrapper)) {
    Write-Color "Wrapper already exists, not overwriting: $cmdPath (use -ForceWrapper to overwrite)" Yellow
  } else {
    $cmd = @"
@echo off
set "APPDIR=$AppDir"
set "VENV=$VenvDir"
call "%VENV%\Scripts\activate.bat"
cd /d "%APPDIR%"
openkitsune %*
"@
    Set-Content -Path $cmdPath -Value $cmd -Encoding ASCII
    Write-Color "Wrapper created: $cmdPath" Green
    Write-Color "Add to PATH if you want global command: $binDir" Yellow
  }
}

Write-Host ""
Write-Color "=== Done ===" Green
Write-Host "Start:"
Write-Host "  openkitsune"
Write-Host "  openkitsune --help"
