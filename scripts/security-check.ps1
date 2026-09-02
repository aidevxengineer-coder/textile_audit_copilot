$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"

Write-Host "Running Bandit..."
& $python -m bandit -r backend -x backend/tests -ll
if ($LASTEXITCODE -ne 0) { throw "Bandit failed with exit code $LASTEXITCODE" }

Write-Host "Running pip-audit..."
# Chroma is used only through PersistentClient and is never exposed as an HTTP
# server. PYSEC-2026-311 affects Chroma's unauthenticated server API and has no
# fixed release yet; deployment must keep that API unexposed.
& $python -m pip_audit -r requirements.txt --ignore-vuln PYSEC-2026-311
if ($LASTEXITCODE -ne 0) { throw "pip-audit failed with exit code $LASTEXITCODE" }

Write-Host "Running npm audit..."
npm --prefix frontend audit --audit-level=high
if ($LASTEXITCODE -ne 0) { throw "npm audit failed with exit code $LASTEXITCODE" }
