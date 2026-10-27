"""NAS 十五年成果按需出图（nas_ondemand）。

把 NAS 上老师/师兄的逐日 ω/SM/VOD 成果，按「用户在看哪一天」按需取一帧、
本地渲染成 PNG 落盘，缓存上限 2000 帧，超限按 LRU 淘汰。

═══════════════════════════════════════════════════════════════════════════
红线声明（用户 2026-10-27 明令；改本包任何代码前必须先问用户）
═══════════════════════════════════════════════════════════════════════════
1. NAS 只读。全包唯一的非 GET 请求是 ``POST /api/login``（只换 token，
   不碰任何文件）；其余一律 ``GET``。
2. 只能读 ``config.ALLOWED_NAS_PREFIXES`` 里那几组目录。路径校验发生在
   发请求之前 —— 对不上前缀直接抛 ``NasPathDenied``，一个字节都不发出去。
3. 禁止引用本地 ``Z:`` 盘符（该盘已映射到 NAS，具备写/删能力）。
4. 只下载 ``YYYYMMDD.mat``，其它后缀一概不取。
5. 本地只写 ``Data/ProjectOutput/imports/imported-nas-*`` 这族目录；
   淘汰只删这几族目录里的帧文件，其它 ``imported-*`` 一概不遍历。
═══════════════════════════════════════════════════════════════════════════

用法（避免在包 ``__init__`` 里 import 重模块，统一走子模块）：
    from app.services.nas_ondemand.service import ensure_frame, cache_state
"""

__all__ = ["cache", "config", "fetcher", "renderer", "service"]
