#!/usr/bin/env python3
"""CGDA 服务端问题反馈扫描器（只读；供 AI 编码助手 / 工程师使用）。

读取 ``BACKEND_DATA_ROOT/_runtime/feedback/``（或 ``BACKEND_FEEDBACK_DIR``）
下的反馈目录，输出结构化摘要 / 完整详情，供问题分析与规范化修复入口使用。

用法::

    Env\\Python312\\python.exe Tools/feedback_triage.py                 # 全部反馈摘要
    Env\\Python312\\python.exe Tools/feedback_triage.py --open           # 仅未受理/未修复（AI 待办）
    Env\\Python312\\python.exe Tools/feedback_triage.py --show CGDA-BUG-20260820-B86U
    Env\\Python312\\python.exe Tools/feedback_triage.py --count
    Env\\Python312\\python.exe Tools/feedback_triage.py --dir <反馈目录>

设计原则：
- 纯标准库（json/os/pathlib），无第三方依赖；不 import backend（Tools/ 主线外辅助）。
- 只读：绝不修改 / 删除反馈数据（删除走处理台或 DELETE /feedback/api/reports/{id}）。
- AI 解析友好：摘要为对齐文本，详情为 ``key: value`` 扁平行。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

#: 与后端 _RESPONSE_STATUSES / 处理台 STATUS 保持同义
STATUS_LABELS = {
    "submitted": "已提交(未受理)",
    "received": "已受理",
    "in_progress": "处理中",
    "needs_info": "待补充信息",
    "fixed": "已修复",
    "closed": "已关闭",
    "rejected": "不予处理",
}
#: 视为"已闭环"的状态（不在待办清单中）
CLOSED_STATUSES = {"fixed", "closed", "rejected"}
SEVERITY = {"low": "低", "medium": "中", "high": "高", "critical": "紧急"}


def resolve_feedback_dir(explicit: str | None) -> Path:
    """反馈根目录解析：--dir > BACKEND_FEEDBACK_DIR > BACKEND_RUNTIME_ROOT/feedback
    > BACKEND_DATA_ROOT/_runtime/feedback > 候选探测（存在即用）> 开发兜底。"""
    if explicit:
        return Path(explicit)
    env = os.getenv("BACKEND_FEEDBACK_DIR", "").strip()
    if env:
        return Path(env)
    runtime = os.getenv("BACKEND_RUNTIME_ROOT", "").strip()
    if runtime:
        return Path(runtime) / "feedback"
    data_root = os.getenv("BACKEND_DATA_ROOT", "").strip()
    if data_root:
        return Path(data_root) / "_runtime" / "feedback"
    # 候选探测：项目现行 DATA_ROOT（I:/Geograph_DataSet，见 deployment.config.json /
    # .workbuddy memory 约定）优先；其次开发兜底。保证无 env 时也能命中真实反馈。
    repo_root = Path(__file__).resolve().parents[1]
    for candidate in (
        Path("I:/Geograph_DataSet") / "_runtime" / "feedback",
        repo_root / "Code" / "backend" / ".data" / "_runtime" / "feedback",
    ):
        if candidate.is_dir():
            return candidate
    return repo_root / "Code" / "backend" / ".data" / "_runtime" / "feedback"


def read_json(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def status_of(rid_dir: Path) -> tuple[str, dict | None]:
    """返回 (状态, response 对象或 None)。response.json 不存在 → submitted。"""
    resp = read_json(rid_dir / "response.json")
    if resp is None:
        return "submitted", None
    status = str(resp.get("status") or "received")
    return (status if status in STATUS_LABELS else "received"), resp


def iter_reports(root: Path):
    if not root.exists():
        return
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        report = read_json(child / "report.json")
        if report is None:
            continue
        yield child, report


def _inner(report: dict) -> dict:
    inner = report.get("report")
    return inner if isinstance(inner, dict) else report


def summarize(root: Path, only_open: bool):
    rows = []
    for rid_dir, report in iter_reports(root):
        rid = rid_dir.name
        inner = _inner(report)
        meta = read_json(rid_dir / "meta.json") or {}
        att_dir = rid_dir / "attachments"
        att_count = len([p for p in att_dir.iterdir()]) if att_dir.is_dir() else 0
        status, resp = status_of(rid_dir)
        if only_open and status in CLOSED_STATUSES:
            continue
        assignee = ""
        if resp and isinstance(resp.get("assignee"), dict):
            assignee = str(resp["assignee"].get("name") or "")
        contact = inner.get("contact") if isinstance(inner.get("contact"), dict) else {}
        rows.append(
            {
                "id": rid,
                "status": status,
                "sev": SEVERITY.get(str(inner.get("severity")), "—"),
                "title": str(inner.get("title") or "（无标题）")[:36],
                "category": str(inner.get("categoryLabel") or inner.get("category") or "—")[:10],
                "by": str(contact.get("name") or "匿名")[:12],
                "atts": att_count,
                "uploaded": str(meta.get("uploadedAt") or "")[:19],
                "assignee": assignee[:12],
            }
        )
    if not rows:
        print("（无反馈记录）" if not only_open else "（无未闭环反馈）")
        return
    hdr = f"{'编号':<26} {'状态':<18} {'严重':<4} {'类型':<10} {'提交人':<12} {'附件':<4} {'上传时间':<19} 受理人"
    print(hdr)
    print("-" * len(hdr.encode("gbk", "replace")) if sys.platform.startswith("win") else "-" * len(hdr))
    for r in rows:
        print(
            f"{r['id']:<26} {STATUS_LABELS.get(r['status'], r['status']):<18} "
            f"{r['sev']:<4} {r['category']:<10} {r['by']:<12} {r['atts']:<4} "
            f"{r['uploaded']:<19} {r['assignee']}"
        )


def show(root: Path, rid: str):
    rid_dir = root / rid
    report = read_json(rid_dir / "report.json")
    if report is None:
        print(f"未找到反馈目录：{rid_dir}", file=sys.stderr)
        sys.exit(2)
    inner = _inner(report)
    meta = read_json(rid_dir / "meta.json") or {}
    status, resp = status_of(rid_dir)

    def kv(k: str, v) -> None:
        print(f"{k}: {v if v not in (None, '') else '—'}")

    print(f"reportId: {rid}")
    print(f"status: {STATUS_LABELS.get(status, status)}（{status}）")
    kv("title", inner.get("title"))
    kv("category", inner.get("categoryLabel") or inner.get("category"))
    kv("severity", inner.get("severityLabel") or SEVERITY.get(str(inner.get("severity"))))
    kv("createdAt", inner.get("createdAt"))
    kv("uploadedAt", meta.get("uploadedAt"))
    kv("description", str(inner.get("description") or "").strip()[:2000])
    kv("steps", str(inner.get("steps") or "").strip()[:1500])
    kv("expected", inner.get("expected"))
    kv("actual", inner.get("actual"))
    contact = inner.get("contact") if isinstance(inner.get("contact"), dict) else {}
    if contact:
        print("contact: " + json.dumps(
            {k: contact.get(k) for k in ("name", "role", "contact", "deviceId") if contact.get(k)},
            ensure_ascii=False,
        ))
    env = inner.get("env") if isinstance(inner.get("env"), dict) else {}
    if env:
        print("env: " + json.dumps(env, ensure_ascii=False)[:800])
    client = inner.get("client") if isinstance(inner.get("client"), dict) else {}
    if client:
        print("client: " + json.dumps(client, ensure_ascii=False)[:400])
    att_dir = rid_dir / "attachments"
    if att_dir.is_dir():
        names = [p.name for p in sorted(att_dir.iterdir()) if p.is_file()]
        if names:
            print("attachments: " + ", ".join(names[:20]))
    if resp:
        print("--- response ---")
        kv("resp_status", resp.get("status"))
        kv("updatedAt", resp.get("updatedAt"))
        kv("assignee", json.dumps(resp.get("assignee"), ensure_ascii=False) if resp.get("assignee") else None)
        if resp.get("timeline"):
            print("timeline:")
            for t in resp["timeline"]:
                print(f"  - [{t.get('at')}] {STATUS_LABELS.get(str(t.get('status')), t.get('status'))}: {t.get('note')}")
        if resp.get("replies"):
            print("replies:")
            for q in resp["replies"]:
                print(f"  - {q.get('at')} {q.get('author')}（{q.get('role')}）: {q.get('body')}")
    print("--- 处理入口 ---")
    print("处理台: /feedback/console.html（admin 会话）")
    print("删除:   DELETE /feedback/api/reports/{id}（admin）")


def count(root: Path):
    total = open_n = 0
    by_status: dict[str, int] = {}
    for rid_dir, _ in iter_reports(root):
        total += 1
        status, _ = status_of(rid_dir)
        by_status[status] = by_status.get(status, 0) + 1
        if status not in CLOSED_STATUSES:
            open_n += 1
    print(f"反馈总数: {total}")
    print(f"未闭环: {open_n}")
    for s in sorted(by_status):
        print(f"  {STATUS_LABELS.get(s, s)}: {by_status[s]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="CGDA 服务端问题反馈扫描器（只读）")
    ap.add_argument("--dir", help="反馈根目录（覆盖环境变量/默认推导）")
    ap.add_argument("--open", action="store_true", help="仅列出未受理/未修复的反馈（AI 待办）")
    ap.add_argument("--show", metavar="ID", help="打印单条反馈完整详情")
    ap.add_argument("--count", action="store_true", help="统计反馈数与状态分布")
    args = ap.parse_args()
    root = resolve_feedback_dir(args.dir)
    if not root.is_dir():
        print(f"反馈目录不存在：{root}", file=sys.stderr)
        print("提示：可用 --dir 指定，或确认后端已启动且上传过反馈。", file=sys.stderr)
        return 1
    if args.show:
        show(root, args.show)
    elif args.count:
        count(root)
    else:
        summarize(root, only_open=args.open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
