$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "Starting FastAPI backend at http://127.0.0.1:8000" -ForegroundColor Cyan
uv run uvicorn sq_bi_runtime.api:app --reload
