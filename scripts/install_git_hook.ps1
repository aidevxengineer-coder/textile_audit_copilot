$ErrorActionPreference = "Stop"

git config core.hooksPath .github/hooks
Write-Host "Git hooks path set to .github/hooks"
