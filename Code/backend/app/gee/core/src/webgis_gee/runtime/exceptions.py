class WebGISError(Exception):
    """Base exception for the module."""


class WorkflowValidationError(WebGISError):
    """Raised when a workflow definition is invalid."""


class NodeExecutionError(WebGISError):
    """Raised when a node execution fails."""


class AccountUnavailableError(WebGISError):
    """Raised when no GEE account can be leased."""


class StorageOperationError(WebGISError):
    """Raised when artifact storage operations fail."""


class ResourceExhaustedError(WebGISError):
    """Raised when in-process resource limits are exceeded."""
