from enum import Enum


class AccountState(str, Enum):
    AVAILABLE = "available"
    LEASED = "leased"
    COOLDOWN = "cooldown"
    DISABLED = "disabled"
    EXHAUSTED = "exhausted"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PortKind(str, Enum):
    GEOMETRY = "geometry"
    FEATURE_COLLECTION = "feature_collection"
    IMAGE = "image"
    IMAGE_COLLECTION = "image_collection"
    TABLE = "table"
    ARTIFACT = "artifact"
    VALUE = "value"
    DIAGNOSTIC = "diagnostic"
