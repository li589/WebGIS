"""Diagnose Python environment and dependencies."""
import sys
import subprocess
from pathlib import Path

print("=" * 80)
print("PYTHON ENVIRONMENT DIAGNOSIS")
print("=" * 80)

# Check Python interpreter
python_exe = sys.executable
print(f"Python: {python_exe}")
print(f"Version: {sys.version}")
print(f"Path: {Path(python_exe).resolve()}")

# Check if pip is available
print("\n[CHECK] pip module...")
result = subprocess.run([python_exe, "-m", "pip", "--version"],
                       capture_output=True, text=True)
if result.returncode == 0:
    print(f"[OK] pip available: {result.stdout.strip()}")
else:
    print(f"[SKIP] pip not available (stderr: {result.stderr[:100]})")

# Try importing dotenv
print("\n[CHECK] python-dotenv import...")
try:
    from dotenv import load_dotenv
    print("[OK] python-dotenv is installed")
except ImportError as e:
    print(f"[FAIL] Cannot import dotenv: {e}")

# Check if we can start backend config
print("\n[CHECK] Backend config import...")
sys.path.insert(0, str(Path(r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend")))
try:
    from app.core.config import BACKEND_ROOT, _RUNTIME_ROOT
    print(f"[OK] Config loaded successfully")
    print(f"  - BACKEND_ROOT: {BACKEND_ROOT}")
    print(f"  - _RUNTIME_ROOT: {_RUNTIME_ROOT}")
except Exception as e:
    print(f"[FAIL] Config import failed: {e}")

# List key directories
print("\n[KY DIRECTORIES]")
key_dirs = [
    r"I:\Geograph_DataSet",
    r"I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res",
    r"I:\Geograph_DataSet\Inversion_Results",
]

for dir_path in key_dirs:
    p = Path(dir_path)
    if p.exists():
        count = len(list(p.iterdir()))
        print(f"[OK] {dir_path} ({count} items)")
    else:
        print(f"[MISSING] {dir_path}")

print("\n" + "=" * 80)
print("DIAGNOSIS COMPLETE")
print("=" * 80)
