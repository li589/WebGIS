"""Start backend FastAPI + Worker + Gateway using launch.py."""
import os
import subprocess
import sys
from pathlib import Path

# Get Python interpreter
python_exe = Path(r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Env\Python312\python.exe")
launch_py = Path(r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\launch.py")

if not python_exe.exists():
    print(f"ERROR: Python not found: {python_exe}")
    sys.exit(1)

if not launch_py.exists():
    print(f"ERROR: launch.py not found: {launch_py}")
    sys.exit(1)

print("[INFO] Starting FastAPI + Workers + Gateway...")
print(f"[CMD] {python_exe} {launch_py} start")

# Start all services
result = subprocess.run([str(python_exe), str(launch_py), "start"], 
                       cwd=Path(__file__).parent,
                       env={**os.environ},
                       text=True,
                       encoding="utf-8")

print(result.stdout)
if result.stderr:
    print("[STDERR]", result.stderr)

sys.exit(result.returncode)
