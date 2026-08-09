"""SHP/DBF 多语言编码解析（跨 Windows / Linux）。

DBF 属性表编码在现实数据中极不统一：
- 国内 ArcGIS / 超图等常为 GBK / GB18030，``.cpg`` 却写 ``ANSI`` 或缺失；
- 外网数据可能是 UTF-8、Big5、Shift-JIS、cp125x、OEM 页等；
- Windows 与 Linux 上可用的 codec 名不完全一致（如 ``mbcs`` 仅 Windows）。

本模块专责：
1. 解析 ``.cpg`` / DBF Language Driver ID（LDID）；
2. 按平台与 locale 生成可尝试的编码候选；
3. 用严格解码 + 文本质量打分选择最佳编码；
4. 提供统一的 pyshp / 字节解码入口，供矢量导入使用。
"""

from __future__ import annotations

import codecs
import locale
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Iterable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 别名与 LDID
# ---------------------------------------------------------------------------

# .cpg / 人类可读名 → Python codec（优先跨平台名）
_CODEPAGE_ALIASES: dict[str, str] = {
    "65001": "utf-8",
    "utf8": "utf-8",
    "utf-8": "utf-8",
    "utf-8-sig": "utf-8-sig",
    "936": "gbk",
    "cp936": "gbk",
    "gbk": "gbk",
    "gb2312": "gbk",
    "gb18030": "gb18030",
    "ansi": "gbk",  # 国内常见误标；欧美场景会在候选里额外插入 cp1252
    "950": "big5",
    "cp950": "big5",
    "big5": "big5",
    "big5hkscs": "big5hkscs",
    "932": "cp932",
    "cp932": "cp932",
    "shift-jis": "shift_jis",
    "shift_jis": "shift_jis",
    "sjis": "shift_jis",
    "949": "cp949",
    "cp949": "cp949",
    "euc-kr": "euc_kr",
    "euc_kr": "euc_kr",
    "1250": "cp1250",
    "1251": "cp1251",
    "1252": "cp1252",
    "1253": "cp1253",
    "1254": "cp1254",
    "1255": "cp1255",
    "1256": "cp1256",
    "1257": "cp1257",
    "1258": "cp1258",
    "8859-1": "latin-1",
    "iso-8859-1": "latin-1",
    "latin1": "latin-1",
    "latin-1": "latin-1",
    "iso-8859-2": "iso8859-2",
    "iso-8859-5": "iso8859-5",
    "iso-8859-9": "iso8859-9",
    "iso-8859-15": "iso8859-15",
    "437": "cp437",
    "850": "cp850",
    "852": "cp852",
    "855": "cp855",
    "866": "cp866",
    "874": "cp874",
    "koi8-r": "koi8-r",
    "koi8_r": "koi8-r",
}

# DBF header Language Driver ID (offset 29) → codec（ESRI / dBase 常见映射）
_DBF_LDID_CODEPAGES: dict[int, str] = {
    0x01: "cp437",
    0x02: "cp850",
    0x03: "cp1252",
    0x08: "cp865",
    0x09: "cp437",
    0x0A: "cp850",
    0x0B: "cp437",
    0x0D: "cp437",
    0x0E: "cp850",
    0x0F: "cp437",
    0x10: "cp850",
    0x11: "cp437",
    0x12: "cp850",
    0x13: "cp932",
    0x14: "cp850",
    0x15: "cp437",
    0x16: "cp850",
    0x17: "cp865",
    0x18: "cp437",
    0x19: "cp437",
    0x1A: "cp850",
    0x1B: "cp437",
    0x1C: "cp863",
    0x1D: "cp850",
    0x1F: "cp852",
    0x22: "cp852",
    0x23: "cp852",
    0x24: "cp860",
    0x25: "cp850",
    0x26: "cp866",
    0x37: "cp850",
    0x40: "cp852",
    0x4D: "gbk",  # Simplified Chinese
    0x4E: "cp949",  # Korean
    0x4F: "big5",  # Traditional Chinese
    0x50: "cp874",
    0x57: "cp1252",
    0x58: "cp1252",
    0x59: "cp1252",
    0x64: "cp852",
    0x65: "cp866",
    0x66: "cp865",
    0x67: "cp861",
    0x6A: "cp737",
    0x6B: "cp857",
    0x6C: "cp863",
    0x78: "cp950",
    0x79: "cp949",
    0x7A: "cp936",
    0x7B: "cp932",
    0x7C: "gb18030",
    0x86: "cp737",
    0x87: "cp852",
    0x88: "cp857",
    0xC8: "cp1250",
    0xC9: "cp1251",
    0xCA: "cp1254",
    0xCB: "cp1253",
    0xCC: "cp1257",
}

