@echo off
chcp 65001 >nul
set "HERE=%~dp0"
set "LOG=%HERE%_env_probe.log"
del "%LOG%" 2>nul

echo === ENV PYTHON (Env\Python312) === > "%LOG%" 2>&1
"%HERE%Env\Python312\python.exe" -c "import sys; print('version:', sys.version.split()[0])" >> "%LOG%" 2>&1
echo --- import numpy --- >> "%LOG%" 2>&1
"%HERE%Env\Python312\python.exe" -c "import numpy; print('numpy OK', numpy.__version__)" >> "%LOG%" 2>&1
echo --- import scipy.io --- >> "%LOG%" 2>&1
"%HERE%Env\Python312\python.exe" -c "import scipy.io; print('scipy OK')" >> "%LOG%" 2>&1
echo. >> "%LOG%" 2>&1

echo === SYSTEM PYTHON === >> "%LOG%" 2>&1
"C:\Program Files\Python\Python312\python.exe" -c "import sys; print('version:', sys.version.split()[0])" >> "%LOG%" 2>&1
"C:\Program Files\Python\Python312\python.exe" -c "import numpy, scipy.io, h5py; print('all deps OK', numpy.__version__)" >> "%LOG%" 2>&1
