# 바깥(인터넷 되는 PC)에서 의존성을 lib/ 로 풀어 zip 에 넣습니다.
# 안쪽은 pip / venv 없이 Python 만으로 기동합니다.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Stamp = Get-Date -Format "yyyyMMdd-HHmm"
$Stage = Join-Path $env:TEMP "guardian-import-$Stamp"
$OutDir = Join-Path $Root "dist"
$Zip = Join-Path $OutDir "guardian-import-$Stamp.zip"
$Lib = Join-Path $Stage "lib"

if (Test-Path $Stage) {
    Remove-Item -Recurse -Force $Stage
}
New-Item -ItemType Directory -Force $Stage | Out-Null
New-Item -ItemType Directory -Force $Lib | Out-Null
New-Item -ItemType Directory -Force $OutDir | Out-Null

$Copy = @(
    "app",
    "plugins",
    "templates",
    "static",
    "scripts",
    "requirements.txt",
    "config.example.yaml",
    "README.md"
)
foreach ($item in $Copy) {
    $src = Join-Path $Root $item
    if (-not (Test-Path $src)) {
        throw "없는 경로입니다: $item"
    }
    Copy-Item -Recurse -Force $src $Stage
}

Get-ChildItem -Path $Stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -Path $Stage -Recurse -Directory -Filter ".pytest_cache" | Remove-Item -Recurse -Force
Get-ChildItem -Path $Stage -Recurse -File -Include *.pyc,*.pyo | Remove-Item -Force

$Pip = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Pip)) {
    $Pip = "py"
}

Write-Host "의존성을 lib/ 에 풉니다 (Windows 64bit CPython 3.13, 인터넷은 여기서만)"
& $Pip -m pip install `
    -r (Join-Path $Root "requirements.txt") `
    --target $Lib `
    --python-version 3.13 `
    --platform win_amd64 `
    --implementation cp `
    --only-binary :all: `
    --upgrade `
    --no-compile
if ($LASTEXITCODE -ne 0) {
    throw @"
3.13 Windows 용 패키지를 lib/ 에 풀지 못했습니다.
이 PC 파이썬이 3.13 이 아니어도 pip 가 휠만 받아 풀 수 있습니다.
안쪽과 같은 Windows 64bit Python 3.13 이 있는 PC에서 다시 실행하세요.
pip 가 최신이어야 --python-version 이 됩니다: py -m pip install -U pip
"@
}

Get-ChildItem -Path $Lib -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

if (Test-Path $Zip) {
    Remove-Item -Force $Zip
}
if (Get-Command tar -ErrorAction SilentlyContinue) {
    tar -C $Stage -a -cf $Zip *
} else {
    Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip -Force
}
Remove-Item -Recurse -Force $Stage
Write-Host "반입 파일: $Zip"
Write-Host "안에는 pip 없이 압축 풀고 config.yaml 의 dify.base_url IP만 바꾼 뒤 py -m app 하면 됩니다."
