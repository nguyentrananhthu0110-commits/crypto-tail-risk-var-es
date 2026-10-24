# Crypto Risk Intelligence - Setup bang PowerShell (khong can CMD)
# Cach chay neu bi chan execution policy:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
Write-Host "Crypto Risk Intelligence - SETUP (chi cai dat, khong tai du lieu)" -ForegroundColor Cyan

$PythonExe = $null
$PythonPrefix = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonExe = (Get-Command py).Source
    $PythonPrefix = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonExe = (Get-Command python).Source
} else {
    throw "Khong tim thay Python. Hay cai Python 3.11-3.13 tu python.org va tick 'Add Python to PATH'."
}

& $PythonExe @PythonPrefix -c "import sys; sys.exit(0 if sys.version_info.major==3 and sys.version_info.minor not in range(10) else 3)"
if ($LASTEXITCODE -ne 0) { throw "Can Python 3.10 tro len (khuyen nghi 3.11-3.13)." }
& $PythonExe @PythonPrefix --version

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$VenvBroken = $false
if (Test-Path $VenvPy) {
    try {
        & $VenvPy -c "import sys" 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { $VenvBroken = $true }
    } catch { $VenvBroken = $true }
}
if ($VenvBroken) {
    Write-Host "[1/3] .venv bi hong (Python goc khong con). Dang tao lai..."
    & $PythonExe @PythonPrefix -m venv --clear ".venv"
    if ($LASTEXITCODE -ne 0) { throw "Khong tao lai duoc .venv." }
} elseif (-not (Test-Path $VenvPy)) {
    Write-Host "[1/3] Dang tao moi truong ao .venv..."
    & $PythonExe @PythonPrefix -m venv ".venv"
    if ($LASTEXITCODE -ne 0) { throw "Khong tao duoc .venv." }
} else {
    Write-Host "[1/3] Da co .venv, tai su dung."
}

Write-Host "[2/3] Dang cai dependencies..."
& $VenvPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Nang cap pip that bai. Kiem tra mang." }
& $VenvPy -m pip install -r "requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "Cai dependencies that bai. Xem loi pip phia tren." }

Write-Host "[3/3] Dang kiem tra cai dat..."
& $VenvPy -c "import fastapi, uvicorn, pandas, numpy, scipy, sklearn, pyarrow, requests, joblib; print('Core dependencies: OK')"
if ($LASTEXITCODE -ne 0) { throw "Thieu dependency cot loi. Hay chay lai setup.ps1." }
Write-Host "[THANH CONG] Tiep theo: mo ung dung bang .\run_app.ps1 (ZIP da co du lieu/mo hinh dong goi san), hoac nap du lieu moi bang .\prepare_data.ps1" -ForegroundColor Green
