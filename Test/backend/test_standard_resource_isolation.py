from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_owner_scoped_layer_ids_preserve_legacy_ids() -> None:
    from app.data_io.services.paths import owner_scoped_layer_id

    assert owner_scoped_layer_id("imported-demo-00", None) == "imported-demo-00"
    assert owner_scoped_layer_id("imported-demo-00", 12) == "imported-demo-00-u12"
    assert owner_scoped_layer_id("imported-demo-00-u12", 12) == "imported-demo-00-u12"


def test_overwrite_guard_rejects_another_users_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.data_io.services import raster_register

    imports_root = tmp_path / "imports"
    existing = imports_root / "imported-shared"
    existing.mkdir(parents=True)
    (existing / "meta.json").write_text(
        json.dumps({"owner_user_id": 1}), encoding="utf-8"
    )
    marker = existing / "keep.txt"
    marker.write_text("original", encoding="utf-8")
    source = tmp_path / "new.tif"
    source.write_bytes(b"not-needed-before-owner-check")

    monkeypatch.setattr(raster_register, "ensure_imports_root", lambda: None)
    monkeypatch.setattr(
        raster_register,
        "safe_import_child",
        lambda layer_id: imports_root / layer_id,
    )

    with pytest.raises(ValueError, match="拒绝覆盖"):
        raster_register.register_geotiff_as_imported(
            source,
            layer_id="imported-shared",
            replace_existing=True,
            extra_meta={"owner_user_id": 2},
        )

    assert marker.read_text(encoding="utf-8") == "original"


def test_mutation_access_requires_owner_or_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.deps import check_resource_mutation_access
    from app.api.error_codes import ApiError
    from app.services import overlay_registry
    from app.services.credential_resolver import CredentialContext

    monkeypatch.setattr(
        overlay_registry,
        "is_overlay_owner",
        lambda _layer_id, user_id: user_id == 7,
    )
    owner = CredentialContext(source="session", role="standard", user_id=7)
    peer = CredentialContext(source="session", role="standard", user_id=8)
    admin = CredentialContext(source="session", role="admin", user_id=1)

    check_resource_mutation_access(owner, "layer", "imported-demo")
    check_resource_mutation_access(admin, "layer", "imported-demo")
    with pytest.raises(ApiError) as exc_info:
        check_resource_mutation_access(peer, "layer", "imported-demo")
    assert exc_info.value.status_code == 403
