"""Token usage helpers (API usage preferred; char-based estimate fallback)."""

from __future__ import annotations

from typing import Any


def estimate_tokens(text: str) -> int:
    """Rough token estimate without tiktoken dependency (~4 chars / token)."""
    if not text:
        return 0
    # Mix of CJK (≈1 token/char) and Latin (≈4 chars/token)
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - cjk
    return max(1, cjk + (other + 3) // 4)


def usage_from_openai(
    data: dict[str, Any], *, prompt_fallback: str, completion_fallback: str
) -> dict[str, Any]:
    usage = data.get("usage")
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )
        total = int(usage.get("total_tokens") or (prompt + completion))
        if prompt or completion:
            return {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total or (prompt + completion),
                "estimated": False,
            }
    p = estimate_tokens(prompt_fallback)
    c = estimate_tokens(completion_fallback)
    return {
        "prompt_tokens": p,
        "completion_tokens": c,
        "total_tokens": p + c,
        "estimated": True,
    }


def usage_from_anthropic(
    data: dict[str, Any], *, prompt_fallback: str, completion_fallback: str
) -> dict[str, Any]:
    usage = data.get("usage")
    if isinstance(usage, dict):
        prompt = int(usage.get("input_tokens") or 0)
        completion = int(usage.get("output_tokens") or 0)
        if prompt or completion:
            return {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
                "estimated": False,
            }
    return usage_from_openai(
        {}, prompt_fallback=prompt_fallback, completion_fallback=completion_fallback
    )
