from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from algorithms.fy import FyCommandStep


def _build_hidden_creationflags() -> dict[str, Any]:
    """构建跨平台的子进程启动参数，在 Windows 上隐藏控制台黑框窗口。"""
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000，阻止弹出 cmd.exe 黑框
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def inject_geoloc_metadata_to_vrt(
    source_vrt: str | Path, target_vrt: str | Path, metadata_block: str
) -> Path:
    source_vrt = Path(source_vrt)
    target_vrt = Path(target_vrt)
    target_vrt.parent.mkdir(parents=True, exist_ok=True)

    inserted = False
    with (
        source_vrt.open("r", encoding="utf-8") as src,
        target_vrt.open("w", encoding="utf-8") as dst,
    ):
        for line in src:
            if (not inserted) and ("<GCPList" in line or "</Metadata>" in line):
                dst.write(metadata_block)
                inserted = True
            dst.write(line)
        if not inserted:
            dst.write(metadata_block)
    return target_vrt


def extract_tb_channel_to_h5(
    source_hdf: str | Path,
    h5_group_path: str,
    channel_index: int,
    target_h5: str | Path,
) -> Path:
    """FY-3F 3D TB 抽通道 → 2D 临时 HDF5（参照 FY3F_MWRI_mosaic.py 先例）。

    GDAL 将 (scanline, pixel, channel) 3D 数据集暴露为转置多波段栅格，
    ``-b`` 无法选通道；先经 h5py 抽取为 2D 再走 gdal_translate。
    """
    import h5py

    source_hdf = Path(source_hdf)
    target_h5 = Path(target_h5)
    target_h5.parent.mkdir(parents=True, exist_ok=True)
    with (
        h5py.File(source_hdf, "r") as src,
        h5py.File(target_h5, "w") as dst,
    ):
        tb_2d = src[h5_group_path][:, :, channel_index]
        dst.create_dataset("TB", data=tb_2d)
    return target_h5


def execute_fy_command_steps(
    steps: list[FyCommandStep],
    logger: Any | None = None,
    shell: bool = True,
    stop_on_error: bool = True,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    total_steps = max(len(steps), 1)
    hidden_kwargs = _build_hidden_creationflags()
    for index, step in enumerate(steps, start=1):
        if step.command.startswith("WRITE_GEOLOC_METADATA"):
            inject_geoloc_metadata_to_vrt(
                source_vrt=step.metadata["source_vrt"],
                target_vrt=step.metadata["target_vrt"],
                metadata_block=step.metadata["geoloc_metadata"],
            )
            results.append(
                {"name": step.name, "returncode": 0, "outputs": list(step.outputs)}
            )
            if logger is not None:
                logger.emit_progress(
                    "fy_execute", index / total_steps, f"Completed {step.name}"
                )
            continue

        if step.command.startswith("EXTRACT_TB_CHANNEL"):
            try:
                extract_tb_channel_to_h5(
                    source_hdf=step.metadata["source_hdf"],
                    h5_group_path=step.metadata["h5_group_path"],
                    channel_index=int(step.metadata["channel_index"]),
                    target_h5=step.metadata["target_h5"],
                )
                returncode = 0
                stderr = ""
            except Exception as exc:  # noqa: BLE001
                returncode = 1
                stderr = str(exc)
            results.append(
                {
                    "name": step.name,
                    "returncode": returncode,
                    "stderr": stderr,
                    "outputs": list(step.outputs),
                }
            )
            if logger is not None:
                if returncode == 0:
                    logger.emit_progress(
                        "fy_execute", index / total_steps, f"Completed {step.name}"
                    )
                else:
                    logger.emit_error(
                        "fy_execute", f"{step.name} failed", {"stderr": stderr}
                    )
            if returncode != 0 and stop_on_error:
                raise RuntimeError(f"FY command step failed: {step.name}\n{stderr}")
            continue

        process = subprocess.run(
            step.command,
            shell=shell,
            capture_output=True,
            text=True,
            **hidden_kwargs,
        )
        results.append(
            {
                "name": step.name,
                "returncode": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
                "outputs": list(step.outputs),
            }
        )
        if logger is not None:
            if process.returncode == 0:
                logger.emit_progress(
                    "fy_execute", index / total_steps, f"Completed {step.name}"
                )
            else:
                logger.emit_error(
                    "fy_execute", f"{step.name} failed", {"stderr": process.stderr}
                )
        if process.returncode != 0 and stop_on_error:
            raise RuntimeError(f"FY command step failed: {step.name}\n{process.stderr}")
    return results
