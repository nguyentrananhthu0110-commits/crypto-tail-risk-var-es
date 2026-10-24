@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Crypto Risk Intelligence - Update Data
set "EXITCODE=0"

echo ============================================================
echo  Crypto Risk Intelligence - CAP NHAT DU LIEU (incremental)
echo  Chi tai phan thieu ke tu checkpoint gan nhat.
echo  Huan luyen lai chi khi co du ngay du lieu moi theo cau hinh,
echo  hoac khi ban truyen them:  update_data.cmd --retrain
echo ============================================================

if not exist ".venv\Scripts\python.exe" (
  echo [LOI] Chua co moi truong ao .venv. Hay chay setup.cmd truoc.
  set "EXITCODE=1" & goto :done
)
set "VENVPY=%CD%\.venv\Scripts\python.exe"
rem Kich hoat venv cho cac lenh con (van goi truc tiep VENVPY de chiu duoc duong dan co dau cach)
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat" >nul 2>&1

"%VENVPY%" "scripts\check_status.py" >nul 2>&1
"%VENVPY%" "scripts\update_data.py" %*
set "EXITCODE=%ERRORLEVEL%"

if "%EXITCODE%"=="0" (
  echo [THANH CONG] Cap nhat hoan tat. Mo ung dung bang run_app.cmd
) else (
  echo [THAT BAI] Cap nhat dung voi ma loi %EXITCODE%.
  echo Dataset tot gan nhat van duoc giu nguyen. Xem logs\app.log de biet chi tiet.
  if not defined CRI_NO_PAUSE pause
)

:done
endlocal & exit /b %EXITCODE%
