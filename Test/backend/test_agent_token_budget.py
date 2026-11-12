"""游客 Agent token 额度：预占、失败释放和幂等结算。"""

from app.api import rate_limit as rl


def _reset_token_state():
    with rl._guest_quota_memory_lock:
        rl._guest_token_usage.clear()
        rl._guest_token_reservations.clear()
        rl._guest_token_settled.clear()


def setup_function():
    _reset_token_state()


def teardown_function():
    _reset_token_state()


def test_reservation_is_visible_and_success_charges_actual_usage():
    reservation = rl.reserve_guest_agent_tokens("visitor-a", "203.0.113.10", 12000)
    assert reservation is not None
    used, limit = rl.peek_guest_agent_tokens("visitor-a", "203.0.113.10")
    assert used == 12000 and limit >= 12000
    rl.settle_guest_agent_tokens(reservation, 3210)
    used, _ = rl.peek_guest_agent_tokens("visitor-a", "203.0.113.10")
    assert used == 3210


def test_failed_request_releases_without_charging():
    reservation = rl.reserve_guest_agent_tokens("visitor-b", "203.0.113.11", 12000)
    assert reservation is not None
    rl.settle_guest_agent_tokens(reservation, None)
    assert rl.peek_guest_agent_tokens("visitor-b", "203.0.113.11")[0] == 0


def test_duplicate_settlement_is_idempotent():
    reservation = rl.reserve_guest_agent_tokens("visitor-c", "203.0.113.12", 12000)
    assert reservation is not None
    rl.settle_guest_agent_tokens(reservation, 4000)
    rl.settle_guest_agent_tokens(reservation, 4000)
    assert rl.peek_guest_agent_tokens("visitor-c", "203.0.113.12")[0] == 4000


def test_ip_and_global_reservations_are_shared_across_visitors():
    first = rl.reserve_guest_agent_tokens("visitor-d", "203.0.113.13", 12000)
    second = rl.reserve_guest_agent_tokens("visitor-e", "203.0.113.13", 12000)
    assert first is not None and second is not None
    rl.settle_guest_agent_tokens(first, 12000)
    rl.settle_guest_agent_tokens(second, 12000)
    assert rl.peek_guest_agent_tokens("visitor-d", "203.0.113.13")[0] == 12000
    assert rl.peek_guest_agent_tokens("visitor-e", "203.0.113.13")[0] == 12000
