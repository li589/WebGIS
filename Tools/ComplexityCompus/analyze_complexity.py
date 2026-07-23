import json
import os
import subprocess
import sys
from collections import defaultdict

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 脚本所在目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(BASE_DIR))  # 项目根目录
json_path = os.path.join(BASE_DIR, "complexity.json")
outjson_path = os.path.join(BASE_DIR, "complexity_report.json")


# ============================================================
# 工具函数
# ============================================================
def get_file_size(size):
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.2f} {units[index]}"


# ============================================================
# 运行 radon 生成 complexity.json
# ============================================================
radon_cmd = [
    sys.executable,
    "-m",
    "radon",
    "cc",
    "./",
    "-i",
    "Env,venv,.venv,node_modules,.git,__pycache__,build,dist",
    "-e",
    "*/migrations/*,*/tests/*",
    "-a",
    "-s",
    "-j",
    "-o",
    "SCORE",
]

print("执行 radon 命令中......")
print(f"  命令: {' '.join(radon_cmd)}")
print(f"  工作目录: {PROJECT_ROOT}")

# 直接用 Python 捕获 stdout 写入文件，彻底避免 PowerShell/cmd 编码问题
with open(json_path, "w", encoding="utf-8") as f:
    result = subprocess.run(
        radon_cmd,
        cwd=PROJECT_ROOT,
        stdout=f,  # radon 的 JSON 输出直接写入文件
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

if result.returncode != 0:
    print(f"⚠️ radon 返回非零退出码: {result.returncode}")
    if result.stderr:
        print(f"stderr: {result.stderr[:2000]}")
else:
    print("✅ radon 执行完成\n")

print(f"正在加载 {json_path}，请稍候...")
source_size_bytes = os.path.getsize(json_path)

# ============================================================
# 读取并解析 complexity.json
# ============================================================
with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"共分析了 {len(data)} 个 Python 文件\n")

# 收集所有函数/方法的复杂度
all_blocks = []
grade_counts = defaultdict(int)
file_complexity = defaultdict(list)

for filepath, blocks in data.items():
    for b in blocks:
        if isinstance(b, dict) and "complexity" in b:
            comp = b["complexity"]
            name = b.get("name", "unknown")
            lineno = b.get("lineno", 0)
            rank = b.get("rank", "?")

            all_blocks.append((comp, filepath, name, lineno, rank))
            grade_counts[rank] += 1
            file_complexity[filepath].append(comp)

# 按等级统计
print("=" * 70)
print("一、复杂度等级分布")
print("=" * 70)
grade_info = {
    "A": "(1-5)   简单 - 风险极低",
    "B": "(6-10)  简单 - 风险低",
    "C": "(11-15) 适中 - 风险中等",
    "D": "(16-20) 较复杂 - 风险较高",
    "E": "(21-30) 复杂 - 风险高",
    "F": "(31+)   极复杂 - 风险极高",
}
total = sum(grade_counts.values())
for grade in ["A", "B", "C", "D", "E", "F"]:
    count = grade_counts.get(grade, 0)
    pct = count / total * 100 if total > 0 else 0
    bar = "█" * int(pct / 2)
    print(f"  {grade} {grade_info[grade]:30s} {count:>5d} ({pct:5.1f}%) {bar}")

# TOP 30 最复杂的函数
print("\n" + "=" * 70)
print("二、TOP 30 最复杂函数（重构优先级清单）")
print("=" * 70)
all_blocks.sort(reverse=True)
print(f"  {'#':>3s}  {'复杂度':>6s}  {'等级':>4s}  {'文件:行号':<55s}  函数名")
print("-" * 100)
for i, (comp, path, name, lineno, rank) in enumerate(all_blocks[:30], 1):
    short_path = path.replace("\\", "/")
    if len(short_path) > 50:
        short_path = ".../" + short_path[-47:]
    print(f"  {i:>3d}. {comp:>6d}    {rank}    {short_path}:{lineno:<10d}  {name}")

# TOP 20 最复杂的文件
print("\n" + "=" * 70)
print("三、TOP 20 最复杂文件（按文件总复杂度排序）")
print("=" * 70)
file_totals = [
    (sum(comps), len(comps), max(comps), path)
    for path, comps in file_complexity.items()
]
file_totals.sort(reverse=True)
print(f"  {'#':>3s}  {'总复杂度':>8s}  {'函数数':>6s}  {'最高值':>6s}  文件路径")
print("-" * 100)
for i, (total_comp, func_count, max_comp, path) in enumerate(file_totals[:20], 1):
    short_path = path.replace("\\", "/")
    if len(short_path) > 60:
        short_path = ".../" + short_path[-57:]
    print(
        f"  {i:>3d}. {total_comp:>8d}    {func_count:>4d}    {max_comp:>6d}    {short_path}"
    )

# 高危函数详情 (D/E/F 级)
print("\n" + "=" * 70)
print("四、高危函数详情（D/E/F 级，复杂度 >= 16）")
print("=" * 70)
dangerous = [b for b in all_blocks if b[0] >= 16]
print(f"共发现 {len(dangerous)} 个高危函数\n")

for comp, path, name, lineno, rank in dangerous:
    short_path = path.replace("\\", "/")
    if len(short_path) > 55:
        short_path = ".../" + short_path[-52:]
    flag = "🔴" if comp >= 31 else "🟡" if comp >= 21 else "🟠"
    print(f"  {flag} [{rank}] 复杂度={comp:>3d}  {short_path}:{lineno}  →  {name}()")

# 保存精简报告（路径与开头定义的 outjson_path 一致）
report = {
    "summary": {
        "total_files": len(data),
        "total_functions": total,
        "grade_distribution": dict(grade_counts),
        "dangerous_count": len(dangerous),
    },
    "top30_complex_functions": [
        {"complexity": c, "rank": r, "file": p, "line": l, "name": n}
        for c, p, n, l, r in all_blocks[:30]
    ],
    "top20_complex_files": [
        {"total_complexity": tc, "func_count": fc, "max_complexity": mc, "file": p}
        for tc, fc, mc, p in file_totals[:20]
    ],
    "dangerous_functions": [
        {"complexity": c, "rank": r, "file": p, "line": l, "name": n}
        for c, p, n, l, r in dangerous
    ],
}

with open(outjson_path, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

out_size_bytes = os.path.getsize(outjson_path)
print(f"\n✅ 精简报告已保存到 {outjson_path}")
print(
    f"   原始文件: {get_file_size(source_size_bytes)} → 精简后: 只有核心数据({get_file_size(out_size_bytes)})"
)
