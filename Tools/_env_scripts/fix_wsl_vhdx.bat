@echo off
chcp 65001 >nul
set "LOG=%~dp0wsl_fix_result.log"
del "%LOG%" 2>nul

echo === WSL2 VHDX E_ACCESSDENIED Fix ===                          > "%LOG%" 2>&1
echo Timestamp: %DATE% %TIME%                                     >> "%LOG%" 2>&1
echo.                                                              >> "%LOG%" 2>&1

echo [1] Grant Virtual Machines (S-1-5-83-0) Full Control on VHDX files >> "%LOG%" 2>&1
icacls "I:\Docker\DockerDesktop\main\ext4.vhdx" /grant "*S-1-5-83-0:(F)"       >> "%LOG%" 2>&1
icacls "I:\Docker\DockerDesktop\disk\docker_data.vhdx" /grant "*S-1-5-83-0:(F)" >> "%LOG%" 2>&1
echo.                                                              >> "%LOG%" 2>&1

echo [2] Also grant on parent directories (inherit)               >> "%LOG%" 2>&1
icacls "I:\Docker\DockerDesktop" /grant "*S-1-5-83-0:(OI)(CI)(F)" /T /C >> "%LOG%" 2>&1
echo.                                                              >> "%LOG%" 2>&1

echo [3] wsl --shutdown to release handles                        >> "%LOG%" 2>&1
wsl --shutdown                                                     >> "%LOG%" 2>&1
echo.                                                              >> "%LOG%" 2>&1

echo [4] Wait 3s then test docker-desktop mount                   >> "%LOG%" 2>&1
timeout /t 3 /nobreak >nul
wsl -d docker-desktop -e echo WSL_MOUNT_OK                         >> "%LOG%" 2>&1
echo TEST_EXITCODE=%errorlevel%                                    >> "%LOG%" 2>&1
echo.                                                              >> "%LOG%" 2>&1
echo === Fix script completed ===                                 >> "%LOG%" 2>&1
