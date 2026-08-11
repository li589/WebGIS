@echo off
chcp 65001 >nul
set "HERE=%~dp0"
set "PY=%HERE%Env\Python312\python.exe"
set "LOG=%HERE%_env_pip.log"
del "%LOG%" 2>nul
echo === pip install backend requirements === > "%LOG%" 2>&1
"%PY%" -m pip install --disable-pip-version-check -r "%HERE%Code\backend\requirements.txt" >> "%LOG%" 2>&1
echo pip_exit=%errorlevel% >> "%LOG%" 2>&1
echo. >> "%LOG%" 2>&1
echo === verify backend imports === >> "%LOG%" 2>&1
"%PY%" -c "import fastapi,celery,uvicorn,minio,paramiko,pyproj,pandas,h5py,scipy,numpy;print('BACKEND_IMPORTS_OK')" >> "%LOG%" 2>&1
echo verify_exit=%errorlevel% >> "%LOG%" 2>&1
