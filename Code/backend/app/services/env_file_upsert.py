"""受控 upsert ``Code/backend/.env`` 键值（保留其它行与注释）。"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import BACKEND_ROOT

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def backend_env_path() -> Path:
    return BACKEND_ROOT / ".env"


def read_env_file_values(path: Path | None = None) -> dict[str, str]:
    """解析 .env 中未注释的 KEY=VALUE（后出现覆盖先出现）。"""
    env_path = path or backend_env_path()
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE.match(stripped)
        if not match:
            continue
        key, raw = match.group(1), match.group(2)
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            raw = raw[1:-1]
        values[key] = raw
    return values


def upsert_env_keys(
    updates: dict[str, str],
    *,
    path: Path | None = None,
) -> Path:
    """更新或追加指定键；不删除其它键/注释。返回写入路径。"""
    env_path = path or backend_env_path()
    cleaned = {
        str(k).strip(): str(v).strip()
        for k, v in updates.items()
        if str(k).strip() and str(v).strip()
    }
    if not cleaned:
        raise ValueError("no env keys to upsert")

    if env_path.is_file():
        try:
            original = env_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"cannot read env file: {env_path}") from exc
        lines = original.splitlines()
        # Preserve final newline presence when rewriting
        had_trailing_newline = original.endswith("\n") or original.endswith("\r\n")
    else:
        lines = []
        had_trailing_newline = True
        env_path.parent.mkdir(parents=True, exist_ok=True)

    remaining = dict(cleaned)
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            new_lines.append(line)
            continue
        match = _ENV_LINE.match(stripped)
        if not match:
            new_lines.append(line)
            continue
        key = match.group(1)
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)

    if remaining:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# Updated by Settings → data-source paths")
        for key, value in remaining.items():
            new_lines.append(f"{key}={value}")

    body = "\n".join(new_lines)
    if had_trailing_newline or not body.endswith("\n"):
        body = body + "\n"
    env_path.write_text(body, encoding="utf-8")
    return env_path
