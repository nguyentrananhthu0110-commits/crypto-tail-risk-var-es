# Mo Crypto Risk Intelligence bang PowerShell (khong can CMD)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { throw "Chua co .venv. Hay chay: powershell -ExecutionPolicy Bypass -File .\setup.ps1" }

& $VenvPy "scripts\check_status.py" --check-port
$chk = $LASTEXITCODE
if ($chk -eq 3) {
    throw "Cong ung dung dang bi chiem. Co the app dang mo tai http://127.0.0.1:8765, hoac dat CRI_PORT khac."
}
# Neu chua co du lieu/model, van mo web de ban bam nut 'Nap du lieu & huan luyen ngay' trong trinh duyet.
Write-Host "Dang khoi dong... Trinh duyet se tu mo. Dung ung dung bang Ctrl+C trong cua so nay." -ForegroundColor Cyan
& $VenvPy "scripts\launch.py"
if ($LASTEXITCODE -ne 0) { throw "Ung dung dung voi ma loi $LASTEXITCODE. Xem logs\app.log" }
