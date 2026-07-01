$ErrorActionPreference = "Stop"

$LocalConfig = Join-Path $PSScriptRoot "dev.env.ps1"
$PythonHome = Join-Path (Split-Path -Parent $PSScriptRoot) "Python312"
$ActivateScript = Join-Path $PythonHome "activate-project-venv.ps1"
$InstallDepsScript = Join-Path $PythonHome "install-backend-deps.ps1"
$CommonScript = Join-Path (Split-Path -Parent $PSScriptRoot) "common\project-paths.ps1"

if (-not (Test-Path $CommonScript)) {
    throw "Project path resolver not found: $CommonScript"
}

. $CommonScript

if (Test-Path $LocalConfig) {
    . $LocalConfig
}

. $InstallDepsScript
. $ActivateScript

Push-Location $BackendDir

try {
    if ([string]::IsNullOrWhiteSpace($env:BACKEND_MINIO_ENDPOINT)) {
        throw "Set BACKEND_MINIO_ENDPOINT before running minio-check.ps1"
    }
    if ([string]::IsNullOrWhiteSpace($env:BACKEND_MINIO_ACCESS_KEY) -or [string]::IsNullOrWhiteSpace($env:BACKEND_MINIO_SECRET_KEY)) {
        throw "Set BACKEND_MINIO_ACCESS_KEY and BACKEND_MINIO_SECRET_KEY before running minio-check.ps1"
    }
    if ([string]::IsNullOrWhiteSpace($env:BACKEND_MINIO_BUCKET)) {
        $env:BACKEND_MINIO_BUCKET = "workflow-artifacts"
    }

    @'
from minio import Minio
import os

endpoint = os.environ["BACKEND_MINIO_ENDPOINT"]
access_key = os.environ["BACKEND_MINIO_ACCESS_KEY"]
secret_key = os.environ["BACKEND_MINIO_SECRET_KEY"]
bucket = os.environ["BACKEND_MINIO_BUCKET"]
secure = os.environ.get("BACKEND_MINIO_SECURE", "false").lower() == "true"

client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
bucket_exists = client.bucket_exists(bucket)
if not bucket_exists:
    client.make_bucket(bucket)

objects = list(client.list_objects(bucket, recursive=True))
print({
    "endpoint": endpoint,
    "bucket": bucket,
    "bucket_exists": True,
    "object_count": len(objects),
})
'@ | python -

    if ($LASTEXITCODE -ne 0) {
        throw "MinIO connectivity check failed."
    }
}
finally {
    Pop-Location
}