# 全量回退池（再按平台可用性过滤）；utf-8 与中文编码靠前
_FALLBACK_POOL: tuple[str, ...] = (
    "utf-8",
    "gb18030",
    "gbk",
    "big5",
    "big5hkscs",
    "cp932",
    "shift_jis",
    "cp949",
    "euc_kr",
    "cp1252",
    "cp1250",
    "cp1251",
    "cp1253",
    "cp1254",
    "cp1255",
    "cp1256",
    "cp1257",
    "cp1258",
    "cp874",
    "cp437",
    "cp850",
    "cp852",
    "cp855",
    "cp866",
    "koi8-r",
    "iso8859-1",
    "iso8859-2",
    "iso8859-5",
    "iso8859-9",
    "iso8859-15",
    "latin-1",
)

# Windows 专有 / 易踩坑，Linux 上跳过
_WINDOWS_ONLY_CODECS = frozenset({"mbcs", "oem", "ansi"})

_CJK_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\u3040-\u30ff\u31f0-\u31ff"  # kana
    r"\uac00-\ud7af]"  # hangul
)


@dataclass(frozen=True)
class EncodingProbeResult:
    """一次编码探测的结果。"""

    encoding: str
    score: float
    strict: bool
    field_names: tuple[str, ...] = ()
    sample_values: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass
class EncodingResolution:
    """最终选定编码及诊断信息。"""

    encoding: str
    strict: bool
    score: float
    sources: list[str] = field(default_factory=list)
    candidates_tried: list[str] = field(default_factory=list)
    platform: str = field(default_factory=lambda: sys.platform)
    locale: str = ""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def codec_available(name: str) -> bool:
    """当前解释器是否可加载该 codec（处理 Win/Linux 差异）。"""
    key = (name or "").strip().lower()
    if not key:
        return False
    if key in _WINDOWS_ONLY_CODECS and sys.platform != "win32":
        return False
    if key == "mbcs" and sys.platform != "win32":
        return False
    try:
        codecs.lookup(key)
        return True
    except LookupError:
        return False


def normalize_encoding_name(raw: str | None) -> str | None:
    """将 .cpg / 代码页数字 / 别名规范为 Python codec 名。"""
    if raw is None:
        return None
    token = str(raw).strip().strip("\x00").lower()
    if not token:
        return None
    token = token.replace(" ", "").replace("_", "-")
    # windows-936 / codepage936
    token = token.replace("windows-", "").replace("codepage", "").replace("cp-", "cp")
    compact = token.replace("-", "")
    for key in (token, compact, token.replace("-", "_")):
        if key in _CODEPAGE_ALIASES:
            enc = _CODEPAGE_ALIASES[key]
            return enc if codec_available(enc) else None
    digits = "".join(ch for ch in token if ch.isdigit())
    if digits and digits in _CODEPAGE_ALIASES:
        enc = _CODEPAGE_ALIASES[digits]
        return enc if codec_available(enc) else None
    # 直接当作 codec 名试
    for candidate in (token, token.replace("-", "_"), f"cp{digits}" if digits else ""):
        if candidate and codec_available(candidate):
            return candidate
    return None


