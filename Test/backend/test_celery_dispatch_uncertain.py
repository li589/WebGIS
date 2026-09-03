"""Celery 派发失败分类：is_celery_dispatch_uncertain。"""

from __future__ import annotations

import concurrent.futures

import pytest

from app.services.workflow.celery_dispatch import is_celery_dispatch_uncertain


def test_timeout_is_uncertain() -> None:
    assert is_celery_dispatch_uncertain(TimeoutError("slow")) is True
    assert (
        is_celery_dispatch_uncertain(
            concurrent.futures.TimeoutError("apply_async > 8s")
        )
        is True
    )
    assert (
        is_celery_dispatch_uncertain(
            RuntimeError("Celery broker timeout while dispatching workflow (apply_async > 8s)")
        )
        is True
    )


def test_connection_refused_is_certain_undelivered() -> None:
    assert (
        is_celery_dispatch_uncertain(
            ConnectionRefusedError(10061, "由于目标计算机积极拒绝，无法连接。")
        )
        is False
    )
    assert (
        is_celery_dispatch_uncertain(
            OSError(111, "Connection refused")
        )
        is False
    )
    assert (
        is_celery_dispatch_uncertain(
            Exception("redis.exceptions.ConnectionError: Error 10061 connecting to 127.0.0.1:6379")
        )
        is False
    )
    assert (
        is_celery_dispatch_uncertain(
            Exception("kombu.exceptions.OperationalError: Error 10061 connecting to 127.0.0.1:6379. 积极拒绝")
        )
        is False
    )


def test_unknown_error_defaults_uncertain() -> None:
    assert is_celery_dispatch_uncertain(RuntimeError("something odd")) is True


def test_connection_reset_uncertain() -> None:
    exc = ConnectionError("Connection reset by peer")
    assert is_celery_dispatch_uncertain(exc) is True
