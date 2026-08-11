@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set "HERE=%~dp0"
set "ENVDIR=%HERE%Env\Python312"
set "SYSPY=C:\Program Files\Python\Python312"
set "LOG=%HERE%_env_rebuild.log"
del "%LOG%" 2>nul

echo === CGDA Env/Python312 Rebuild (3.12.9) ===        > "%LOG%" 2>&1
echo Start: %DATE% %TIME%                               >> "%LOG%" 2>&1
echo.                                                    >> "%LOG%" 2>&1

echo [1] Backup existing Env\Python312                  >> "%LOG%" 2>&1
if exist "%ENVDIR%" (
    set "BAK=%HERE%Env\Python312.broken.bak"
    if exist "!BAK!" rmdir /S /Q "!BAK!"
    move "%ENVDIR%" "!BAK!"                              >> "%LOG%" 2>&1
    echo Moved old Env to !BAK!                          >> "%LOG%" 2>&1
) else (
    echo No existing Env to backup                       >> "%LOG%" 2>&1
)
echo.                                                    >> "%LOG%" 2>&1

echo [2] Copy system Python 3.12.9 -> Env\Python312      >> "%LOG%" 2>&1
robocopy "%SYSPY%" "%ENVDIR%" /E /NFL /NDL /NJH /NP /R:1 /W:1 >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo robocopy exit code=%RC% (0-7=success)               >> "%LOG%" 2>&1
if %RC% GEQ 8 (
    echo [FATAL] robocopy failed                         >> "%LOG%" 2>&1
    echo REBUILD_STATUS=FAILED_COPY                       >> "%LOG%" 2>&1
    goto :end
)
echo.                                                    >> "%LOG%" 2>&1

echo [3] Verify base interpreter + numpy                 >> "%LOG%" 2>&1
"%ENVDIR%\python.exe" -c "import sys;print('ver',sys.version.split()[0]);import numpy,scipy,h5py;print('numpy',numpy.__version__,'scipy',scipy.__version__,'h5py',h5py.__version__)" >> "%LOG%" 2>&1
echo.                                                    >> "%LOG%" 2>&1

echo [4] pip install backend requirements               >> "%LOG%" 2>&1
"%ENVDIR%\python.exe" -m pip install --disable-pip-version-check -r "%HERE%Code\backend\requirements.txt" >> "%LOG%" 2>&1
echo pip exit code=%ERRORLEVEL%                          >> "%LOG%" 2>&1
echo.                                                    >> "%LOG%" 2>&1

echo [5] Final verification (backend + algo deps)        >> "%LOG%" 2>&1
"%ENVDIR%\python.exe" -c "import numpy,scipy,h5py,fastapi,celery,paramiko;print('ALL_IMPORTS_OK numpy',numpy.__version__)" >> "%LOG%" 2>&1
echo verify exit code=%ERRORLEVEL%                        >> "%LOG%" 2>&1
echo.                                                    >> "%LOG%" 2>&1
echo REBUILD_STATUS=DONE                                 >> "%LOG%" 2>&1

:end
echo End: %DATE% %TIME%                                  >> "%LOG%" 2>&1
endlocal
