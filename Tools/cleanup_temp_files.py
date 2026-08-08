import sys
from pathlib import Path

# Clean up diagnostic scripts
files_to_delete = [
    "lightweight_verify.py",
    "verify_fy_smap_full_regression.py",
    "final_diag.log",
    "diag_run.log",
    "diag_run2.log",
    "diag_fy_smap_comprehensive.py",
    "diag_fy_smap_full.py",
    "diag_quick_check.py",
    "test_fix.py"
]

for f in files_to_delete:
    p = Path(f)
    if p.exists():
        p.unlink()
        print(f"[OK] Deleted {f}")
    else:
        print(f"[SKIP] {f} does not exist")

print("\n[INFO] Cleaned up all diagnostic scripts.")
