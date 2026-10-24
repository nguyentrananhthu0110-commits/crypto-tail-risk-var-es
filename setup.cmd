@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Crypto Risk Intelligence - Setup
set "EXITCODE=0"

echo ============================================================
echo  Crypto Risk Intelligence - SETUP (chi cai dat, khong tai du lieu)
echo ============================================================

rem --- Tim Python: uu tien py launcher, sau do python tren PATH ---
set "PYCMD="
py -3 --version >nul 2>&1 && set "PYCMD=py -3"
if not defined PYCMD (
  python --version >nul 2>&1 && set "PYCMD=python"
)
if not defined PYCMD (
  echo [LOI] Khong tim thay Python. Hay cai Python 3.10-3.13 tu https://www.python.org/downloads/
  echo       Khi cai, nho tick "Add Python to PATH". Sau do chay lai setup.cmd.
  set "EXITCODE=1" & goto :done
)

rem --- Kiem tra phien ban >= 3.10 ---
%PYCMD% -c "import sys; sys.exit(0 if sys.version_info.major==3 and sys.version_info.minor not in range(10) else 3)" >nul 2>&1
if errorlevel 1 (
  echo [LOI] Python hien tai qua cu. Can Python 3.10 tro len (khuyen nghi 3.11-3.13).
  %PYCMD% --version
  set "EXITCODE=1" & goto :done
)
%PYCMD% --version

rem --- Tao virtual environment neu chua co ---
set "VENV_BAD="
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
  if errorlevel 1 set "VENV_BAD=1"
)
if defined VENV_BAD (
  echo [1/3] .venv bi hong ^(Python goc khong con^). Dang tao lai ...
  %PYCMD% -m venv --clear ".venv"
  if errorlevel 1 (
    echo [LOI] Khong tao lai duoc .venv.
    set "EXITCODE=1" & goto :done
  )
) else if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Dang tao moi truong ao .venv ...
  %PYCMD% -m venv ".venv"
  if errorlevel 1 (
    echo [LOI] Khong tao duoc .venv. Kiem tra quyen ghi thu muc va cai dat Python.
    set "EXITCODE=1" & goto :done
  )
) else (
  echo [1/3] Da co .venv, tai su dung.
)

set "VENVPY=%CD%\.venv\Scripts\python.exe"

echo [2/3] Dang nang cap pip va cai dependencies (co the mat vai phut lan dau)...
"%VENVPY%" -m pip install --upgrade pip
if errorlevel 1 (
  echo [LOI] Nang cap pip that bai. Kiem tra ket noi mang roi chay lai setup.cmd.
  set "EXITCODE=1" & goto :done
)
"%VENVPY%" -m pip install -r "requirements.txt"
if errorlevel 1 (
  echo [LOI] Cai dependencies that bai. Xem thong bao pip phia tren.
  echo       Goi y: thu mang khac, hoac cai Python 3.11/3.12 neu ban dang dung ban qua moi.
  set "EXITCODE=1" & goto :done
)

echo [3/3] Dang kiem tra cai dat...
"%VENVPY%" -c "import fastapi, uvicorn, pandas, numpy, scipy, sklearn, pyarrow, requests, joblib; print('Core dependencies: OK')"
if errorlevel 1 (
  echo [LOI] Thieu dependency cot loi sau khi cai. Hay chay lai setup.cmd.
  set "EXITCODE=1" & goto :done
)
"%VENVPY%" -c "import arch, xgboost; print('arch + xgboost: OK')" 2>nul
if errorlevel 1 (
  echo [CANH BAO] arch hoac xgboost chua import duoc. Ung dung van chay bang
  echo            GARCH/xgboost fallback tu cai dat, nhung nen xem lai loi pip.
)

echo.
echo [THANH CONG] Cai dat hoan tat.
echo Buoc tiep theo (chi 1 lan): chay  prepare_data.cmd
echo Sau do moi lan dung chi can:      run_app.cmd

:done
if not "%EXITCODE%"=="0" (
  echo.
  echo Setup that bai voi ma loi %EXITCODE%. Xem huong dan trong README.md phan "Xu ly loi thuong gap".
  if not defined CRI_NO_PAUSE pause
)
endlocal & exit /b %EXITCODE%
