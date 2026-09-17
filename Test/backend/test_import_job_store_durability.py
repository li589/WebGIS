"""导入任务记录（``job-*.json``）的读写健壮性 —— 回归锁。

根因（2026-09-17 CI 偶发）
─────────────────────────
CI 上 ``test_import_job_ownership.py::test_submitter_owns_and_can_read_own_job``
偶发失败：``POST /import/vector`` 返回 **400**，detail 为
``Expecting value: line 1 column 1 (char 0)``（``json.JSONDecodeError`` 原文）。

链路（三处叠加，缺一不可）：
1. ``jobs.create_job`` / ``jobs.update_job`` 原先用 ``path.write_text(...)``
   —— 这是「先截断、再写」，**不是**原子替换，文件在窗口期内为 0 字节；
2. ``jobs.enqueue_job`` 的 ``force_async`` 分支：启动 worker 线程后**立即**
   ``return get_job(job_id)`` 回读同一文件，而 worker 线程起步就是
   ``run_job_sync`` → ``update_job`` → 重写同一文件；两者天然并发；
3. 请求线程的回读恰好落在截断窗口 → ``json.loads("")`` 抛 ``JSONDecodeError``。
   而 ``json.JSONDecodeError`` 是 **``ValueError`` 子类**，被 ``import_vector``
   的 ``except (..., ValueError, ...)`` 吞掉 → ``_http_err`` → 400，
   并把解析器原文当作 ``detail`` 泄露给客户端。

修复（两侧各一处）
──────────────────
* 写入侧：``create_job`` / ``update_job`` 改走
  ``app.data_io.services._meta_io.save_json_atomic``（同目录 ``.tmp`` +
  ``os.replace``），与仓库内 ``meta.json`` / ``bounds.json`` / ``feedback_store``
  等既有模式一致 → 读者只能看到「旧的完整内容」或「新的完整内容」；
* 边界侧：``data_io.api.router._http_err`` 先于 ``ValueError`` 分支对
  ``json.JSONDecodeError`` re-raise（子类先于父类，与 507-before-400 同一惯例）
  → 交全局处理器返回 500 + 通用文案，不再 400 泄露。

本文件锁三件事
──────────────
A. 原子写不留 ``.tmp`` 残留，且记录始终可解析；
B. 并发「写-读」下读者**永不**看到半写内容（修复前必红）；
C. ``_http_err`` 对 ``JSONDecodeError`` 的行为（不降级为 400、不泄露）。

刻意**不**断言的点
──────────────────
``get_job`` 读到损坏文件时应抛 ``JSONDecodeError``（服务端故障）而**不是**
404 / 空记录 —— 该契约由 ``test_exception_narrowing.py`` 场景 4a 把守，
本文件不重复造第二套期望，避免两处契约漂移。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

_CODE_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PROVIDER = _CODE_ROOT / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


@pytest.fixture()
def jobs_mod(tmp_path, monkeypatch):
    """隔离 ``output_root`` → ``jobs_dir()`` 落到 ``tmp_path``，不污染真实数据根。

    ``paths.output_root()`` 惰性读取 ``app.core.config.settings``（模块属性），
    故替换模块属性即可生效，无需重导模块（与 ``test_auth.py`` 同一手法）。
    """
    import app.core.config as cfg_mod

    monkeypatch.setattr(
        cfg_mod,
        "settings",
        replace(
            cfg_mod.settings,
            environment="test",
            output_root=str(tmp_path / "out"),
        ),
    )

    from app.data_io.services import jobs as module

    return module


def _create(module, **kwargs):
    return module.create_job(
        kind=kwargs.pop("kind", "vector"),
        payload=kwargs.pop("payload", {"paths": ["x.shp"]}),
        owner_user_id=kwargs.pop("owner_user_id", 1),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# A. 原子写：无 .tmp 残留，记录始终可解析
# ---------------------------------------------------------------------------


def test_create_and_update_job_leave_no_tmp_residue(jobs_mod):
    """写入走 ``save_json_atomic``：临时文件必须已被 ``os.replace`` 消费掉。

    残留 ``.tmp`` 说明写入路径退化成了「写临时文件但没替换」之类的半成品实现。
    """
    job_id = _create(jobs_mod)
    job_dir = jobs_mod.jobs_dir()
    assert list(job_dir.glob("*.tmp")) == [], "create_job 后出现 .tmp 残留"

    jobs_mod.update_job(job_id, status="running", progress=0.5)
    assert list(job_dir.glob("*.tmp")) == [], "update_job 后出现 .tmp 残留"

    record = jobs_mod.get_job(job_id)
    assert record["job_id"] == job_id
    assert record["status"] == "running"
    assert record["progress"] == 0.5
    assert record["owner_user_id"] == 1
    assert record["payload"] == {"paths": ["x.shp"]}


def test_update_job_preserves_untouched_fields(jobs_mod):
    """读-改-写不得丢字段（``payload`` / ``owner_user_id`` / ``created_at``）。"""
    job_id = _create(jobs_mod, owner_user_id=42)
    before = jobs_mod.get_job(job_id)

    jobs_mod.update_job(job_id, status="succeeded", result={"layer_id": "L1"})
    after = jobs_mod.get_job(job_id)

    assert after["status"] == "succeeded"
    assert after["result"] == {"layer_id": "L1"}
    assert after["owner_user_id"] == 42
    assert after["created_at"] == before["created_at"]
    assert after["updated_at"] >= before["updated_at"]


def test_job_file_on_disk_is_always_valid_json(jobs_mod):
    """落盘内容必须可直接 ``json.loads``（避免写出非法字面量）。"""
    for i in range(20):
        job_id = _create(jobs_mod, payload={"i": i, "text": "中文/emoji ✅"})
        jobs_mod.update_job(job_id, progress=i)
        raw = jobs_mod._job_path(job_id).read_text(encoding="utf-8")
        assert json.loads(raw)["job_id"] == job_id


# ---------------------------------------------------------------------------
# B. 并发回归：写者高频重写，读者永不见半写内容（修复前必红）
# ---------------------------------------------------------------------------


def test_concurrent_update_and_read_never_sees_partial_json(jobs_mod):
    """``enqueue_job`` 竞态的等价复现：worker 写 / 请求线程读。

    修复前（非原子 ``write_text``）读者会读到 0 字节文件 → ``JSONDecodeError``，
    正是 CI 上 400 的来源。修复后只允许两种结果：读到合法记录，或
    ``FileNotFoundError``（文件尚未落盘；本用例中实际不会出现）。
    """
    # 放大载荷 → 拉长写入窗口，使修复前的「截断窗口命中」稳定复现
    blob = "x" * 262_144
    job_id = _create(jobs_mod, payload={"blob": blob}, owner_user_id=1)

    stop = threading.Event()
    corrupt: list[str] = []
    read_oserrors: list[str] = []
    writer_errors: list[str] = []
    stats = {"writes": 0, "reads": 0}

    def writer() -> None:
        i = 0
        while not stop.is_set():
            i += 1
            try:
                jobs_mod.update_job(job_id, progress=i % 100, blob=blob)
                stats["writes"] += 1
            except Exception as exc:  # noqa: BLE001 — 显式收集，便于断言诊断
                writer_errors.append(f"{type(exc).__name__}: {exc}")
                return

    def reader() -> None:
        while not stop.is_set():
            stats["reads"] += 1
            try:
                record = jobs_mod.get_job(job_id)
            except FileNotFoundError:
                continue  # 允许：文件尚未落盘
            except json.JSONDecodeError as exc:
                # ← 修复前会稳定命中这里
                corrupt.append(str(exc))
                return
            except OSError as exc:  # Windows 上 replace 与读并发的 sharing violation
                read_oserrors.append(f"{type(exc).__name__}: {exc}")
                continue
            if not isinstance(record, dict) or record.get("job_id") != job_id:
                corrupt.append(f"读到非法记录: {record!r}")
                return

    threads = [
        threading.Thread(target=writer, name="job-writer"),
        threading.Thread(target=reader, name="job-reader"),
    ]
    for t in threads:
        t.start()
    time.sleep(1.5)
    stop.set()
    for t in threads:
        t.join(timeout=15)
    assert not any(t.is_alive() for t in threads), "读写线程未在超时内退出"

    assert (
        stats["writes"] > 0 and stats["reads"] > 0
    ), f"未产生并发读写，用例无效: {stats}"
    assert not writer_errors, f"写入侧抛出异常: {writer_errors[:3]}"
    # 核心断言：读者永远不得看到半写 / 不可解析内容
    assert not corrupt, (
        f"并发读出现不可解析内容（原子写失效）: {corrupt[:3]} "
        f"(writes={stats['writes']} reads={stats['reads']})"
    )
    # 收尾：文件必须是合法 JSON
    assert jobs_mod.get_job(job_id)["job_id"] == job_id
    if read_oserrors:  # 平台级瞬态，记录但不判红（与数据损坏不同类）
        print(f"[info] Windows sharing violation 计数: {len(read_oserrors)}")


def test_torn_file_scenario_is_reproduced_by_direct_truncation(jobs_mod):
    """确定性复现：把文件截成 0 字节 → 裸读必然 ``JSONDecodeError``。

    这是上面并发用例的「定标」对照：证明该异常类型确实可被 `get_job` 抛出，
    从而说明并发用例断言的不是一个不可能发生的事件。
    """
    job_id = _create(jobs_mod)
    jobs_mod._job_path(job_id).write_text("", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        jobs_mod.get_job(job_id)


# ---------------------------------------------------------------------------
# B2. 按 job 粒度的互斥：多写者各写各的字段，不得 lost update
# ---------------------------------------------------------------------------


def test_concurrent_distinct_field_writes_do_not_lose_updates(jobs_mod):
    """8 个写者各写自己的字段：结束后**每个字段都必须在**。

    这是 ``job_lock`` 的核心回归锁。``update_job`` 是「读 → 改 → 写」，若不加锁，
    写者 A 先读到不含 ``fB`` 的快照、B 写完 ``fB``、A 再落盘就会把 ``fB`` 抹掉
    （lost update）。**加锁前本用例必红**。
    """
    job_id = _create(jobs_mod)
    n_writers, rounds = 8, 40
    errors: list[str] = []
    barrier = threading.Barrier(n_writers)

    def writer(index: int) -> None:
        try:
            barrier.wait(timeout=15)  # 尽量让所有写者同时进入临界区竞争
            for _ in range(rounds):
                jobs_mod.update_job(job_id, **{f"f{index}": True})
        except Exception as exc:  # noqa: BLE001 — 收集后统一断言，便于诊断
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), "写者线程未在超时内退出"
    assert not errors, f"写者抛出异常: {errors[:3]}"

    record = jobs_mod.get_job(job_id)
    missing = [f"f{i}" for i in range(n_writers) if not record.get(f"f{i}")]
    assert not missing, f"lost update：这些写者的字段被覆盖丢失 {missing}"


def test_job_lock_serializes_critical_sections(jobs_mod):
    """互斥本身可验证：临界区内并发计数不得 > 1。"""
    job_id = _create(jobs_mod)

    inside = 0
    max_inside = 0
    violations: list[int] = []
    guard = threading.Lock()

    def worker() -> None:
        nonlocal inside, max_inside
        for _ in range(30):
            with jobs_mod.job_lock(job_id):
                with guard:
                    inside += 1
                    max_inside = max(max_inside, inside)
                    if inside > 1:
                        violations.append(inside)
                time.sleep(0.001)  # 拉长临界区，放大未互斥时的重叠概率
                with guard:
                    inside -= 1

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not violations, f"临界区出现并发进入（锁失效）: {violations[:5]}"
    assert max_inside == 1, f"临界区最大并发数应为 1，实为 {max_inside}"


def test_lock_anchor_is_not_mistaken_for_a_job(jobs_mod):
    """锁锚点 ``<job_id>.lock`` 不得被 ``list_jobs`` 的 ``job-*.json`` glob 扫到。"""
    job_id = _create(jobs_mod)
    jobs_mod.update_job(job_id, progress=0.1)  # 该调用会创建锁锚点

    job_dir = jobs_mod.jobs_dir()
    assert list(job_dir.glob("*.lock")), "未创建锁锚点，说明加锁路径没生效"

    listed = [i["job_id"] for i in jobs_mod.list_jobs(limit=100, include_all=True)]
    assert job_id in listed
    assert all(".lock" not in str(x) for x in listed)


# ---------------------------------------------------------------------------
# B3. 取消与终态写入互斥（cancel 不得被覆盖 / 也不得覆盖终态）
# ---------------------------------------------------------------------------


def test_cancel_job_does_not_overwrite_terminal_state(jobs_mod):
    """已成功的任务再取消，状态必须保持 ``succeeded``（不得被回退成 cancelled）。"""
    job_id = _create(jobs_mod)
    jobs_mod.update_job(job_id, status="succeeded", progress=1.0)

    result = jobs_mod.cancel_job(job_id)

    assert result["status"] == "succeeded"
    assert jobs_mod.get_job(job_id)["status"] == "succeeded"


def test_cancel_job_marks_queued_job_cancelled(jobs_mod):
    job_id = _create(jobs_mod)  # 初始 status=queued
    result = jobs_mod.cancel_job(job_id)
    assert result["status"] == "cancelled"
    assert jobs_mod.get_job(job_id)["status"] == "cancelled"


def test_run_job_sync_preserves_cancel_issued_inside_handler(jobs_mod):
    """处理器内取消 → 终态保持 cancelled。

    一个用例锁两件事：
    1. ``handler`` **不在锁内**执行——否则处理器里再调 ``cancel_job``（要取同一把锁）
       会自锁死，本用例将直接超时；
    2. 取消优先于成功——终态写入前在同一把锁内复查，cancelled 不被覆盖为 succeeded。
    """
    job_id = _create(jobs_mod)

    def handler(_payload: dict) -> dict:
        jobs_mod.cancel_job(job_id)
        return {"layer_id": "should-not-win"}

    final = jobs_mod.run_job_sync(job_id, handler)

    assert final["status"] == "cancelled"
    assert jobs_mod.get_job(job_id)["status"] == "cancelled"


def test_run_job_sync_completes_when_not_cancelled(jobs_mod):
    """未取消时正常落到 succeeded，并把 handler 结果写入 ``result``。"""
    job_id = _create(jobs_mod)
    final = jobs_mod.run_job_sync(job_id, lambda _p: {"layer_id": "L-1"})
    assert final["status"] == "succeeded"
    assert final["result"] == {"layer_id": "L-1"}
    assert final["error"] is None


def test_run_job_sync_records_failure(jobs_mod):
    """handler 抛错 → ``failed`` + ``error`` 文案，且异常继续上抛（调用方需感知）。"""
    job_id = _create(jobs_mod)

    def boom(_payload: dict) -> dict:
        raise ValueError("bad shapefile")

    with pytest.raises(ValueError):
        jobs_mod.run_job_sync(job_id, boom)

    record = jobs_mod.get_job(job_id)
    assert record["status"] == "failed"
    assert "bad shapefile" in record["error"]


# ---------------------------------------------------------------------------
# C. 边界收窄：JSONDecodeError 不得被父类 ValueError 降级为 400
# ---------------------------------------------------------------------------


def test_http_err_reraises_json_decode_error_before_value_error_branch():
    """``JSONDecodeError`` ⊂ ``ValueError``，但语义是**服务端**故障。

    若被父类分支命中 → 400 + ``detail`` 为解析器原文（含服务端路径），
    与 ``test_exception_narrowing.py`` 场景 4a 的既有契约（500 + 通用文案）冲突。
    """
    from app.data_io.api.router import _http_err

    exc = json.JSONDecodeError("Expecting value", "doc", 0)
    with pytest.raises(json.JSONDecodeError):
        _http_err(exc)


def test_http_err_still_maps_plain_value_error_to_400():
    """收窄不得误伤：真正的客户端输入错误仍是 400 + 原 detail。"""
    from app.data_io.api.router import _http_err

    translated = _http_err(ValueError("upload_ids 不能为空"))
    assert translated.status_code == 400
    assert "upload_ids" in translated.detail


@pytest.fixture(scope="module")
def transfer_client(tmp_path_factory):
    """具备数据交换权限的 API 客户端（admin API key），用于端点级断言。

    module 级：app 启动约 10s，函数级会让本文件在 CI 上过慢。
    """
    tmp_path = tmp_path_factory.mktemp("job_store_e2e")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "true")
    monkeypatch.setenv("BACKEND_API_KEY", "job-store-test-key")
    monkeypatch.setenv("BACKEND_API_KEY_ROLE", "admin")

    import app.core.config as cfg_mod
    from app.core.config import Settings

    cfg_mod.settings = replace(Settings(), environment="test")
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "job-store-test-key",
    )

    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(
        create_app(),
        raise_server_exceptions=False,
        headers={"X-API-Key": "job-store-test-key"},
    ) as client:
        yield client
    monkeypatch.undo()


def test_import_vector_corrupt_job_store_returns_500_not_400(
    transfer_client, tmp_path, monkeypatch
):
    """端点级症状锁：服务端 JSON 损坏 → 500 + 通用文案（**不是** 400 + 解析器原文）。

    修复前 ``import_vector`` 的 ``except (..., ValueError, ...)`` 会把
    ``JSONDecodeError``（``ValueError`` 子类，由 ``enqueue_job`` 回读竞态抛出）
    翻译成 400，并把 ``Expecting value: line 1 column 1 (char 0)`` 当作 detail 返回
    —— 正是 2026-09-17 CI 上观测到的响应体。
    """
    from app.data_io.api import router as router_mod

    upload = tmp_path / "sample.shp"
    upload.write_bytes(b"not-a-real-shapefile")

    monkeypatch.setattr(router_mod, "assert_upload_access", lambda *a, **k: None)
    monkeypatch.setattr(router_mod, "resolve_upload_path", lambda _uid: upload)

    def _boom(*_a, **_k):
        raise json.JSONDecodeError("Expecting value", "doc", 0)

    monkeypatch.setattr(router_mod, "enqueue_job", _boom)

    resp = transfer_client.post(
        "/import/vector",
        json={"upload_ids": ["fake-uid"], "async_mode": True},
    )

    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["detail"] == "Internal server error"
    # 不得泄露解析器原文 / 服务端路径
    assert "Expecting value" not in json.dumps(body, ensure_ascii=False)
