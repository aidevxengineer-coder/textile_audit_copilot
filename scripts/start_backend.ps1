$ErrorActionPreference = "Stop"

$hostValue = if ($env:BACKEND_HOST) { $env:BACKEND_HOST } else { "127.0.0.1" }
$portValue = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { "8010" }

& ".\.venv\Scripts\python.exe" -m uvicorn backend.run:app --host $hostValue --port $portValue --reload
