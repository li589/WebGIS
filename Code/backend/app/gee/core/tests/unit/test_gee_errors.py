from webgis_gee.gee.errors import GeeErrorCategory, classify_gee_error


def test_classify_gee_error_detects_quota_failures() -> None:
    decision = classify_gee_error("quota exceeded for account")

    assert decision.category == GeeErrorCategory.QUOTA
    assert decision.should_cooldown_account is True


def test_classify_gee_error_detects_auth_failures() -> None:
    decision = classify_gee_error("authentication failed for service account")

    assert decision.category == GeeErrorCategory.AUTH
    assert decision.should_cooldown_account is True


def test_classify_gee_error_detects_transient_failures() -> None:
    decision = classify_gee_error("temporary backend error, try again later")

    assert decision.category == GeeErrorCategory.TRANSIENT
    assert decision.should_cooldown_account is False


def test_classify_gee_error_detects_user_input_failures() -> None:
    decision = classify_gee_error("missing image input for export")

    assert decision.category == GeeErrorCategory.USER_INPUT
    assert decision.should_cooldown_account is False
