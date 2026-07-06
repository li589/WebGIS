"""标准化模式枚举，替代散落的魔法字符串。"""
from __future__ import annotations
from enum import StrEnum


class RetrievalMode(StrEnum):
    """反演模式：单日反演与块反演共用。"""
    DH = "dh"
    DDCA = "ddca"
    OMEGA = "omega"


class DualTgMode(StrEnum):
    """daily_bundle 双温度梯度模式。"""
    PAPER_CT = "PAPER_CT"
    TSOIL1_ONLY = "TSOIL1_ONLY"
    TSOIL2_ONLY = "TSOIL2_ONLY"
