# UnRAR（后端 vendored 控制台工具）

本目录存放 **RARLAB 官方控制台 UnRAR**，供 `app.data_io.services.archive_safe` 在服务端**无界面**解压 `.rar` 使用。

> 这是后端运行时依赖的第三方二进制，放在 `Code/backend/vendor/`，**不是**仓库根 `Tools/`（`Tools/` 仅放主线外辅助脚本）。

## 支持格式与工具矩阵

| 格式 | 实现 | 依赖 |
|------|------|------|
| `.zip` | Python `zipfile` | 无 |
| `.tar` / `.tar.gz` / `.tgz` / `.tar.bz2` / `.tbz2` / `.tar.xz` / `.txz` | Python `tarfile`（`r:*` 透明解压压缩层） | 无 |
| `.gz`（单文件，非 tar.gz） | Python `gzip` | 无 |
| `.rar` | 控制台 UnRAR（7z CLI 回退） | 本目录二进制或系统 `unrar` |
| `.7z` | 7-Zip CLI | `p7zip-full`（Linux）/ 7-Zip（Windows） |

## 布局

```text
Code/backend/vendor/unrar/
├─ win-x64/UnRAR.exe   # Windows x64 控制台
├─ linux-x64/unrar     # Linux x64 控制台（可选；生产可改用 apt）
├─ license-rarlab.txt
└─ README.md

Code/backend/vendor/7zip/          # 可选；不放二进制时依赖系统安装
├─ win-x64/7z.exe
└─ linux-x64/7z
```

查找顺序（见 `archive_safe._find_unrar_tool`）：

1. 本目录对应平台二进制  
2. 系统 PATH 中的 `unrar`（须通过控制台探测：打印 `UNRAR` + `Usage`）

7z 查找顺序（见 `archive_safe._find_7z`）：vendor → 平台常见安装位置（Windows `Program Files\7-Zip`；Linux `/usr/bin/7z`、`/usr/bin/7za`）→ PATH。GUI（`7zFM`/`7zG`）一律排除。

## Linux 生产策略

- **RAR**：`sudo apt install unrar`（Debian/Ubuntu 官方源，非 free 分支；`unrar-free` 对 RAR5 支持不完整，不推荐）。或从 [RARLAB](https://www.rarlab.com/rar_add.htm) 下载 `rarlinux-x64-*.tar.gz`，解出 `unrar` 放入 `vendor/unrar/linux-x64/`（`chmod +x`）。
- **7z**：`sudo apt install p7zip-full`（提供 `/usr/bin/7z`，同时覆盖 RAR 回退）。
- CI（Ubuntu）已具备 `unrar`；本地 Windows 联调 RAR 测试需 `vendor/unrar/win-x64/UnRAR.exe`（gitignore，下载方式见下）。

## 重要：禁止用错二进制

| 正确 | 错误 |
|------|------|
| `win-x64/UnRAR.exe` / `linux-x64/unrar`（CLI） | 把 `unrarw64.exe`（自解压安装包）当工具 |
| `apt install unrar` / 本目录 linux 二进制 | 调用 WinRAR GUI / 执行用户上传的 SFX |
| `apt install p7zip-full`（CLI `7z`） | 依赖 7-Zip GUI / `7zFM` |

## 更新 Windows 二进制

1. 从 [RARLAB UnRAR for Windows](https://www.rarlab.com/rar_add.htm) 下载 `unrarw64.exe`（SFX，**不要**直接当工具）。
2. 静默解出真正 CLI：`unrarw64.exe -s -dC:\path\to\out`
3. 将解出的 `UnRAR.exe` 复制为 `win-x64/UnRAR.exe`
4. 验证（应立即打印 Usage，无窗口）：`win-x64\UnRAR.exe`

## 安全策略（由 archive_safe 执行）

- 拒绝 MZ/SFX 自解压上传（不执行、不弹窗）
- 路径穿越 / 符号链接 / 压缩炸弹（数量·体积·比率，全部格式一致）
- 拒绝可执行与脚本扩展名
- 子进程无窗口；UnRAR 工具必须通过 `UNRAR`+`Usage` 探测
