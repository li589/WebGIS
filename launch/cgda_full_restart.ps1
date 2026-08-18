$ErrorActionPreference = 'Continue'
Set-Location 'D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system'

# Rebuild full PATH from registry (machine + user) so launch.py can find docker etc.
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')

Write-Host '=== [1/3] launch.py stop (stop all old services: FastAPI / Workers / Beat / Docker / Gateway) ==='
& .\Env\Python312\python.exe launch.py stop
Write-Host ''
Write-Host '=== [2/3] launch.py clean-cache (clear __pycache__ / *.pyc / Vite .vite; Redis NOT flushed) ==='
& .\Env\Python312\python.exe launch.py clean-cache
Write-Host ''
Write-Host '=== [3/3] launch.py start (Docker + FastAPI + 7 Workers + Beat + Nginx Gateway :5175) ==='
& .\Env\Python312\python.exe launch.py start
Write-Host ''
Write-Host '=== DONE. Services are detached processes (PIDs in Code/backend/.data/logs/launcher_pids.json). This window can be closed. ==='
