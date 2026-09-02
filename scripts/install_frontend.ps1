$ErrorActionPreference = "Stop"

npm install
npm --prefix frontend install

Write-Host "Root and frontend npm dependencies installed"
