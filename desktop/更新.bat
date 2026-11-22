@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================
echo   Spirit 更新
echo ==============================
echo.
where node >nul 2>nul
if errorlevel 1 (
  echo 找不到 Node.js，请先安装 Node。
  pause
  exit /b 1
)
node scripts\update.mjs --pull
if errorlevel 1 (
  echo.
  echo 更新失败，看上面的输出。
  pause
  exit /b 1
)
echo.
echo 更新完成。双击 release\Spirit\Spirit.exe 启动。
pause
