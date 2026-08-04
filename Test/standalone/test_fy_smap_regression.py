"""
FY/SMAP 反演全流程回归测试
==========================

目标:
1. 加载现有的 fy_raw_omega 和 smap_raw_omega 结果
2. 与 Omega_Custom_Res 中的 MATLAB 参考结果对比
3. 定位差异原因（可能是缓存问题或计算逻辑变化）
4. 重新运行全流程（如果需要）
"""

import sys
import io
import subprocess
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ===================== Configuration =====================
OMEGA_AVG_DAILY_PY = r"D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\algorithms\providers\Python\modules\omega_avg_daily.py"
ENV_PYTHON = r"D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Env\Python312\python.exe"

CUSTOM_RES_DIR = Path(r"I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res")

# FY Reference files
FY_RAW_OMEGA_FILES = list((CUSTOM_RES_DIR / "fy_raw_ω").glob("*.mat"))[:4]

# SMAP Reference files  
SMAP_RAW_OMEGA_FILES = list((CUSTOM_RES_DIR / "smap_raw_omega").glob("*.mat"))[:4]

print("="*70)
print("FY/SMAP 反演全流程回归测试")
print("="*70)

# Step 1: Check existing results
print("\n[1] 检查现有 MATLAB 参考结果...")

for label, ref_dir in [
    ("FY RAW OMEGA", CUSTOM_RES_DIR / "fy_raw_ω"),
    ("SMAP RAW OMEGA", CUSTOM_RES_DIR / "smap_raw_omega"),
]:
    print(f"\n{label}:")
    files = sorted(ref_dir.glob("*.mat")) if ref_dir.exists() else []
    for f in files:
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"   {f.name} ({size_mb:.2f} MB)")

# Step 2: Load and compare with Python results
print("\n\n[2] 准备对比分析...")
print(f"Python modules location: {Path(OMEGA_AVG_DAILY_PY).parent}")

# Step 3: Create comparison script
comparison_script = f"""
# -*- coding: utf-8 -*-
\"\"\"对比 FY/SMAP Python vs MATLAB 结果.\"\"\"
import sys
sys.path.insert(0, r'D:\\temp_desktop\\Proj\\Comprehensive Geographic Data Analysis system')

import numpy as np
from pathlib import Path
from scipy.io import loadmat

CUSTOM_RES = r'I:\\Geograph_DataSet\\Soil_Moisture\\Omega_Custom_Res'

def compare_mat_results():
    \"\"\"加载并对比 FY 和 SMAP 的结果.\"\"\"
    
    # FY 结果
    fy_dir = Path(CUSTOM_RES) / 'fy_raw_ω'
    print('\\n=== FY RAW OMEGA Results ===')
    for mat_file in sorted(fy_dir.glob('*.mat'))[:2]:  # First 2 files
        print(f'\\nFile: {{mat_file.stem}}')
        data = loadmat(mat_file)
        keys = [k for k in data.keys() if not k.startswith('__')]
        for key in keys[:5]:  # Print first 5 keys
            val = data[key]
            print(f'  {{key}}: shape={{val.shape}}, dtype={{val.dtype}}')
            if val.size < 100:
                print(f'    values: {{val.flatten()[:10]}}')
    
    # SMAP 结果
    smap_dir = Path(CUSTOM_RES) / 'smap_raw_omega'
    print('\\n\\n=== SMAP RAW OMEGA Results ===')
    for mat_file in sorted(smap_dir.glob('*.mat'))[:2]:
        print(f'\\nFile: {{mat_file.stem}}')
        data = loadmat(mat_file)
        keys = [k for k in data.keys() if not k.startswith('__')]
        for key in keys[:5]:
            val = data[key]
            print(f'  {{key}}: shape={{val.shape}}, dtype={{val.dtype}}')
            
compare_mat_results()
"""

comparison_file = Path(__file__).parent / "test_compare_matlab.py"
with open(comparison_file, 'w', encoding='utf-8') as f:
    f.write(comparison_script)

print(f"\nComparison script created: {comparison_file}")
print("\nTo run comparison:")
print(f'  python -c "{comparison_script}"')

# Step 4: Test current workflow
print("\n\n[3] 测试当前工作流执行...")
print(f"\nUsing Python: {ENV_PYTHON}")

# Quick check if omega module loads correctly
check_load = """
import sys
sys.path.insert(0, r'D:\\temp_desktop\\Proj\\Comprehensive Geographic Data Analysis system\\Code\\algorithms\\providers\\Python')

try:
    from modules.omega_avg_daily import OmegaAvgDailyModule
    print('\\n✓ OmegaAvgDailyModule loaded successfully')
    print(f'  Module name: {{OmegaAvgDailyModule.name}}')
    print(f'  Description: {{OmegaAvgDailyModule.description}}')
except Exception as e:
    print(f'\\n✗ Error loading module: {{e}}')
    import traceback
    traceback.print_exc()
"""

result = subprocess.run([ENV_PYTHON, '-c', check_load], 
                       capture_output=True, text=True, encoding='utf-8')
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)

print("\n\n【下一步建议】")
print("1. 使用上面的对比脚本来加载 MATLAB 结果")
print("2. 检查是否有相同的 .mat 文件被 Python 读取")
print("3. 对比两者的数据结构")
print("4. 如果差异很大，可能需要：")
print("   - 清理旧缓存")
print("   - 重新运行 D1 omega_block")
print("   - 重新运行 D2 avg-omega pipeline")
