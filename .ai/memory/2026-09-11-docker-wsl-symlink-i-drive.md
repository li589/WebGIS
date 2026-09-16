# 2026-09-11 Docker 启动失败：WSL 数据目录符号链接指向外接 I 盘

## 现象
Docker Desktop 启动报：
`starting WSL engine: installing main distribution: creating distribution destination dir:
mkdir C:\Users\likr\AppData\Local\Docker\wsl: Cannot create a file when that file already exists.`

## 根因链
1. `%LOCALAPPDATA%\Docker\wsl` 是 **符号链接**（2026-07-19 建）→ `I:\Docker\DockerDesktop`。
   Docker 设置里没有自定义数据目录，走的默认路径，所以完全依赖 I 盘在位。
2. I 盘（外接）不在位 → 链接成断链 → Go 的 `MkdirAll` 对"已存在但打不开"的入口返回
   ERROR_ALREADY_EXISTS，于是报出这个极具误导性的 "already exists"。
3. I 盘本身不稳定（见下）。

## I 盘忽隐忽现的原因（Windows 事件日志）
- **事件 158（主因）**：`磁盘 3 的磁盘标识符与连接到系统的一个或多个磁盘的磁盘标识符相同`
  → 磁盘签名冲突，Windows 反复将其脱机/不分配盘符 → 盘符时有时无。
- **事件 51（次因）**：`在设备 \Device\Harddisk2\DR60 上检测到一个错误`，同一时刻突发 8 次
  → I/O 错误，多见于线材/供电/接口，也可能是坏道。
- 无 Kernel-PnP 225（意外移除）记录 → 更像**逻辑脱机**而非物理掉线。

## 磁盘拓扑（注册表 Services\disk\Enum）
| Disk | 设备 | 说明 |
|------|------|------|
| 0 | NVMe SK hynix PC801 | 系统盘（C:） |
| 1 | NVMe HP SSD FX700 1TB | D: |
| 2 | SCSI\Disk&Ven_ASM&Prod_ASM1156 | 外接盘（报事件 51） |
| 3 | SCSI\Disk&Ven_ASM&Prod_ASM1156 | 外接盘（报事件 158，疑为 I:） |

两块外接盘同为 ASMedia ASM1156 桥接；若互为克隆则必然签名相同，需 `diskpart`
`select disk 3` + `uniqueid disk id=<新值>` 改签名（**仅数据盘，勿动 Disk 0**）。

## 处置与状态
- I 盘恢复在线后，`I:\Docker\DockerDesktop` 可读，含 `disk`、`main` 两个发行版目录 —— 数据仍在。
- 但 WSL 发行版已**全部注销**（`HKCU\...\Lxss` 无子项），Docker 会重装发行版；
  `wsl -l -v` 同样显示"未安装分发"。
- 修复动作：以**管理员身份**启动 Docker Desktop（本仓库硬约定：Windows 上 Docker 相关
  操作必须提权）。
- 长期建议：Docker 虚拟盘**不要放外接盘**。C: 尚有约 271G 可用，等 Docker 起来后用
  Settings → Resources → Advanced 的虚拟磁盘位置迁移到内部盘，一次性摆脱该故障模式。

## 工具链坑（本次取证可用/不可用）
- ❌ PowerShell 工具本会话**完全无输出**（连 `Get-Date` 都空），不可依赖。
- ❌ 从 bash 调 `powershell.exe` / `cmd.exe` 被安全策略拦截；`diskpart` 需提权（Permission denied）。
- ❌ `wmic` 已被新版 Windows 移除。
- ✅ 可用替代：`wevtutil qe System "/q:*[System[Provider[@Name='disk'] ...]]" /f:text /rd:true`
  （输出为 UTF-16，需 `| tr -d '\000'`）、`reg query`、`node -e` + `fs`（走 Windows API，
  比 git-bash 的 `/i` 盘符映射可靠）、`tasklist`。
- ⚠️ 判断外盘是否真在位，用 Node `fs.readdirSync("I:\\")` 而非 `ls /i`（后者会给出误导结果）。
