"""
全面诊断 FY/SMAP 反演问题并生成解决方案
===========================================
1. 检查 omega_avg_daily 模块
2. 检查 workflow seeds
3. 对比 MATLAB 参考结果
4. 重新运行全流程
"""

import sys
import io
from pathlib import Path

# Fix encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(r"D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system")
CODE_DIR = PROJECT_ROOT / "Code"

print("="*60)
print("STEP 1: 检查 omega_avg_daily 模块")
print("="*60)

omega_modules = []
algorithms_dir = CODE_DIR / "algorithms" / "providers" / "Python"

if algorithms_dir.exists():
    print(f"\n查找 {algorithms_dir}")
    for item in algorithms_dir.rglob("*"):
        if item.is_file() and "omega" in str(item).lower():
            omega_modules.append(str(item.relative_to(PROJECT_ROOT)))
            print(f"   ✓ {item.name}")

if not omega_modules:
    print("\n⚠ 未找到 omega 相关模块")
else:
    print(f"\n共找到 {len(omega_modules)} 个 omega 模块")

print("\n" + "="*60)
print("STEP 2: 检查 workflow seeds")
print("="*60)

workflow_seeds = PROJECT_ROOT / "workflow_seeds"
if workflow_seeds.exists():
    seed_files = list(workflow_seeds.glob("*.json"))
    print(f"Found {len(seed_files)} seed files:")
    for sf in sorted(seed_files):
        print(f"   - {sf.name}")
else:
    print("workflow_seeds directory does not exist!")

print("\n" + "="*60)
print("STEP 3: 检查 MATLAB 参考结果")
print("="*60)

omega_custom_dir = Path(r"I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res")
if omega_custom_dir.exists():
    categories = {}
    for cat_dir in omega_custom_dir.iterdir():
        if cat_dir.is_dir():
            mat_files = [f for f in cat_dir.glob("*.mat")]
            categories[cat_dir.name] = len(mat_files)
            print(f"\n[{cat_dir.name}] {len(mat_files)} .mat files:")
            for mf in sorted(mat_files)[:5]:
                rel = mf.relative_to(cat_dir)
                print(f"   {rel}")
            if len(mat_files) > 5:
                print(f"   ... (and {len(mat_files)-5} more)")
else:
    print(f"[ERROR] Directory does not exist: {omega_custom_dir}")

print("\n" + "="*60)
print("STEP 4: NAS 参考数据")
print("="*60)

nas_ref_path = r"https://nasfile.personaltunnel.dpdns.org/files/Liuzheng/omega_final"
print(f"NAS Reference URL: {nas_ref_path}")
print("Note: Access requires FileBrowser extension")