def platform_locale_hints() -> list[str]:
    """根据系统 locale 给出优先编码（不保证正确，仅作排序加权）。"""
    hints: list[str] = []
    loc = ""
    try:
        loc = locale.setlocale(locale.LC_CTYPE) or ""
    except locale.Error:
        loc = ""
    if not loc or loc in {"C", "POSIX"}:
        try:
            loc = locale.getpreferredencoding(False) or ""
        except Exception:
            loc = ""
    low = loc.lower()
    if any(x in low for x in ("zh_cn", "zh-cn", "chinese_china", "chs", "gbk", "936")):
        hints.extend(["gb18030", "gbk"])
    elif any(x in low for x in ("zh_tw", "zh-tw", "zh_hk", "big5", "950")):
        hints.extend(["big5", "big5hkscs"])
    elif any(x in low for x in ("ja", "japan", "932", "shift")):
        hints.extend(["cp932", "shift_jis"])
    elif any(x in low for x in ("ko", "korea", "949")):
        hints.extend(["cp949", "euc_kr"])
    elif any(x in low for x in ("ru", "cyril", "1251", "866")):
        hints.extend(["cp1251", "cp866", "koi8-r"])
    elif sys.platform == "win32":
        # 西欧 Windows 默认常接近 cp1252
        hints.append("cp1252")
    # 系统首选编码本身
    pref = normalize_encoding_name(locale.getpreferredencoding(False) or "")
    if pref:
        hints.insert(0, pref)
    return [h for h in hints if codec_available(h)]


def is_encoding_error(exc: BaseException) -> bool:
    if isinstance(exc, UnicodeError):
        return True
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    return (
        "could not decode" in msg
        or "codec can't decode" in msg
        or "codec can't encode" in msg
        or "dbffileexception" in msg
        or "dbffileexception" in name
        or "unicode" in name
    )


# ---------------------------------------------------------------------------
# .cpg / LDID
# ---------------------------------------------------------------------------


def read_cpg_raw(shp_or_dbf: Path) -> str | None:
    stem_path = shp_or_dbf
    if stem_path.suffix.lower() in {".shp", ".dbf", ".shx", ".prj"}:
        base = stem_path.with_suffix("")
    else:
        base = stem_path
    for candidate in (
        Path(str(base) + ".cpg"),
        Path(str(base) + ".CPG"),
        stem_path.with_suffix(".cpg"),
        stem_path.with_suffix(".CPG"),
        stem_path.parent / f"{stem_path.stem}.cpg",
    ):
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="ascii", errors="ignore")
            except OSError:
                continue
    return None


def read_cpg_encoding(shp_or_dbf: Path) -> str | None:
    text = read_cpg_raw(shp_or_dbf)
    if text is None:
        return None
    for line in text.splitlines():
        enc = normalize_encoding_name(line)
        if enc:
            return enc
    return normalize_encoding_name(text)


def read_dbf_ldid(dbf_path: Path) -> int | None:
    """读取 DBF 头 Language Driver ID（第 30 字节，0-based offset 29）。"""
    path = (
        dbf_path if dbf_path.suffix.lower() == ".dbf" else dbf_path.with_suffix(".dbf")
    )
    if not path.is_file():
        return None
    try:
        with path.open("rb") as fh:
            head = fh.read(32)
    except OSError:
        return None
    if len(head) < 30:
        return None
    return head[29]


def ldid_to_encoding(ldid: int | None) -> str | None:
    if ldid is None or ldid == 0:
        return None
    enc = _DBF_LDID_CODEPAGES.get(ldid)
    if enc and codec_available(enc):
        return enc
    return None


# ---------------------------------------------------------------------------
# 候选列表
# ---------------------------------------------------------------------------


def build_encoding_candidates(
    shp_or_dbf: Path,
    *,
    extra: Iterable[str] | None = None,
) -> tuple[list[str], list[str]]:
    """生成编码尝试顺序与来源标签。

    Returns:
        (encodings, sources) sources 与 encodings 对齐描述来源，如 ``cpg`` / ``ldid``。
    """
    ordered: list[str] = []
    sources: list[str] = []
    seen: set[str] = set()

    def _add(enc: str | None, source: str) -> None:
        if not enc or not codec_available(enc):
            return
        key = enc.lower()
        if key in seen:
            return
        seen.add(key)
        ordered.append(enc)
        sources.append(source)

    cpg_raw = read_cpg_raw(shp_or_dbf)
    cpg = normalize_encoding_name(cpg_raw) if cpg_raw else None
    _add(cpg, "cpg")
    if cpg_raw and "ansi" in cpg_raw.lower():
        _add("gbk", "cpg-ansi→gbk")
        _add("cp1252", "cpg-ansi→cp1252")
        _add("gb18030", "cpg-ansi→gb18030")

    ldid = read_dbf_ldid(
        shp_or_dbf
        if shp_or_dbf.suffix.lower() == ".dbf"
        else shp_or_dbf.with_suffix(".dbf")
    )
    _add(ldid_to_encoding(ldid), f"ldid=0x{(ldid or 0):02X}")

    for hint in platform_locale_hints():
        _add(hint, "locale")

    if extra:
        for item in extra:
            _add(normalize_encoding_name(item) or item, "extra")

    for enc in _FALLBACK_POOL:
        _add(enc, "fallback")

    # Windows 上最后再试 mbcs（本机 ANSI 页），Linux 不可用
    if sys.platform == "win32":
        _add("mbcs", "win-mbcs")

    return ordered, sources


