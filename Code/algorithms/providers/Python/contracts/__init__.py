"""Shared contracts for runtime, data, and products.

接入方可通过以下模块完成 HTTP/JSON 适配：
- contracts.serialization:  coerce_job_request() + get_job_request_json_schema()
- contracts.api_errors:     build_api_error_response() 将异常转为标准 HTTP 响应
- contracts.validation_feedback: build_validation_feedback() 获取字段级错误清单
"""

from .data import DataBundle, DataRequest
from .event import LogEvent
from .job import JobRequest, JobResult
from .product import OutputSpec, ProductManifest, ProductRef
from .runtime import CachePolicy, RegionSpec, ResourceHint, RuntimeContext, TimeRange
from .serialization import (
    JobRequestDecodeError,
    coerce_job_request,
    get_job_request_json_schema,
    job_request_from_mapping,
)
from .validation import (
    JobRequestValidationError,
    validate_job_request,
)

# api_errors / validation_feedback 放在最后：它们依赖 workflow.serialization，
# 而 workflow.serialization 在 runner 包初始化完成后才能安全导入。
from .api_errors import ApiErrorResponse, ApiSuggestedFix, build_api_error_response
from .validation_feedback import ValidationIssue, build_validation_feedback

__all__ = [
    "ApiErrorResponse",
    "ApiSuggestedFix",
    "build_api_error_response",
    "build_validation_feedback",
    "CachePolicy",
    "coerce_job_request",
    "DataBundle",
    "DataRequest",
    "get_job_request_json_schema",
    "job_request_from_mapping",
    "JobRequest",
    "JobRequestDecodeError",
    "JobRequestValidationError",
    "JobResult",
    "LogEvent",
    "OutputSpec",
    "ProductManifest",
    "ProductRef",
    "RegionSpec",
    "ResourceHint",
    "RuntimeContext",
    "TimeRange",
    "validate_job_request",
    "ValidationIssue",
]
