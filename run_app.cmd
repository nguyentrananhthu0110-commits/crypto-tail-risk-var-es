@echo off
setlocal EnableExtensions
rem --- Chay dung tu bat ky working directory nao: luon ve thu muc chua file nay ---
cd /d "%~dp0"
title Crypto Risk Intelligence
set "EXITCODE=0"

echo ============================================================
echo  Crypto Risk Intelligence - KHOI DONG UNG DUNG
echo ============================================================

if not exist ".venv\Scripts\python.exe" (
  echo [LOI] Chua co moi truong ao .venv.
  echo Hay chay theo thu tu:  setup.cmd   roi   prepare_data.cmd
  set "EXITCODE=1" & goto :failed
)
set "VENVPY=%CD%\.venv\Scripts\python.exe"
rem Kich hoat venv cho cac lenh con (van goi truc tiep VENVPY de chiu duoc duong dan co dau cach)
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat" >nul 2>&1

rem --- Kiem tra dependency thiet yeu ---
"%VENVPY%" -c "import fastapi, uvicorn, pandas" >nul 2>&1
if errorlevel 1 (
  echo [LOI] Thieu dependency thiet yeu. Hay chay lai setup.cmd.
  set "EXITCODE=1" & goto :failed
)

rem --- Kiem tra dataset/model va port (khong am tham tai lai du lieu) ---
"%VENVPY%" "scripts\check_status.py" --require-ready --check-port
set "CHK=%ERRORLEVEL%"
if "%CHK%"=="2" (
  echo.
  echo [CHUA SAN SANG] Chua co du lieu/mo hinh da luu.
  echo Hay chay prepare_data.cmd MOT LAN de khoi tao, sau do chay lai run_app.cmd.
  set "EXITCODE=2" & goto :failed
)
if "%CHK%"=="3" (
  echo.
  echo [PORT BAN] Cong ung dung dang bi chiem.
  echo Co the ung dung da mo o cua so khac: thu truy cap http://127.0.0.1:8765
  echo Neu muon dung cong khac: dat bien moi truong CRI_PORT roi chay lai.
  echo   Vi du (trong CMD):  set CRI_PORT=8770  ^&^& run_app.cmd
  set "EXITCODE=3" & goto :failed
)
if not "%CHK%"=="0" (
  echo [LOI] Kiem tra trang thai that bai (ma %CHK%). Xem logs\app.log
  set "EXITCODE=%CHK%" & goto :failed
)

echo.
echo Dang khoi dong server... Trinh duyet se tu mo khi san sang.
echo Dong ung dung: nhan Ctrl+C trong cua so nay (server con se duoc tat sach).
"%VENVPY%" "scripts\launch.py"
set "EXITCODE=%ERRORLEVEL%"

if "%EXITCODE%"=="0" (
  echo [DA DUNG] Ung dung da dong sach. Du lieu va mo hinh van duoc luu cho lan sau.
  goto :done
)

:failed
if "%EXITCODE%"=="0" set "EXITCODE=1"
echo.
echo [THAT BAI] Ung dung dung voi ma loi %EXITCODE%.
echo Vi tri log: %CD%\logs\app.log
echo Xem README.md phan "Xu ly loi thuong gap" de biet cach xu ly.
if not defined CRI_NO_PAUSE pause

:done
endlocal & exit /b %EXITCODE%