# ---------------------------------------------------------------------------
# 文本质量打分（在多种编码都能“解出来”时择优）
# ---------------------------------------------------------------------------


def score_decoded_text(samples: Iterable[str], *, encoding: str) -> float:
    """越高越好。惩罚替换符/控制符/乱码结构，奖励可打印与 CJK。"""
    texts = [t for t in samples if t]
    if not texts:
        return 0.0
    blob = "\n".join(texts)
    n = max(1, len(blob))
    score = 0.0

    repl = blob.count("\ufffd")
    score -= repl * 8.0

    ctrl = sum(1 for ch in blob if ord(ch) < 32 and ch not in "\t\n\r")
    score -= ctrl * 4.0

    # 私用区 / 特殊符号过多常为错误解码
    pua = sum(1 for ch in blob if 0xE000 <= ord(ch) <= 0xF8FF)
    score -= pua * 3.0

    cjk = len(_CJK_RE.findall(blob))
    score += cjk * 2.5

    printable = sum(1 for ch in blob if ch.isprintable() or ch in "\t\n\r")
    score += (printable / n) * 6.0

    # UTF-8 误用 GBK 时常出现大量拉丁扩展音标
    latin_ext = sum(1 for ch in blob if 0x00C0 <= ord(ch) <= 0x024F)
    if encoding.lower() in {"utf-8", "utf-8-sig"} and cjk == 0 and latin_ext > n * 0.15:
        score -= 5.0

    # GB* 解 UTF-8 中文时常大量怪字且 CJK 比例怪；若无明显 CJK 且高位多则扣分
    if encoding.lower() in {"gbk", "gb18030", "cp936"} and cjk == 0:
        high = sum(1 for ch in blob if ord(ch) > 127)
        if high > n * 0.3:
            score -= 4.0

    # 字段名不应过长乱码
    for t in texts[:20]:
        if len(t) > 40:
            score -= 1.0
        if t.isascii() and t.isidentifier():
            score += 0.3

    return score


def decode_dbf_bytes(
    raw: bytes, encodings: Iterable[str] | None = None
) -> tuple[str, str]:
    """解码任意 DBF 文本字节，返回 (text, encoding)。"""
    data = raw.rstrip(b"\x00 ")
    candidates = list(encodings) if encodings else []
    if not candidates:
        candidates, _ = build_encoding_candidates(Path("dummy.dbf"))
        # 无文件上下文时用池
        candidates = [e for e in _FALLBACK_POOL if codec_available(e)]

    best: tuple[float, str, str] | None = None
    for enc in candidates:
        if not codec_available(enc):
            continue
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        text = text.rstrip("\x00 ").strip()
        sc = score_decoded_text([text], encoding=enc)
        if best is None or sc > best[0]:
            best = (sc, text, enc)
    if best:
        return best[1], best[2]
    return data.decode("latin-1", errors="replace").rstrip(
        "\x00 "
    ).strip(), "latin-1+replace"


def normalize_dbf_str(value: Any, *, encodings: Iterable[str] | None = None) -> Any:
    """规范化 pyshp 读出的字段值（去填充、bytes 再解码）。"""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, bytes):
        text, _ = decode_dbf_bytes(value, encodings)
        return text
    if isinstance(value, str):
        return value.rstrip("\x00 ").strip()
    return value


