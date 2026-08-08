
# -*- coding: utf-8 -*-
"""对比 FY/SMAP Python vs MATLAB 结果."""
import sys
sys.path.insert(0, r'D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system')

import numpy as np
from pathlib import Path
from scipy.io import loadmat

CUSTOM_RES = r'I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res'

def compare_mat_results():
    """加载并对比 FY 和 SMAP 的结果."""

    # FY 结果
    fy_dir = Path(CUSTOM_RES) / 'fy_raw_ω'
    print('\n=== FY RAW OMEGA Results ===')
    for mat_file in sorted(fy_dir.glob('*.mat'))[:2]:  # First 2 files
        print(f'\nFile: {mat_file.stem}')
        data = loadmat(mat_file)
        keys = [k for k in data.keys() if not k.startswith('__')]
        for key in keys[:5]:  # Print first 5 keys
            val = data[key]
            print(f'  {key}: shape={val.shape}, dtype={val.dtype}')
            if val.size < 100:
                print(f'    values: {val.flatten()[:10]}')

    # SMAP 结果
    smap_dir = Path(CUSTOM_RES) / 'smap_raw_omega'
    print('\n\n=== SMAP RAW OMEGA Results ===')
    for mat_file in sorted(smap_dir.glob('*.mat'))[:2]:
        print(f'\nFile: {mat_file.stem}')
        data = loadmat(mat_file)
        keys = [k for k in data.keys() if not k.startswith('__')]
        for key in keys[:5]:
            val = data[key]
            print(f'  {key}: shape={val.shape}, dtype={val.dtype}')

compare_mat_results()
