#Requires -RunAsAdministrator
param(
    [string]$TaskName = "Guardian",
    [string]$Python = "",
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
if (-not $Python) {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $Python = $venvPython
    } else {
        $Python = (Get-Command python).Source
    }
}

$argument = "-m app"
$action = New-ScheduledTaskAction -Execute $Python -Argument $argument -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Scheduled task '$TaskName' registered. WorkingDirectory=$RepoRoot"
Write-Host "사내 공용으로 쓸 때는 config.yaml 의 app.host=0.0.0.0, auth.enabled=true 로 바꾸세요."
