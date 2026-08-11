@echo off
setlocal
set "HERE=%~dp0"
set "ENV_PY=%HERE%Env\Python312\python.exe"
"%ENV_PY%" -c "import sys; print('numpy check...'); import numpy; print('numpy file:', getattr(numpy,'__file__',None)); print('numpy version:', getattr(numpy,'__version__','MISSING')); print('path has site-packages:', any('site-packages' in p for p in sys.path))"
endlocal