# ---------------------------------------------------------------------------
# 打开 shapefile / 解析为 GeoJSON
# ---------------------------------------------------------------------------


def _sample_from_reader(
    reader: Any, *, max_records: int = 40
) -> tuple[list[str], list[str]]:
    fields = [str(f[0]).rstrip("\x00 ").strip() for f in reader.fields[1:]]
    values: list[str] = []
    shape_records = getattr(reader, "iterShapeRecords", None)
    it = shape_records() if callable(shape_records) else iter(reader.shapeRecords())
    for idx, sr in enumerate(it):
        if idx >= max_records:
            break
        for val in sr.record:
            if isinstance(val, str) and val.strip():
                values.append(val.rstrip("\x00 ").strip())
            elif isinstance(val, bytes) and val.strip(b"\x00 "):
                values.append(val.decode("latin-1", errors="replace"))
    return fields, values


def probe_shapefile_encoding(shp_path: Path) -> EncodingResolution:
    """探测 SHP/DBF 最佳编码（不返回 Reader，仅诊断/选定）。"""
    import shapefile  # type: ignore

    candidates, sources = build_encoding_candidates(shp_path)
    source_by_enc = {
        enc.lower(): sources[i] for i, enc in enumerate(candidates) if i < len(sources)
    }
    tried: list[str] = []
    best: EncodingProbeResult | None = None
    last_err: BaseException | None = None

    for enc in candidates:
        tried.append(enc)
        try:
            with shapefile.Reader(
                str(shp_path), encoding=enc, encodingErrors="strict"
            ) as reader:
                fields, values = _sample_from_reader(reader)
            score = score_decoded_text([*fields, *values], encoding=enc)
            # cpg / ldid 命中加分
            src = source_by_enc.get(enc.lower(), "")
            if src.startswith("cpg"):
                score += 3.0
            elif src.startswith("ldid"):
                score += 2.0
            elif src == "locale":
                score += 0.8
            probe = EncodingProbeResult(
                encoding=enc,
                score=score,
                strict=True,
                field_names=tuple(fields),
                sample_values=tuple(values[:12]),
                notes=(src,),
            )
            if best is None or probe.score > best.score:
                best = probe
            # 若 cpg 明确且分数可接受，可提前结束
            if (
                src.startswith("cpg")
                and score >= 4.0
                and "\ufffd" not in "".join(fields)
            ):
                break
        except Exception as exc:
            if is_encoding_error(exc):
                last_err = exc
                continue
            raise

    if best is not None:
        loc = ""
        try:
            loc = locale.getpreferredencoding(False) or ""
        except Exception:
            loc = ""
        return EncodingResolution(
            encoding=best.encoding,
            strict=True,
            score=best.score,
            sources=list(best.notes),
            candidates_tried=tried,
            locale=loc,
        )

    # strict 全失败 → replace 兜底择优
    for enc in candidates[:8]:
        tried.append(f"{enc}+replace")
        try:
            with shapefile.Reader(
                str(shp_path), encoding=enc, encodingErrors="replace"
            ) as reader:
                fields, values = _sample_from_reader(reader)
            score = score_decoded_text([*fields, *values], encoding=enc) - 2.0
            probe = EncodingProbeResult(
                encoding=enc,
                score=score,
                strict=False,
                field_names=tuple(fields),
                sample_values=tuple(values[:12]),
            )
            if best is None or probe.score > best.score:
                best = probe
        except Exception as exc:
            last_err = exc
            continue

    if best is None:
        detail = str(last_err)[:240] if last_err else "unknown"
        raise ValueError(
            "无法解析 SHP/DBF 字段编码（已尝试 utf-8 / gb18030 / gbk / big5 / cp125x 等，"
            "并考虑 .cpg 与 LDID）。请检查属性表编码或补充正确的 .cpg。"
            f" 明细: {detail}"
        )

    return EncodingResolution(
        encoding=best.encoding,
        strict=best.strict,
        score=best.score,
        sources=["replace-fallback"] if not best.strict else list(best.notes),
        candidates_tried=tried,
    )


