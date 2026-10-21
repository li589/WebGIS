@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0.."

set BASELINE=font-baseline-20261021

echo ============================================================
echo   字体一键回退：思源黑体 + Inter  --^>  原来的 Sora
echo ============================================================
echo.
echo   只改 7 个字体相关文件，不动数据、不动后端、不动别的功能。
echo   回退后浏览器按 Ctrl+Shift+R 强刷，即可看到旧字体。
echo.
echo   想改回新字体：双击 restore-fonts-undo.bat
echo.
set /p CONFIRM=确认现在回退吗？输入 y 回车：
if /i not "%CONFIRM%"=="y" (
  echo.
  echo 已取消，什么都没动。
  pause
  exit /b 0
)

echo.
echo [1/2] 把字体文件恢复成换字体之前的样子 ...
git checkout %BASELINE% -- ^
  Code/frontend/index.html ^
  Code/frontend/src/styles/tokens.css ^
  Code/frontend/src/styles/toolbar-menu.css ^
  Code/frontend/src/components/TimelineScrubber.styles.css ^
  Code/frontend/src/components/layer-sidebar/LayerSidebar.styles.css ^
  Code/frontend/src/components/info-panel/InfoPanel.styles.css ^
  Code/frontend/src/components/agent/AgentChatPanel.vue
if errorlevel 1 (
  echo.
  echo [失败] 恢复文件出错，把上面的报错发给助手，别自己改。
  pause
  exit /b 1
)

echo.
echo [2/2] 重新构建前端，约 5 秒 ...
cd /d "%~dp0..\Code\frontend"
call npm run build
if errorlevel 1 (
  echo.
  echo [失败] 构建没通过，把上面的报错发给助手。
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   完成：字体已回到旧版。浏览器 Ctrl+Shift+R 强刷。
echo ============================================================
pause
