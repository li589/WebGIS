@echo off
chcp 65001 >nul
set "HERE=%~dp0"
set "PY=%HERE%Env\Python312\python.exe"
set "LOG=%HERE%_env_verify.log"
del "%LOG%" 2>nul
"%PY%" -c "import sys;print('ver',sys.version.split()[0])"                    > "%LOG%" 2>&1
"%PY%" -c "import socket;print('socket OK')"                                  >> "%LOG%" 2>&1
"%PY%" -c "import ctypes;print('ctypes OK')"                                  >> "%LOG%" 2>&1
"%PY%" -c "import numpy;print('numpy',numpy.__version__)"                     >> "%LOG%" 2>&1
"%PY%" -c "import scipy;print('scipy',scipy.__version__)"                     >> "%LOG%" 2>&1
"%PY%" -c "import scipy.io;print('scipy.io OK')"                              >> "%LOG%" 2>&1
"%PY%" -c "import h5py;print('h5py',h5py.__version__)"                        >> "%LOG%" 2>&1
