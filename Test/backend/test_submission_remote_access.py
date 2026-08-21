"""提交期远程数据集访问预校验测试（#56）。

覆盖：_validate_remote_dataset_access 的三态语义
（明确拒绝 fail-closed / 基础设施异常 fail-open / 非 REMOTE_SCHEMES 确定性跳过）、
URIs 提取、router 的 403 + C403001 映射。
"""

from __future__ import annotations

import pytest

from shared.contracts.api_contracts import WorkflowSubmitRequest
from shared.remote_sources.access_control import RemoteAccessDeniedError


def _make_payload(uris: list[str] | None = None) -> WorkflowSubmitRequest:
    """构造带 data_access_requests 的最小提交 payload。"""
    algorithm_request: dict = {}
    if uris is not None:
        algorithm_request = {
            "datasource_selection": {
                "_data_access_requests": {
                    "GLDAS_NOAH025_3H": {"selector": {"uris": uris}}
                }
            }
        }
    return WorkflowSubmitRequest(
        command_type="analysis",
        command_label="test",
        layer_id=None,
        algorithm_request=algorithm_request,
    )


class _FakeSourceRegistry:
    """按 ref_id 匹配 remote_source 条目的假 registry。"""

    def __init__(self, entries: list[dict]):
        self._entries = entries

    def list_entries(self) -> list[dict]:
        return self._entries


class _FakeGrantsRegistry:
    def __init__(self, entries: list[dict]):
        self._entries = entries

    def list_entries(self) -> list[dict]:
        return self._entries


@pytest.fixture()
def svc():
    from app.services.workflow.service_container import submission_service

    return submission_service


@pytest.fixture()
def legacy_source():
    """legacy 模式 storage_profile 源（ref_id=gldas-nas）。"""
    return [
        {
            "remote_source_id": "gldas-remote",
            "kind": "storage_profile",
            "ref_id": "gldas-nas",
            "remote_path": "GLDAS/data",
            "access_mode": "legacy",
        }
    ]


@pytest.fixture()
def gldas_grants():
    return [
        {
            "grant_id": "gldas-grant",
            "portal_id": "nasa_gldas",
            "dataset_key": "GLDAS_NOAH025_3H",
            "path_prefix": "GLDAS/data",
            "enabled": True,
        }
    ]


def _patch_registries(monkeypatch, sources, grants):
    import app.services.remote_source_registry as src_mod
    import app.services.remote_dataset_grants as grants_mod

    monkeypatch.setattr(
        src_mod, "get_remote_source_registry", lambda: _FakeSourceRegistry(sources)
    )
    monkeypatch.setattr(
        grants_mod, "get_remote_dataset_grants", lambda: _FakeGrantsRegistry(grants)
    )


