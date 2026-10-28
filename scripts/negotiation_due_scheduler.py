#!/usr/bin/env python3
"""Wake the per-listing Trove thread when a negotiation record is due.

This scheduler is intentionally deterministic and does not use an LLM. It runs
from launchd, reads the negotiation state, and queues one message per target
thread when active listings have reached their per-listing next_follow_up time.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "negotiation_scheduler.json"
STATE_PATH = ROOT / "runtime" / "negotiation_scheduler_state.json"
LOCK_PATH = ROOT / "runtime" / "negotiation_scheduler.lock"
STATE_SCRIPT = ROOT / ".codex" / "skills" / "price-negotiation" / "scripts" / "negotiation_state.py"
LOG_DIR = ROOT / "logs"


def load_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_clock(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def parse_datetime(value: str, timezone: ZoneInfo) -> datetime | None:
    if not value or value == "-":
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone)
        return parsed.astimezone(timezone)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone)
        except ValueError:
            continue
    return None


def in_active_window(now: datetime, config: dict) -> bool:
    start = parse_clock(config["active_window"]["start"])
    end = parse_clock(config["active_window"]["end"])
    current = now.time().replace(tzinfo=None)
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def read_active_records(python_path: str) -> list[dict]:
    result = subprocess.run(
        [python_path, str(STATE_SCRIPT), "list", "--active-only", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "状态脚本读取失败")
    return json.loads(result.stdout or "[]")


def due_records(records: list[dict], timezone: ZoneInfo, now: datetime) -> list[dict]:
    due = []
    for record in records:
        target = parse_datetime(str(record.get("next_follow_up", "")), timezone)
        if target is not None and target <= now:
            due.append(record)
    return due


def group_by_thread(records: list[dict], fallback_thread_id: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for record in records:
        thread_id = str(record.get("thread_id") or fallback_thread_id or "").strip()
        if not thread_id:
            thread_id = ""
        grouped.setdefault(thread_id, []).append(record)
    return grouped


def dispatched_recently(
    state: dict,
    record: dict,
    now: datetime,
    timezone: ZoneInfo,
    retry_minutes: int,
    repeat_minutes: int,
) -> bool:
    saved = state.get("targets", {}).get(str(record["id"]), {})
    if saved.get("next_follow_up") != record.get("next_follow_up"):
        return False
    if saved.get("thread_id") != record.get("thread_id", ""):
        return False
    attempted = parse_datetime(str(saved.get("last_attempt_at", "")), timezone)
    interval = repeat_minutes if saved.get("last_success_at") else retry_minutes
    return attempted is not None and now - attempted < timedelta(minutes=interval)


def write_log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"negotiation-scheduler-{datetime.now().date().isoformat()}.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


def write_error(task: str, detail: str) -> None:
    error_dir = LOG_DIR / "error"
    error_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now()
    path = error_dir / f"{timestamp.strftime('%Y-%m-%d-%H%M%S')}.md"
    path.write_text(
        "\n".join(
            [
                f"- 时间：{timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
                "- 来源：com.trove.negotiation-scheduler",
                f"- 任务：{task}",
                f"- 现象：{detail}",
                "- 根因：Codex 队列命令或本地调度依赖不可用",
                "- 影响：本轮未成功唤醒谈价任务",
                "- 处理：检查 Codex 应用、登录态和 launchd 日志；下轮自动重试",
                "",
            ]
        ),
        encoding="utf-8",
    )


def build_queue_message(records: list[dict], now: datetime) -> str:
    lines = [
        f"Trove 谈价调度唤醒：{now.strftime('%Y-%m-%d %H:%M')} 以下记录已到独立跟进时间。",
        "请加载 price-negotiation skill，只检查这些 listing；按档案中的首报、目标和最高可接受价自动推进，不得超过上限。",
        "例行回复、普通还价和等待保持静默；谈成、售出、出现风险或需要本人购买时再通知。",
    ]
    for record in records:
        lines.append(
            f"- {record['id']} | {record['model']} | {record['seller']} | "
            f"next={record['next_follow_up']}"
        )
    lines.append("完成后按 SOP 更新每条记录的状态、下次跟进、消息哈希和截图。")
    lines.append("用户已授权当前 active 谈价自动发送平台内消息；不得下单、付款、填写地址或泄露隐私。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Trove 逐商品到期调度器")
    parser.add_argument("--dry-run", action="store_true", help="只显示是否会唤醒，不调用 codex queue")
    parser.add_argument("--force", action="store_true", help="忽略运行时段、去重和重试限制")
    parser.add_argument("--now", help="测试用 ISO 时间，例如 2026-10-27T22:55:00")
    args = parser.parse_args()

    config = load_json(CONFIG_PATH, {})
    if not config.get("enabled", False) and not args.force:
        return 0

    timezone = ZoneInfo(config.get("timezone", "Asia/Shanghai"))
    now = (
        datetime.fromisoformat(args.now).replace(tzinfo=timezone)
        if args.now
        else datetime.now(timezone)
    )
    if not args.force and not in_active_window(now, config):
        return 0

    python_path = sys.executable
    codex_path = shutil.which("codex")
    if not codex_path:
        write_log("ERROR codex executable not found")
        write_error("谈价到期调度", "找不到 codex 可执行文件")
        return 1

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0

        state = load_json(STATE_PATH, {"version": 1, "targets": {}})
        try:
            records = read_active_records(python_path)
        except Exception as exc:
            write_log(f"ERROR state read failed: {exc}")
            write_error("读取谈价状态", str(exc))
            return 1
        due = due_records(records, timezone, now)
        retry_minutes = int(config.get("retry_failed_after_minutes", 5))
        repeat_minutes = int(config.get("repeat_unprocessed_after_minutes", 30))
        actionable = [
            record
            for record in due
            if args.force
            or not dispatched_recently(
                state,
                record,
                now,
                timezone,
                retry_minutes,
                repeat_minutes,
            )
        ]
        if not actionable:
            return 0

        fallback_thread_id = str(config.get("thread_id", "")).strip()
        groups = group_by_thread(actionable, fallback_thread_id)
        if args.dry_run:
            for thread_id, group in groups.items():
                print("--- thread", thread_id or "<missing>", "---")
                print(build_queue_message(group, now))
            return 0

        attempted_at = now.isoformat(timespec="seconds")
        targets = state.setdefault("targets", {})
        had_error = False
        for thread_id, group in groups.items():
            record_ids = ",".join(str(record["id"]) for record in group)
            if not thread_id:
                had_error = True
                detail = "缺少谈价线程 ID，且配置没有 fallback thread_id"
                write_log(f"ERROR missing thread ids={record_ids} detail={detail}")
                write_error("启动谈价调度", detail)
                for record in group:
                    item = targets.setdefault(str(record["id"]), {})
                    item["next_follow_up"] = record.get("next_follow_up", "")
                    item["thread_id"] = record.get("thread_id", "")
                    item["last_attempt_at"] = attempted_at
                    item["last_error"] = detail
                continue

            message = build_queue_message(group, now)
            try:
                result = subprocess.run(
                    [codex_path, "queue", "--thread", thread_id, "--message", message],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                had_error = True
                detail = "codex queue 超过 30 秒未返回"
                write_log(f"ERROR queue timed out thread={thread_id} ids={record_ids}")
                write_error("唤醒谈价任务", detail)
                for record in group:
                    item = targets.setdefault(str(record["id"]), {})
                    item["next_follow_up"] = record.get("next_follow_up", "")
                    item["thread_id"] = record.get("thread_id", "")
                    item["last_attempt_at"] = attempted_at
                    item["last_error"] = detail
                continue

            for record in group:
                item = targets.setdefault(str(record["id"]), {})
                item["next_follow_up"] = record.get("next_follow_up", "")
                item["thread_id"] = record.get("thread_id", "")
                item["last_attempt_at"] = attempted_at
                if result.returncode == 0:
                    item["last_success_at"] = attempted_at
                    item["last_error"] = ""
                else:
                    item["last_error"] = (result.stderr or result.stdout or "queue failed").strip()

            if result.returncode != 0:
                had_error = True
                detail = (result.stderr or result.stdout or "queue failed").strip()
                write_log(
                    f"ERROR queue failed thread={thread_id} ids={record_ids} "
                    f"detail={detail}"
                )
                write_error("唤醒谈价任务", detail)
            else:
                write_log(f"queued thread={thread_id} ids={record_ids}")
        atomic_json(STATE_PATH, state)
        return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
