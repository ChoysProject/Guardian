$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path ".\config.yaml")) {
    Copy-Item .\config.example.yaml .\config.yaml
}
& .\.venv\Scripts\python.exe -m app
