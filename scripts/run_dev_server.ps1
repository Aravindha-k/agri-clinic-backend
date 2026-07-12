# Local Django dev server for LAN / device testing on Windows.
# Uses --noreload to avoid WinError 1450 when the autoreloader scans .venv.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Error "Virtual env not found. Run: python -m venv .venv"
}

Write-Host "Starting Django on 0.0.0.0:8000 (no autoreload — restart manually after code changes)"
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000 --noreload