class TestValidateRemoteDatasetAccess:
    def test_legacy_granted_prefix_passes(self, svc, monkeypatch, legacy_source, gldas_grants):
        """legacy 源 + 授权前缀匹配 URI → 放行。"""
        _patch_registries(monkeypatch, legacy_source, gldas_grants)
        payload = _make_payload(["sftp://host/GLDAS/data/file.nc?cred=gldas-nas"])
        svc._validate_remote_dataset_access(payload)  # 不抛 = 通过

    def test_legacy_unauthorized_path_denied(
        self, svc, monkeypatch, legacy_source, gldas_grants
    ):
        """legacy 源 + 未授权路径 → RemoteAccessDeniedError（fail-closed，附 dataset）。"""
        _patch_registries(monkeypatch, legacy_source, gldas_grants)
        payload = _make_payload(["sftp://host/SECRET/other.nc?cred=gldas-nas"])
        with pytest.raises(RemoteAccessDeniedError) as exc_info:
            svc._validate_remote_dataset_access(payload)
        assert "GLDAS_NOAH025_3H" in exc_info.value.reason

    def test_site_compatible_source_passes(self, svc, monkeypatch, gldas_grants):
        """site_compatible 源任意路径 → 放行。"""
        source = [
            {
                "remote_source_id": "open-remote",
                "kind": "storage_profile",
                "ref_id": "open-nas",
                "remote_path": "",
                "access_mode": "site_compatible",
            }
        ]
        _patch_registries(monkeypatch, source, gldas_grants)
        payload = _make_payload(["sftp://host/ANY/path.nc?cred=open-nas"])
        svc._validate_remote_dataset_access(payload)

    def test_http_uri_skipped_deterministically(self, svc, monkeypatch):
        """http:// 直链 → 确定性跳过（registry 即使不可用也不影响）。"""
        import app.services.remote_source_registry as src_mod

        def _boom():
            raise RuntimeError("registry unavailable")

        monkeypatch.setattr(src_mod, "get_remote_source_registry", _boom)
        payload = _make_payload(["https://example.com/data.nc"])
        svc._validate_remote_dataset_access(payload)  # 不抛 = 跳过

    def test_registry_unavailable_fail_open(self, svc, monkeypatch, legacy_source):
        """registry 基础设施异常 → fail-open 放行。"""
        import app.services.remote_source_registry as src_mod
        import app.services.remote_dataset_grants as grants_mod

        def _boom():
            raise RuntimeError("db locked")

        monkeypatch.setattr(src_mod, "get_remote_source_registry", _boom)
        monkeypatch.setattr(grants_mod, "get_remote_dataset_grants", _boom)
        payload = _make_payload(["sftp://host/SECRET/other.nc?cred=gldas-nas"])
        svc._validate_remote_dataset_access(payload)  # 降级放行

    def test_empty_requests_pass(self, svc, monkeypatch, legacy_source, gldas_grants):
        """空 data_access_requests → 直接通过。"""
        _patch_registries(monkeypatch, legacy_source, gldas_grants)
        payload = _make_payload(None)
        svc._validate_remote_dataset_access(payload)


class TestRouterMapping:
    def test_workflow_router_maps_denied_to_403(self, monkeypatch):
        """workflow_router：RemoteAccessDeniedError → 403 + C403001。"""
        from app.api.error_codes import AUTH_ERROR
        from app.api.routers.workflow_router import submit_workflow as router_submit
        from app.services.workflow.service_container import submission_service
        from fastapi import HTTPException

        def _deny(payload, **kwargs):
            raise RemoteAccessDeniedError(
                "sftp://host/SECRET/x.nc", "dataset 'DS' not in authorized grants"
            )

        monkeypatch.setattr(submission_service, "submit_workflow", _deny)
        payload = _make_payload(["sftp://host/SECRET/x.nc?cred=gldas-nas"])
        with pytest.raises(HTTPException) as exc_info:
            router_submit(payload)
        assert exc_info.value.status_code == 403
        assert getattr(exc_info.value, "error_code", None) == AUTH_ERROR.code
        assert "远程数据集访问被拒绝" in str(exc_info.value.detail)

    def test_analysis_router_maps_denied_to_403(self, monkeypatch):
        """analysis_router：RemoteAccessDeniedError → 403 + C403001。"""
        from app.api.error_codes import AUTH_ERROR
        from app.api.routers.analysis_router import create_analysis_run
        import app.services.analysis_run_service as run_svc
        from fastapi import HTTPException
        from shared.contracts.api_contracts import AnalysisRunRequest

        def _deny(payload, **kwargs):
            raise RemoteAccessDeniedError(
                "sftp://host/SECRET/x.nc", "dataset 'DS' not in authorized grants"
            )

        import importlib

        router_module = importlib.import_module(
            "app.api.routers.analysis_router"
        )
        monkeypatch.setattr(router_module, "submit_analysis_run", _deny)
        payload = AnalysisRunRequest(
            tool_id="omega_tool",
            layer_id="method-smap-omega-doy-dynamic",
        )
        with pytest.raises(HTTPException) as exc_info:
            create_analysis_run(payload)
        assert exc_info.value.status_code == 403
        assert getattr(exc_info.value, "error_code", None) == AUTH_ERROR.code
