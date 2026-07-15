#!/usr/bin/env python3
"""
将指定文件夹下、指定扩展名的所有文本文件合并为一个文件。
用法：
    python merge_folder.py <文件夹路径> <扩展名> [输出文件]
示例：
    python merge_folder.py ./notes txt merged.txt
    python merge_folder.py ./logs .log > all_logs.txt
"""

import sys
import os

def main():
    if len(sys.argv) < 3:
        print("用法: python merge_folder.py <文件夹路径> <扩展名> [输出文件]")
        print("扩展名可带或不带点，如 txt 或 .txt 均可")
        sys.exit(1)

    folder = sys.argv[1]
    ext = sys.argv[2].lstrip(".")   # 去除可能输入的 '.'，统一处理
    output_file = sys.argv[3] if len(sys.argv) > 3 else None

    if not os.path.isdir(folder):
        print(f"错误：路径不存在或不是文件夹 —— {folder}", file=sys.stderr)
        sys.exit(1)

    # 收集所有符合扩展名的文件（仅当前文件夹，不含子文件夹）
    files = [
        f for f in os.listdir(folder)
        if os.path.isfile(os.path.join(folder, f)) and f.lower().endswith("." + ext.lower())
    ]
    files.sort()  # 按文件名排序，保证顺序稳定

    if not files:
        print(f"在 {folder} 中未找到扩展名为 .{ext} 的文件。", file=sys.stderr)
        sys.exit(0)

    # 选择输出目标：文件或标准输出
    if output_file:
        out = open(output_file, "wb")
    else:
        out = sys.stdout.buffer

    try:
        first = True
        for fname in files:
            full_path = os.path.join(folder, fname)

            if not first:
                out.write(b"---\n")
            first = False

            # 写入 “文件名:” 行
            out.write(fname.encode("utf-8") + b":\n")

            # 原样写入文件内容
            with open(full_path, "rb") as f:
                content = f.read()
            out.write(content)

            # 如果文件末尾没有换行，补一个，确保分隔符独占一行
            if content and content[-1] != 10:   # 10 是 b'\n' 的 ASCII
                out.write(b"\n")
    finally:
        if output_file:
            out.close()

if __name__ == "__main__":
    main()