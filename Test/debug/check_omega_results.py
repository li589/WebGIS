"""Check Omega results directory."""
import sys
import io
from pathlib import Path

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

omega_dir = Path(r"I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res")

print(f"=== Checking {omega_dir} ===\n")

if omega_dir.exists():
    for item in omega_dir.iterdir():
        if item.is_dir():
            print(f"\n[DIR] {item.name}/")
            files = list(item.rglob("*"))
            file_list = [f for f in files if f.is_file()]
            for f in sorted(file_list)[:15]:
                rel = f.relative_to(item)
                size_mb = f.stat().st_size / (1024*1024)
                print(f"   {rel}  ({size_mb:.2f} MB)")
            if len(file_list) > 15:
                print(f"   ... and {len(file_list)-15} more files")
            print(f"   TOTAL: {len(file_list)} files")
else:
    print("Directory does not exist!")