def reader_to_geojson(
    reader: Any, *, encodings: Iterable[str] | None = None
) -> dict[str, Any]:
    fields = [str(f[0]).rstrip("\x00 ").strip() for f in reader.fields[1:]]
    features: list[dict[str, Any]] = []
    shape_records = getattr(reader, "iterShapeRecords", None)
    records = shape_records() if callable(shape_records) else reader.shapeRecords()
    for sr in records:
        geom = sr.shape.__geo_interface__
        props: dict[str, Any] = {}
        for key, val in zip(fields, sr.record, strict=False):
            if not key:
                continue
            props[key] = normalize_dbf_str(val, encodings=encodings)
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": features}


def shapefile_to_geojson(shp_path: Path) -> tuple[dict[str, Any], EncodingResolution]:
    """用最佳编码读取 shapefile → GeoJSON。"""
    import shapefile  # type: ignore

    path = Path(shp_path)
    resolution = probe_shapefile_encoding(path)
    errors = "strict" if resolution.strict else "replace"
    with shapefile.Reader(
        str(path), encoding=resolution.encoding, encodingErrors=errors
    ) as reader:
        geojson = reader_to_geojson(reader, encodings=resolution.candidates_tried)
    label = (
        resolution.encoding if resolution.strict else f"{resolution.encoding}+replace"
    )
    logger.info(
        "SHP encoding resolved: path=%s encoding=%s score=%.2f sources=%s platform=%s",
        path.name,
        label,
        resolution.score,
        resolution.sources,
        resolution.platform,
    )
    return geojson, EncodingResolution(
        encoding=label,
        strict=resolution.strict,
        score=resolution.score,
        sources=list(resolution.sources),
        candidates_tried=list(resolution.candidates_tried),
        platform=resolution.platform,
        locale=resolution.locale,
    )


def shapefile_to_geojson_with_fallback(
    shp_path: Path,
) -> tuple[dict[str, Any], EncodingResolution]:
    """对外入口：pyshp 多编码探测，失败再 geopandas；始终返回 EncodingResolution。"""
    last_err: BaseException | None = None
    try:
        return shapefile_to_geojson(shp_path)
    except ImportError:
        pass
    except ValueError as exc:
        last_err = exc
    except Exception:
        raise

    try:
        import json

        import geopandas as gpd  # type: ignore

        candidates, sources = build_encoding_candidates(shp_path)
        best_gj = None
        best_enc = None
        best_score = float("-inf")
        best_src = "geopandas"
        for enc, src in zip(candidates, sources, strict=False):
            try:
                gdf = gpd.read_file(shp_path, encoding=enc)
                gj = json.loads(gdf.to_json())
                samples: list[str] = []
                for feat in (gj.get("features") or [])[:30]:
                    props = feat.get("properties") or {}
                    samples.extend(str(k) for k in props)
                    samples.extend(str(v) for v in props.values() if v is not None)
                score = score_decoded_text(samples, encoding=enc)
                if src.startswith("cpg"):
                    score += 3.0
                if score > best_score:
                    best_score = score
                    best_gj = gj
                    best_enc = enc
                    best_src = f"geopandas:{src}"
            except Exception as exc:
                if is_encoding_error(exc):
                    last_err = exc
                    continue
                raise
        if best_gj is not None and best_enc is not None:
            loc = ""
            try:
                loc = locale.getpreferredencoding(False) or ""
            except Exception:
                loc = ""
            return best_gj, EncodingResolution(
                encoding=best_enc,
                strict=True,
                score=best_score,
                sources=[best_src],
                candidates_tried=list(candidates),
                locale=loc,
            )
        raise ValueError(
            "geopandas 无法按常见编码读取 SHP。"
            f" 明细: {str(last_err)[:200] if last_err else ''}"
        )
    except ImportError as exc:
        if last_err is not None:
            raise last_err from exc
        raise RuntimeError(
            "缺少 shapefile/geopandas 依赖，无法解析 SHP。请安装 pyshp 或 geopandas。"
        ) from exc


# ---------------------------------------------------------------------------
# 导出编码（Win / Linux 目标软件兼容）
# ---------------------------------------------------------------------------

