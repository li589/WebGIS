from __future__ import annotations

from pathlib import Path
from typing import Any


def _normalize_hdf5_mat_value(value: Any) -> Any:
    import numpy as np

    array = np.asarray(value)
    if array.dtype.kind in {"S", "U"}:
        return array
    if array.ndim >= 2:
        axes = tuple(range(array.ndim - 1, -1, -1))
        array = np.transpose(array, axes=axes)
    return array


def _load_hdf5_node(node: Any) -> Any:
    import h5py

    if isinstance(node, h5py.Dataset):
        return _normalize_hdf5_mat_value(node[()])
    if isinstance(node, h5py.Group):
        payload: dict[str, Any] = {}
        for key, value in node.items():
            if key.startswith("#"):
                continue
            payload[key] = _load_hdf5_node(value)
        return payload
    raise TypeError(f"Unsupported HDF5 node type: {type(node)!r}")


def _load_v73_mat_file(file_path: Path) -> dict[str, Any]:
    import h5py

    payload: dict[str, Any] = {}
    with h5py.File(file_path, "r") as handle:
        for key, value in handle.items():
            if key.startswith("#"):
                continue
            payload[key] = _load_hdf5_node(value)
    return payload


def load_mat_file(file_path: str | Path) -> dict[str, Any]:
    """Load a .mat file, auto-detecting MAT v7.3 (HDF5) vs v5 (scipy).

    On Windows, ``h5py.is_hdf5()`` may raise ``OSError`` instead of returning
    ``False`` for certain files (antivirus, locking, or permission edge cases).
    Catch that and fall through to scipy.
    """
    import h5py
    from scipy.io import loadmat

    file_path = Path(file_path)
    file_path_str = str(file_path)
    try:
        is_hdf5 = h5py.is_hdf5(file_path_str)
    except OSError:
        is_hdf5 = False
    if is_hdf5:
        return _load_v73_mat_file(file_path_str)
    try:
        payload = loadmat(file_path_str, squeeze_me=True, struct_as_record=False)
        return {
            key: value for key, value in payload.items() if not key.startswith("__")
        }
    except NotImplementedError as exc:
        if "Please use HDF reader for matlab v7.3 files" not in str(exc):
            raise
        return _load_v73_mat_file(file_path_str)
    except (FileNotFoundError, OSError):
        # Windows NTFS 可能出现文件存在于目录列表但无法 open() 的情况
        # （文件系统损坏 / 权限 / 杀软锁定）。向上传播调用方自行处理回退。
        raise


def normalize_aliases_param(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        parts = tuple(part.strip() for part in value.split(",") if part.strip())
        return parts or default
    if isinstance(value, (list, tuple)):
        parts = tuple(str(part).strip() for part in value if str(part).strip())
        return parts or default
    text = str(value).strip()
    return (text,) if text else default


def get_first_available(payload: dict[str, Any], aliases: list[str]) -> Any:
    for alias in aliases:
        if alias in payload:
            return payload[alias]
    raise KeyError(f"Missing required variable. Tried aliases: {aliases}")


def extract_inversion_inputs(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "tbv": get_first_available(payload, ["TBv", "tbv", "Tbv"]),
        "tbh": get_first_available(payload, ["TBh", "tbh", "Tbh"]),
        "ts": get_first_available(payload, ["Ts", "ts", "TC", "Tg"]),
        "tau_ini": get_first_available(payload, ["Tau_ini", "tau_ini", "Tau"]),
        "clay_fraction": get_first_available(payload, ["CF", "cf", "ClayFraction"]),
        "albedo": get_first_available(payload, ["Albedo", "ALBEDO", "albedo"]),
        "porosity": get_first_available(payload, ["porosity", "Porosity"]),
        "theta_deg": get_first_available(payload, ["Theta", "theta", "IA"]),
    }


def extract_ddca_inputs(payload: dict[str, Any]) -> dict[str, Any]:
    result = extract_inversion_inputs(payload)
    result["h_value"] = get_first_available(payload, ["H", "h", "DH"])
    return result
