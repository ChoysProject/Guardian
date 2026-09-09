$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Start-Guardian([string]$Python) {
    if (-not (Test-Path ".\config.yaml")) {
        Copy-Item .\config.example.yaml .\config.yaml
    }
    & $Python -m app
}

# 반입본: 바깥에서 풀어 넣은 lib/ 가 있으면 venv·pip 없이 기동
if (Test-Path ".\lib") {
    $env:PYTHONNOUSERSITE = "1"
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        Start-Guardian "py"
    } else {
        Start-Guardian "python"
    }
    exit $LASTEXITCODE
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
Start-Guardian ".\.venv\Scripts\python.exe"
