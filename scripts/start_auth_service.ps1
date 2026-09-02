$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
& "$root\.venv\Scripts\python.exe" -m uvicorn app.auth.main:app --app-dir "$root\backend" --host 127.0.0.1 --port 8011
