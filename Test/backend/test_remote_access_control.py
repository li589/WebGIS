"""远程下载访问控制测试（Phase 4：访问模式语义对齐）。

覆盖：AccessPolicyContext 构建、site_compatible 放行、legacy 白名单
前缀匹配、未管控放行、RemoteAccessDeniedError、skip_check、
build_policy_context_from_uri。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def sample_grants():
    return [
        {
            "grant_id": "gldas-grant",
            "portal_id": "nasa_gldas",
            "dataset_key": "GLDAS_NOAH025_3H",
            "path_prefix": "data/GLDAS_NOAH025_3H\nGLDAS/data",
            "enabled": True,
        },
        {
            "grant_id": "smap-grant",
            "portal_id": "nsidc_data",
            "dataset_key": "SPL3SMP_E",
            "path_prefix": "SPL3SMP_E",
            "enabled": True,
        },
        {
            "grant_id": "disabled-grant",
            "portal_id": "nasa_gldas",
            "dataset_key": "DISABLED_DATASET",
            "path_prefix": "disabled/",
            "enabled": False,
        },
    ]


class TestCheckRemoteAccess:
    def test_skip_check(self):
        from shared.remote_sources.access_control import (
            AccessPolicyContext,
            check_remote_access,
        )

        ctx = AccessPolicyContext(skip_check=True)
        check_remote_access("sftp://host/data", ctx)

    def test_no_source_entry_passes(self):
        from shared.remote_sources.access_control import (
            AccessPolicyContext,
            check_remote_access,
        )

        ctx = AccessPolicyContext(source_entry=None)
        check_remote_access("sftp://host/data", ctx)

    def test_site_compatible_passes(self):
        from shared.remote_sources.access_control import (
            AccessPolicyContext,
            check_remote_access,
        )

        ctx = AccessPolicyContext(
            source_entry={"remote_source_id": "x", "access_mode": "site_compatible"},
            grants=[],
        )
        check_remote_access("sftp://host/anything", ctx)

    def test_legacy_no_grants_passes(self):
        from shared.remote_sources.access_control import (
            AccessPolicyContext,
            check_remote_access,
        )

        ctx = AccessPolicyContext(
            source_entry={"remote_source_id": "x", "access_mode": "legacy"},
            grants=[],
        )
        check_remote_access("sftp://host/data", ctx)

    def test_legacy_grant_prefix_match(self, sample_grants):
        from shared.remote_sources.access_control import (
            AccessPolicyContext,
            check_remote_access,
        )

        ctx = AccessPolicyContext(
            source_entry={"remote_source_id": "gldas", "access_mode": "legacy"},
            grants=sample_grants,
        )
        check_remote_access("sftp://host/data/GLDAS_NOAH025_3H/file.nc", ctx)

    def test_legacy_grant_s3_prefix_match(self, sample_grants):
        """测试多行 path_prefix 中第二行前缀匹配（用 sftp 替代不支持的 s3 scheme）。"""
        from shared.remote_sources.access_control import (
            AccessPolicyContext,
            check_remote_access,
        )

        ctx = AccessPolicyContext(
            source_entry={"remote_source_id": "gldas", "access_mode": "legacy"},
            grants=sample_grants,
        )
        # 使用 sftp scheme（合法），路径命中第二行 prefix
        check_remote_access("sftp://nasa-gldas/GLDAS/data/file.nc", ctx)

    def test_legacy_no_match_raises(self, sample_grants):
        from shared.remote_sources.access_control import (
            AccessPolicyContext,
            RemoteAccessDeniedError,
            check_remote_access,
        )

        ctx = AccessPolicyContext(
            source_entry={"remote_source_id": "gldas", "access_mode": "legacy"},
            grants=sample_grants,
        )
        with pytest.raises(RemoteAccessDeniedError, match="no dataset grant matches"):
            check_remote_access("sftp://host/random/path.nc", ctx)

    def test_disabled_grant_ignored(self, sample_grants):
        from shared.remote_sources.access_control import (
            AccessPolicyContext,
            RemoteAccessDeniedError,
            check_remote_access,
        )

        ctx = AccessPolicyContext(
            source_entry={"remote_source_id": "gldas", "access_mode": "legacy"},
            grants=sample_grants,  # disabled-grant 有 prefix=disabled/ 但 enabled=False
        )
        with pytest.raises(RemoteAccessDeniedError):
            check_remote_access("sftp://host/disabled/file.nc", ctx)


class TestBuildPolicyContextFromUri:
    def test_no_cred_profile_skips(self):
        from shared.remote_sources.access_control import build_policy_context_from_uri

        ctx = build_policy_context_from_uri("sftp://host/data/file.nc")
        assert ctx.skip_check is True

    def test_with_profile_builds_context(self):
        from shared.remote_sources.access_control import build_policy_context_from_uri

        class FakeRegistry:
            def list_entries(self):
                return [
                    {"ref_id": "profile1", "access_mode": "site_compatible"},
                    {"ref_id": "profile2", "access_mode": "legacy"},
                ]

        ctx = build_policy_context_from_uri(
            "sftp://host/data/file.nc?cred=profile2",
            source_registry=FakeRegistry(),
        )
        assert ctx.source_entry["ref_id"] == "profile2"
        assert ctx.source_entry["access_mode"] == "legacy"