# UI / API 可选导出编码（值 → Python codec）
EXPORT_ENCODING_CHOICES: dict[str, str] = {
    "auto": "auto",
    "utf-8": "utf-8",
    "utf-8-sig": "utf-8-sig",  # CSV + Excel
    "gbk": "gbk",
    "gb18030": "gb18030",
    "big5": "big5",
    "cp1252": "cp1252",
    "cp932": "cp932",
    "latin-1": "latin-1",
}

# 写入 .cpg 的人类可读标签（ArcGIS / QGIS 常用）
_CPG_LABELS: dict[str, str] = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8",
    "gbk": "GBK",
    "cp936": "GBK",
    "gb18030": "GB18030",
    "big5": "Big5",
    "cp950": "Big5",
    "cp1252": "1252",
    "cp932": "932",
    "shift_jis": "932",
    "latin-1": "8859-1",
    "iso8859-1": "8859-1",
}


def strip_encoding_modifiers(name: str | None) -> str | None:
    """``gbk+replace`` → ``gbk``。"""
    if not name:
        return None
    base = str(name).split("+", 1)[0].strip()
    return normalize_encoding_name(base) or (base if codec_available(base) else None)


def cpg_label_for_encoding(encoding: str) -> str:
    key = strip_encoding_modifiers(encoding) or "utf-8"
    return _CPG_LABELS.get(key.lower(), key.upper())


def resolve_export_encoding(
    requested: str | None,
    *,
    meta: dict[str, Any] | None = None,
    fmt: str = "geojson",
) -> str:
    """解析导出编码。

    - ``auto``：优先 meta.export_encoding_default / source_encoding；
      CSV 默认 utf-8-sig；SHP 默认 utf-8（并写 .cpg）；GeoJSON 固定 utf-8。
    """
    fmt_l = (fmt or "").lower()
    if fmt_l in {"geojson", "json"}:
        return "utf-8"

    req = (requested or "auto").strip().lower() or "auto"
    if req not in EXPORT_ENCODING_CHOICES and req != "auto":
        # 允许直接传 codec 名
        norm = normalize_encoding_name(req)
        if not norm or not codec_available(norm):
            raise ValueError(
                f"不支持的导出编码: {requested}。"
                f"可选: {', '.join(EXPORT_ENCODING_CHOICES)}"
            )
        req = norm

    if req == "auto":
        meta = meta or {}
        hinted = strip_encoding_modifiers(
            str(
                meta.get("export_encoding_default") or meta.get("source_encoding") or ""
            )
        )
        if hinted and codec_available(hinted):
            # CSV 在 Windows Excel 下 utf-8 建议带 BOM
            if fmt_l == "csv" and hinted == "utf-8":
                return "utf-8-sig"
            if hinted == "utf-8-sig" and fmt_l in {"shp", "shp-zip", "shapefile"}:
                return "utf-8"
            return hinted
        if fmt_l == "csv":
            return "utf-8-sig"
        return "utf-8"

    if req == "utf-8-sig" and fmt_l in {"shp", "shp-zip", "shapefile"}:
        return "utf-8"
    if not codec_available(req):
        raise ValueError(
            f"当前系统不支持编码 {req}（请在 Linux 确认已安装对应 locale/codec）"
        )
    return req


def truncate_to_encoded_bytes(text: str, encoding: str, max_bytes: int) -> str:
    """按目标编码字节长度截断（DBF 字段名 ≤10 字节）。"""
    if max_bytes <= 0:
        return ""
    raw = text or ""
    while raw and len(raw.encode(encoding, errors="ignore")) > max_bytes:
        raw = raw[:-1]
    if not raw:
        # 回退 ASCII 占位
        return "F"
    return raw


def encode_export_text(
    value: Any, encoding: str, *, max_bytes: int | None = None
) -> str:
    """将属性值转为可被目标编码写入的文本。"""
    if value is None:
        text = ""
    elif hasattr(value, "isoformat"):
        try:
            text = value.isoformat()
        except Exception:
            text = str(value)
    else:
        text = str(value)
    # 验证可编码；不可编码字符替换为 ?
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        text = text.encode(encoding, errors="replace").decode(
            encoding, errors="replace"
        )
    if max_bytes is not None:
        text = truncate_to_encoded_bytes(text, encoding, max_bytes)
    return text
