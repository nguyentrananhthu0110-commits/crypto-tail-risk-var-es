# Nap du lieu Binance + huan luyen bang PowerShell (khong can CMD)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { throw "Chua co .venv. Hay chay: powershell -ExecutionPolicy Bypass -File .\setup.ps1" }
& $VenvPy "scripts\prepare_data.py" @args
if ($LASTEXITCODE -ne 0) { throw "prepare_data that bai voi ma loi $LASTEXITCODE. Xem logs\app.log" }
Write-Host "[THANH CONG] Mo ung dung bang .\run_app.ps1" -ForegroundColor Green
