"""导入存储路径与限额。"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings

_OUTPUT_ROOT = (
    Path(settings.output_root)
    if settings.output_root
    else Path.cwd() / "imports_output"
)
IMPORTS_DIR = _OUTPUT_ROOT / "imports"
STAGING_DIR = IMPORTS_DIR / "_staging"
JOBS_DIR = IMPORTS_DIR / "_jobs"
DOC_SESSIONS_DIR = IMPORTS_DIR / "_documents"

MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MiB
MAX_IMPORTS_TOTAL_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB
CHUNK_SYNC_THRESHOLD_BYTES = 100 * 1024 * 1024  # >100 MiB → async job
STAGING_TTL_SECONDS = 24 * 3600
PREVIEW_FEATURE_LIMIT = 5000
DOC_PREVIEW_ROW_LIMIT = 5000


def ensure_imports_root() -> Path:
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    DOC_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return IMPORTS_DIR


def dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def assert_quota_available(extra_bytes: int = 0) -> None:
    ensure_imports_root()
    used = dir_size_bytes(IMPORTS_DIR)
    if used + max(0, extra_bytes) > MAX_IMPORTS_TOTAL_BYTES:
        raise QuotaExceededError("导入存储配额已满，请清理旧导入后再试")


class QuotaExceededError(RuntimeError):
    """Imports disk quota exceeded."""
