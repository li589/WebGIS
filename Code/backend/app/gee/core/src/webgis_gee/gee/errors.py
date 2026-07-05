from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GeeErrorCategory(str, Enum):
    AUTH = "auth"
    QUOTA = "quota"
    TRANSIENT = "transient"
    USER_INPUT = "user_input"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GeeErrorDecision:
    category: GeeErrorCategory
    should_cooldown_account: bool
    reason: str
    matched_text: str | None = None


def classify_gee_error(*messages: str) -> GeeErrorDecision:
    normalized_messages = [message.strip() for message in messages if message and message.strip()]
    if not normalized_messages:
        return GeeErrorDecision(
            category=GeeErrorCategory.UNKNOWN,
            should_cooldown_account=False,
            reason="workflow execution failed",
        )

    for message in normalized_messages:
        lowered = message.lower()
        decision = _classify_single_message(message=message, lowered=lowered)
        if decision is not None:
            return decision

    return GeeErrorDecision(
        category=GeeErrorCategory.UNKNOWN,
        should_cooldown_account=False,
        reason=normalized_messages[0],
    )


def _classify_single_message(message: str, lowered: str) -> GeeErrorDecision | None:
    auth_keywords = (
        "auth",
        "authentication",
        "credential",
        "credentials",
        "permission",
        "forbidden",
        "unauthorized",
        "service account",
        "account disabled",
        "invalid grant",
        "initialize",
        "initialization failed",
    )
    quota_keywords = (
        "quota",
        "rate limit",
        "too many requests",
        "limit exceeded",
        "exceeded",
        "user memory limit",
        "memory capacity exceeded",
        "resource exhausted",
    )
    transient_keywords = (
        "timeout",
        "timed out",
        "deadline exceeded",
        "temporarily unavailable",
        "internal error",
        "connection reset",
        "connection aborted",
        "try again",
        "transient",
        "backend error",
    )
    user_input_keywords = (
        "missing ",
        "unsupported ",
        "invalid ",
        "unknown ",
        "path escapes",
        "workflow graph must be a dag",
        "requires bucket",
        "requires asset_id",
    )

    if any(keyword in lowered for keyword in auth_keywords):
        return GeeErrorDecision(
            category=GeeErrorCategory.AUTH,
            should_cooldown_account=True,
            reason=message,
            matched_text=message,
        )
    if any(keyword in lowered for keyword in quota_keywords):
        return GeeErrorDecision(
            category=GeeErrorCategory.QUOTA,
            should_cooldown_account=True,
            reason=message,
            matched_text=message,
        )
    if any(keyword in lowered for keyword in transient_keywords):
        return GeeErrorDecision(
            category=GeeErrorCategory.TRANSIENT,
            should_cooldown_account=False,
            reason=message,
            matched_text=message,
        )
    if any(keyword in lowered for keyword in user_input_keywords):
        return GeeErrorDecision(
            category=GeeErrorCategory.USER_INPUT,
            should_cooldown_account=False,
            reason=message,
            matched_text=message,
        )
    return None
