from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

from algorithms.fy import FyCommandStep


def inject_geoloc_metadata_to_vrt(source_vrt: str | Path, target_vrt: str | Path, metadata_block: str) -> Path:
    source_vrt = Path(source_vrt)
    target_vrt = Path(target_vrt)
    target_vrt.parent.mkdir(parents=True, exist_ok=True)

    inserted = False
    with source_vrt.open("r", encoding="utf-8") as src, target_vrt.open("w", encoding="utf-8") as dst:
        for line in src:
            if (not inserted) and ("<GCPList" in line or "</Metadata>" in line):
                dst.write(metadata_block)
                inserted = True
            dst.write(line)
        if not inserted:
            dst.write(metadata_block)
    return target_vrt


def execute_fy_command_steps(
    steps: list[FyCommandStep],
    logger: Any | None = None,
    shell: bool = True,
    stop_on_error: bool = True,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    total_steps = max(len(steps), 1)
    for index, step in enumerate(steps, start=1):
        if step.command.startswith("WRITE_GEOLOC_METADATA"):
            inject_geoloc_metadata_to_vrt(
                source_vrt=step.metadata["source_vrt"],
                target_vrt=step.metadata["target_vrt"],
                metadata_block=step.metadata["geoloc_metadata"],
            )
            results.append({"name": step.name, "returncode": 0, "outputs": list(step.outputs)})
            if logger is not None:
                logger.emit_progress("fy_execute", index / total_steps, f"Completed {step.name}")
            continue

        process = subprocess.run(
            step.command,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
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
                logger.emit_progress("fy_execute", index / total_steps, f"Completed {step.name}")
            else:
                logger.emit_error("fy_execute", f"{step.name} failed", {"stderr": process.stderr})
        if process.returncode != 0 and stop_on_error:
            raise RuntimeError(f"FY command step failed: {step.name}\n{process.stderr}")
    return results
