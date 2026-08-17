"""统一业务错误码（对齐架构交付包《系统设计》BD-03 / 错误码表）。

契约口径（与 G6 交付包一致）：
- ``C403001`` — 鉴权/授权失败语义域：未鉴权写（fail-closed）、无权限、越权（IDOR）。
- ``C429001`` — 触发限流（写接口 120 次/分钟/IP 等），响应携带 ``Retry-After``。

设计决策：HTTP 状态码保持标准语义（401=未鉴权 / 403=无权限 / 429=限流），
``error_code`` 为业务标识，二者解耦。架构文档错误码表中的「403」列为语义域
（鉴权类 4xx 统一归属 C403001），由本模块注释 + 交付包实施回执对齐。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class ErrorCodeSpec:
    """业务错误码规格。"""

    code: str
    default_message: str


C403001 = ErrorCodeSpec("C403001", "无权访问或写接口未鉴权被拒绝")
C429001 = ErrorCodeSpec("C429001", "操作太频繁，请稍后再重试")

#: 鉴权/授权失败语义域统一归属 C403001 的便捷引用（401 未鉴权 / 403 无权限）。
AUTH_ERROR = C403001

#: 状态冲突语义域：乐观并发冲突（如工作区快照 409）、请求体超限（413）。
C409001 = ErrorCodeSpec("C409001", "状态冲突或请求体超限，请刷新后重试")
CONFLICT_ERROR = C409001


class ApiError(HTTPException):
    """带业务错误码的 HTTP 异常；响应体将包含 ``error_code`` 字段。

    Args:
        spec: 错误码规格（``C403001`` / ``C429001`` 等）。
        status_code: HTTP 状态码（保持标准语义，与 error_code 解耦）。
        detail: 人类可读错误信息；缺省用规格默认文案。
        headers: 附加响应头（如限流的 ``Retry-After``）。
    """

    def __init__(
        self,
        spec: ErrorCodeSpec,
        *,
        status_code: int,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail=detail or spec.default_message,
            headers=headers,
        )
        self.error_code = spec.code
