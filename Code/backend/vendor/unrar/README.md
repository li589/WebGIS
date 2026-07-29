# UnRAR（后端 vendored 控制台工具）

本目录存放 **RARLAB 官方控制台 UnRAR**，供 `app.data_io.services.archive_safe` 在服务端**无界面**解压 `.rar` 使用。

> 这是后端运行时依赖的第三方二进制，放在 `Code/backend/vendor/`，**不是**仓库根 `Tools/`（`Tools/` 仅放主线外辅助脚本）。

## 布局

```text
Code/backend/vendor/unrar/
├─ win-x64/UnRAR.exe   # Windows x64 控制台
├─ linux-x64/unrar     # Linux x64 控制台
├─ license-rarlab.txt
└─ README.md
```

查找顺序（见 `archive_safe._find_unrar_tool`）：

1. 本目录对应平台二进制  
2. 系统 PATH 中的 `unrar`（须通过控制台探测：打印 `UNRAR` + `Usage`）

生产 Linux 也可不携带本目录，改用：`sudo apt install unrar`。

## 重要：禁止用错二进制

| 正确 | 错误 |
|------|------|
| `win-x64/UnRAR.exe` / `linux-x64/unrar`（CLI） | 把 `unrarw64.exe`（自解压安装包）当工具 |
| `apt install unrar` / 本目录 linux 二进制 | 调用 WinRAR GUI / 执行用户上传的 SFX |

## 更新 Windows 二进制

1. 从 [RARLAB UnRAR for Windows](https://www.rarlab.com/rar_add.htm) 下载 `unrarw64.exe`（SFX，**不要**直接当工具）。
2. 静默解出真正 CLI：`unrarw64.exe -s -dC:\path\to\out`
3. 将解出的 `UnRAR.exe` 复制为 `win-x64/UnRAR.exe`
4. 验证（应立即打印 Usage，无窗口）：`win-x64\UnRAR.exe`

## 安全策略（由 archive_safe 执行）

- 拒绝 MZ/SFX 自解压上传（不执行、不弹窗）
- 路径穿越 / 符号链接 / 压缩炸弹（数量·体积·比率）
- 拒绝可执行与脚本扩展名
- 子进程无窗口；工具必须通过 `UNRAR`+`Usage` 探测
