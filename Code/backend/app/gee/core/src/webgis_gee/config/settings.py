from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration shared by the module."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="WEBGIS_GEE_",
        extra="ignore",
    )

    app_name: str = "webgis-gee"
    environment: str = "dev"
    storage_backend: str = "local"
    local_storage_root: str = "./data"
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str | None = None
    minio_secure: bool = False
    temp_dir: str = "./tmp"
    max_parallel_exports: int = Field(default=2, ge=1)
    max_parallel_uploads: int = Field(default=4, ge=1)
    max_parallel_downloads: int = Field(default=4, ge=1)
    max_local_write_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    account_cooldown_seconds: int = Field(default=300, ge=0)
