"""Agent web_search — DuckDuckGo Instant Answer + Wikipedia fallback (SSRF-safe)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode

logger = logging.getLogger(__name__)

_DDG_URL = "https://api.duckduckgo.com/"
_WIKI_OPENSEARCH = "https://zh.wikipedia.org/w/api.php"
_WIKI_SUMMARY = "https://zh.wikipedia.org/api/rest_v1/page/summary/{title}"
_UA = "CGDA-Agent/1.0 (research map assistant; +https://localhost)"


def web_search_enabled() -> bool:
    raw = os.getenv("BACKEND_AGENT_WEB_SEARCH_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def run_web_search(query: str, *, limit: int = 5) -> dict[str, Any]:
    """Public web search for agent (read-only). Returns ok + results/error."""
    if not web_search_enabled():
        return {
            "ok": False,
            "error": "在线搜索已关闭（BACKEND_AGENT_WEB_SEARCH_ENABLED）",
        }
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query 不能为空"}
    if len(q) > 200:
        q = q[:200]
    limit = max(1, min(8, int(limit)))

    results: list[dict[str, str]] = []
    sources: list[str] = []
    try:
        ddg = _duckduckgo_instant(q, limit=limit)
        results.extend(ddg)
        if ddg:
            sources.append("duckduckgo")
    except Exception as exc:
        logger.warning("web_search DDG failed: %s", exc)

    if len(results) < limit:
        try:
            wiki = _wikipedia_hits(q, limit=limit - len(results))
            results.extend(wiki)
            if wiki:
                sources.append("wikipedia")
        except Exception as exc:
            logger.warning("web_search Wikipedia failed: %s", exc)

    # de-dupe by URL/title
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in results:
        key = (item.get("url") or item.get("title") or "").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break

    if not unique:
        return {
            "ok": True,
            "query": q,
            "count": 0,
            "results": [],
            "sources": sources,
            "note": "未找到摘要结果；可换关键词或改用图层/工作流工具查询平台内数据。",
        }
    return {
        "ok": True,
        "query": q,
        "count": len(unique),
        "results": unique,
        "sources": sources,
    }


def _fetch_json(url: str, *, timeout: float = 8.0) -> Any:
    from app.core.ssrf import safe_urlopen

    with safe_urlopen(
        url,
        timeout=timeout,
        headers={"User-Agent": _UA, "Accept": "application/json"},
        allow_private=False,
        allow_loopback=False,
    ) as resp:
        raw = resp.read(512_000)
    return json.loads(raw.decode("utf-8", errors="replace"))


def _duckduckgo_instant(query: str, *, limit: int) -> list[dict[str, str]]:
    params = urlencode(
        {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
    )
    data = _fetch_json(f"{_DDG_URL}?{params}")
    if not isinstance(data, dict):
        return []
    out: list[dict[str, str]] = []
    abstract = str(data.get("AbstractText") or "").strip()
    abs_url = str(data.get("AbstractURL") or "").strip()
    heading = str(data.get("Heading") or query).strip()
    if abstract:
        out.append(
            {
                "title": heading[:200],
                "snippet": abstract[:600],
                "url": abs_url[:500],
            }
        )
    related = data.get("RelatedTopics")
    if isinstance(related, list):
        for item in related:
            if len(out) >= limit:
                break
            if not isinstance(item, dict):
                continue
            # Nested Topics groups
            if isinstance(item.get("Topics"), list):
                for sub in item["Topics"]:
                    if len(out) >= limit:
                        break
                    hit = _ddg_topic_item(sub)
                    if hit:
                        out.append(hit)
                continue
            hit = _ddg_topic_item(item)
            if hit:
                out.append(hit)
    return out[:limit]


def _ddg_topic_item(item: object) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    text = str(item.get("Text") or "").strip()
    url = str(item.get("FirstURL") or "").strip()
    if not text:
        return None
    title = text.split(" - ", 1)[0][:200]
    return {"title": title, "snippet": text[:600], "url": url[:500]}


_SAFE_TITLE = re.compile(r"^[\w\u4e00-\u9fff\s\-_.()（）]+$", re.UNICODE)


def _wikipedia_hits(query: str, *, limit: int) -> list[dict[str, str]]:
    if limit <= 0:
        return []
    params = urlencode(
        {
            "action": "opensearch",
            "search": query,
            "limit": str(limit),
            "namespace": "0",
            "format": "json",
        }
    )
    data = _fetch_json(f"{_WIKI_OPENSEARCH}?{params}")
    if not isinstance(data, list) or len(data) < 4:
        return []
    titles = data[1] if isinstance(data[1], list) else []
    descs = data[2] if isinstance(data[2], list) else []
    urls = data[3] if isinstance(data[3], list) else []
    out: list[dict[str, str]] = []
    for i, title in enumerate(titles[:limit]):
        t = str(title).strip()
        if not t:
            continue
        snippet = str(descs[i]).strip() if i < len(descs) else ""
        url = str(urls[i]).strip() if i < len(urls) else ""
        if not snippet and _SAFE_TITLE.match(t):
            snippet = _wiki_summary_extract(t) or ""
        out.append(
            {
                "title": t[:200],
                "snippet": (snippet or t)[:600],
                "url": url[:500],
            }
        )
    return out


def _wiki_summary_extract(title: str) -> str | None:
    try:
        url = _WIKI_SUMMARY.format(title=quote(title.replace(" ", "_"), safe=""))
        data = _fetch_json(url, timeout=5.0)
        if isinstance(data, dict):
            extract = str(data.get("extract") or "").strip()
            return extract[:600] or None
    except (HTTPError, URLError, OSError, ValueError, TypeError):
        return None
    return None
