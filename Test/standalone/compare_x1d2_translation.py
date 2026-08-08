"""归一化对比函数平移忠实性（X1/D2 重构复查工具）。

用法：
    python compare_x1d2_translation.py <旧文件.ts> <新文件.ts> [函数名...]

忽略：行首缩进、`deps.`/`workflowPoller.` 前缀（store 闭包→注入）、注释行、空行。
保留：控制流（if/for/while/try）、调用、赋值、字符串、运算符——用于暴露逻辑差异。
不传函数名时对比默认的 workflow 编排函数清单。
"""
import re
import sys


def extract_function(lines, start_idx):
    """从 start_idx 行开始提取函数体（大括号深度归零），返回 (text_lines, end_idx)。"""
    depth = 0
    started = False
    body = []
    for i in range(start_idx, len(lines)):
        line = lines[i]
        stripped = line.strip()
        # 跳过注释行（近似：行首 # 或 // 或 *）
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('/*'):
            continue
        depth += line.count('{') - line.count('}')
        if not started:
            # 函数签名行或装饰/闭合之前的行
            if '{' in line:
                started = True
            body.append(line)
            if depth <= 0 and started and i > start_idx:
                return body, i
            continue
        body.append(line)
        if depth <= 0:
            return body, i
    return body, len(lines) - 1


def normalize(line):
    line = line.strip()
    line = re.sub(r'\bdeps\.', '', line)          # deps. 前缀
    line = re.sub(r'\bworkflowPoller\.', '', line)  # poller 前缀（新文件）
    line = re.sub(r'^function\s+', 'function ', line)
    line = re.sub(r'^async function\s+', 'async function ', line)
    return line


def find_fn(lines, name):
    for i, line in enumerate(lines):
        if re.search(rf'(async )?function {re.escape(name)}\b', line):
            return i
    return None


def main(old_path, new_path, names):
    old_lines = open(old_path, encoding='utf-8').read().splitlines()
    new_lines = open(new_path, encoding='utf-8').read().splitlines()
    for name in names:
        oi = find_fn(old_lines, name)
        ni = find_fn(new_lines, name)
        if oi is None or ni is None:
            print(f'!! {name}: 缺失 old={oi is not None} new={ni is not None}')
            continue
        obody, oe = extract_function(old_lines, oi)
        nbody, ne = extract_function(new_lines, ni)
        onorm = [normalize(l) for l in obody if l.strip() and not l.strip().startswith(('//', '*', '/*'))]
        nnorm = [normalize(l) for l in nbody if l.strip() and not l.strip().startswith(('//', '*', '/*'))]
        # 行数对比
        print(f'== {name}: old={len(onorm)}行 new={len(nnorm)}行')
        # 逐行 diff（忽略空行差异后的对齐近似）
        import difflib
        diff = list(difflib.unified_diff(onorm, nnorm, lineterm='', n=1))
        real = [d for d in diff if d.startswith(('+', '-')) and not d.startswith(('+++', '---'))]
        if not real:
            print('   ✅ 完全一致')
        else:
            print(f'   ⚠️ 差异 {len(real)} 行（含注释/重命名噪音，需人工核对）:')
            for d in real[:40]:
                print(f'   {d}')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    old_path, new_path = sys.argv[1], sys.argv[2]
    if len(sys.argv) > 3:
        names = sys.argv[3:]
    else:
        names = [
            'registerExternalWorkflowRun', 'resolveRestoredCatalogId',
            'hydrateJobLayerFromEvents', 'restoreActiveWorkflows',
            'resolveRestoreWorkflowBridge', 'ensureRestoredRunGroup',
            'interruptWorkflowForCatalog', 'runWorkflowForCatalog',
            'scheduleWorkflowRetry', 'cancelWorkflowRunForJob',
            'retryWorkflowRunForJob',
        ]
    main(old_path, new_path, names)
