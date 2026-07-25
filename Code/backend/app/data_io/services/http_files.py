"""HTTP 附件响应头：安全编码中文文件名。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote


def content_disposition_attachment(filename: str) -> dict[str, str]:
    """生成可被 Starlette latin-1 编码的 Content-Disposition。

    浏览器优先使用 ``filename*``（UTF-8）；ASCII ``filename`` 仅作回退。
    """
    name = Path(filename or "download").name.strip() or "download"
    suffix = Path(name).suffix or ""
    ascii_fallback = f"download{suffix}" if suffix else "download.bin"
    # 仅保留 ASCII 安全字符，避免 header latin-1 崩溃
    safe_ascii = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in name
    )
    if not safe_ascii or safe_ascii.strip("._") == "":
        safe_ascii = ascii_fallback
    encoded = quote(name, safe="")
    return {
        "Content-Disposition": (
            f"attachment; filename=\"{safe_ascii}\"; filename*=UTF-8''{encoded}"
        )
    }
