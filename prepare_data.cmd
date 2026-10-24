@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Crypto Risk Intelligence - Prepare Data (lan dau)
set "EXITCODE=0"

echo ============================================================
echo  Crypto Risk Intelligence - CHUAN BI DU LIEU LAN DAU
echo  Tai lich su Binance public, tao features, huan luyen:
echo  Historical benchmark, GARCH(1,1), HAR-RV, XGBoost,
echo  danh gia out-of-sample, tinh VaR/ES va backtest.
echo ============================================================

if not exist ".venv\Scripts\python.exe" (
  echo [LOI] Chua co moi truong ao .venv. Hay chay setup.cmd truoc.
  set "EXITCODE=1" & goto :done
)
set "VENVPY=%CD%\.venv\Scripts\python.exe"
rem Kich hoat venv cho cac lenh con (van goi truc tiep VENVPY de chiu duoc duong dan co dau cach)
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat" >nul 2>&1

echo Dang chay pipeline... Tien do hien ben duoi, log day du ghi tai logs\app.log
echo (Tai lai toan bo lich su chi xay ra neu ban truyen them --full)
"%VENVPY%" "scripts\prepare_data.py" %*
set "EXITCODE=%ERRORLEVEL%"

if "%EXITCODE%"=="0" (
  echo.
  echo [THANH CONG] Du lieu va mo hinh da duoc luu tai:
  echo   - Du lieu:  data\raw, data\processed, data\features, data\metadata\manifest.sqlite
  echo   - Mo hinh:  models\saved, models\metadata
  echo Tu lan sau chi can chay: run_app.cmd ^(khong tai lai/huan luyen lai^)
) else (
  echo.
  echo [THAT BAI] prepare_data dung voi ma loi %EXITCODE%.
  echo Du lieu tot gan nhat ^(neu co^) van duoc giu nguyen. Xem logs\app.log de biet chi tiet.
  if not defined CRI_NO_PAUSE pause
)

:done
endlocal & exit /b %EXITCODE%
