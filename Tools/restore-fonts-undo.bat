@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0.."

echo ============================================================
echo   撤销字体回退：重新使用 思源黑体 + Inter
echo ============================================================
echo.
echo   把 7 个字体文件恢复成当前版本，再重新构建，约 5 秒。
echo.
echo   想再退回旧字体：双击 restore-fonts.bat
echo.
set /p CONFIRM=确认重新使用新字体吗？输入 y 回车：
if /i not "%CONFIRM%"=="y" (
  echo.
  echo 已取消，什么都没动。
  pause
  exit /b 0
)

echo.
echo [1/2] 恢复新字体文件 ...
git checkout HEAD -- ^
  Code/frontend/index.html ^
  Code/frontend/src/styles/tokens.css ^
  Code/frontend/src/styles/toolbar-menu.css ^
  Code/frontend/src/components/TimelineScrubber.styles.css ^
  Code/frontend/src/components/layer-sidebar/LayerSidebar.styles.css ^
  Code/frontend/src/components/info-panel/InfoPanel.styles.css ^
  Code/frontend/src/components/agent/AgentChatPanel.vue
if errorlevel 1 (
  echo.
  echo [失败] 恢复文件出错，把上面的报错发给助手。
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
echo   完成：已恢复新字体。浏览器 Ctrl+Shift+R 强刷。
echo ============================================================
pause
