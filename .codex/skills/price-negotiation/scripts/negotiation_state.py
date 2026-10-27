#!/usr/bin/env python3
"""Validate and update Trove negotiation Markdown records.

The script is deliberately limited to deterministic state handling. Market
judgement, seller intent, and outgoing messages remain human/model decisions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


STATUSES = {
    "draft",
    "ready_to_contact",
    "backup_ready",
    "awaiting_reply",
    "negotiating",
    "awaiting_user",
    "handoff",
    "stale",
    "completed",
    "unavailable",
    "rejected",
    "abandoned",
}

ACTIVE_STATUSES = {"awaiting_reply", "negotiating", "awaiting_user", "handoff"}
PENDING_STATUSES = {"draft", "ready_to_contact", "backup_ready"}
TERMINAL_STATUSES = {"completed", "unavailable", "rejected", "abandoned"}

TRANSITIONS = {
    "draft": {"ready_to_contact", "backup_ready", "unavailable", "abandoned"},
    "ready_to_contact": {"awaiting_reply", "unavailable", "abandoned"},
    "backup_ready": {"ready_to_contact", "unavailable", "abandoned"},
    "awaiting_reply": {
        "negotiating",
        "awaiting_user",
        "stale",
        "unavailable",
        "abandoned",
    },
    "negotiating": {
        "awaiting_reply",
        "awaiting_user",
        "handoff",
        "unavailable",
        "rejected",
        "abandoned",
    },
    "awaiting_user": {
        "awaiting_reply",
        "negotiating",
        "handoff",
        "unavailable",
        "rejected",
        "abandoned",
    },
    "handoff": {
        "awaiting_reply",
        "negotiating",
        "completed",
        "unavailable",
        "abandoned",
    },
    "stale": {
        "ready_to_contact",
        "awaiting_reply",
        "negotiating",
        "awaiting_user",
        "unavailable",
        "abandoned",
    },
}

FIELD_RE = re.compile(r"^- ([^：\n]+)：(.*)$", re.MULTILINE)
MONEY_RE = re.compile(r"(?<!\d)(\d[\d,]*(?:\.\d+)?)")
TITLE_RE = re.compile(r"^# 谈价记录：(.+)$", re.MULTILINE)

REQUIRED_FIELDS = (
    "商品 ID",
    "平台",
    "链接",
    "卖家",
    "地区",
    "当前挂牌价",
    "商品状态",
    "市场样本",
    "市场参考价",
    "估算合理成交价",
    "首报",
    "目标价",
    "最高可接受价",
    "谈价状态",
    "最后检查时间",
    "最后我方消息",
    "最后卖家消息",
    "最后卖家消息哈希",
    "下次跟进",
    "卖家承诺",
    "风险事项",
)


def find_records_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "records" / "negotiation"
        if candidate.is_dir():
            return candidate
    return Path.cwd() / "records" / "negotiation"


def record_files(records_dir: Path) -> list[Path]:
    return sorted(path for path in records_dir.glob("*.md") if path.is_file())


def fields(text: str) -> dict[str, str]:
    return {key.strip(): value.strip() for key, value in FIELD_RE.findall(text)}


def money(field: dict[str, str], key: str) -> float | None:
    match = MONEY_RE.search(field.get(key, ""))
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def parse_time(value: str) -> datetime | None:
    value = value.strip()
    if not value or value == "-":
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def load_record(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    parsed = fields(text)
    title_match = TITLE_RE.search(text)
    model = title_match.group(1).strip() if title_match else path.stem
    return {
        "path": path,
        "text": text,
        "fields": parsed,
        "model": model,
        "id": parsed.get("商品 ID", ""),
        "status": parsed.get("谈价状态", ""),
        "current_price": money(parsed, "当前挂牌价"),
        "first_offer": money(parsed, "首报"),
        "target_price": money(parsed, "目标价"),
        "max_price": money(parsed, "最高可接受价"),
        "next_follow_up": parsed.get("下次跟进", ""),
    }


def all_records(records_dir: Path) -> list[dict[str, object]]:
    return [load_record(path) for path in record_files(records_dir)]


def find_by_id(records_dir: Path, listing_id: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    records = all_records(records_dir)
    matches = [record for record in records if record["id"] == listing_id]
    return (matches[0], records) if len(matches) == 1 else ({}, records)


def validate_records(records_dir: Path) -> tuple[list[str], list[dict[str, object]]]:
    errors: list[str] = []
    records = all_records(records_dir)
    seen_ids: dict[str, Path] = {}

    for record in records:
        path = record["path"]
        parsed = record["fields"]
        missing = [key for key in REQUIRED_FIELDS if key not in parsed]
        if missing:
            errors.append(f"{path.name}: 缺少字段 {', '.join(missing)}")

        listing_id = str(record["id"])
        status = str(record["status"])
        if not listing_id:
            errors.append(f"{path.name}: 商品 ID 为空")
        elif listing_id in seen_ids:
            errors.append(
                f"{path.name}: 商品 ID {listing_id} 与 {seen_ids[listing_id].name} 重复"
            )
        else:
            seen_ids[listing_id] = path

        if status not in STATUSES:
            errors.append(f"{path.name}: 未知状态 {status or '<empty>'}")

        url = parsed.get("链接", "")
        if not url.startswith(("https://", "http://")):
            errors.append(f"{path.name}: 链接不是 http(s) URL")

        current = record["current_price"]
        first = record["first_offer"]
        target = record["target_price"]
        maximum = record["max_price"]
        if None in (current, first, target, maximum):
            errors.append(f"{path.name}: 当前价、首报、目标价或最高可接受价无法解析")
        elif first > target or target > maximum:
            errors.append(
                f"{path.name}: 价格顺序应满足 首报({first:g}) <= 目标({target:g}) "
                f"<= 最高({maximum:g})"
            )

        if status in ACTIVE_STATUSES | PENDING_STATUSES:
            if parse_time(parsed.get("最后检查时间", "")) is None:
                errors.append(f"{path.name}: 未记录有效的最后检查时间")

        if status in {"negotiating", "awaiting_user", "handoff"}:
            message = parsed.get("最后卖家消息", "").strip()
            digest = parsed.get("最后卖家消息哈希", "").strip()
            if not message or message == "-":
                errors.append(f"{path.name}: 当前状态要求记录最后卖家消息")
            if not digest or digest == "-":
                errors.append(f"{path.name}: 当前状态要求记录最后卖家消息哈希")

        if status == "awaiting_reply":
            sent = parsed.get("最后我方消息", "").strip()
            next_follow_up = parse_time(parsed.get("下次跟进", ""))
            if not sent or sent == "-":
                errors.append(f"{path.name}: awaiting_reply 要求记录最后我方消息")
            if next_follow_up is None:
                errors.append(f"{path.name}: awaiting_reply 要求有效的下次跟进时间")

    return errors, records


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def public_record(record: dict[str, object]) -> dict[str, object]:
    parsed = record["fields"]
    follow_up = record.get("next_follow_up", "")
    follow_up_time = parse_time(str(follow_up))
    return {
        "id": record["id"],
        "model": record["model"],
        "status": record["status"],
        "seller": parsed.get("卖家", ""),
        "current_price": record["current_price"],
        "first_offer": record["first_offer"],
        "target_price": record["target_price"],
        "max_price": record["max_price"],
        "last_checked": parsed.get("最后检查时间", ""),
        "next_follow_up": follow_up,
        "follow_up_due": bool(follow_up_time and follow_up_time <= datetime.now()),
        "last_seller_message": parsed.get("最后卖家消息", ""),
        "last_seller_message_hash": parsed.get("最后卖家消息哈希", ""),
        "path": str(record["path"]),
    }


def ensure_transition(current: str, new: str) -> None:
    if new not in STATUSES:
        raise ValueError(f"未知目标状态：{new}")
    if current == new:
        raise ValueError(f"状态已经是 {new}")
    allowed = TRANSITIONS.get(current, set())
    if new not in allowed:
        allowed_text = ", ".join(sorted(allowed)) or "无"
        raise ValueError(f"不允许从 {current} 迁移到 {new}；可进入：{allowed_text}")


def replace_field(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^- {re.escape(key)}：.*$", re.MULTILINE)
    replacement = f"- {key}：{value}"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)
    raise ValueError(f"记录缺少字段：{key}")


def append_timeline(text: str, timestamp: str, note: str) -> str:
    row = f"| {timestamp} | 系统 | {note.replace('|', '/')} |"
    return text.rstrip() + "\n" + row + "\n"


def message_digest(message: str) -> str:
    normalized = re.sub(r"\s+", " ", message).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def update_record(
    path: Path,
    text: str,
    timestamp: str,
    *,
    note: str,
    status: str | None = None,
    our_message: str | None = None,
    seller_message: str | None = None,
    next_follow_up: str | None = None,
    append_event: bool = True,
) -> None:
    text = replace_field(text, "最后检查时间", timestamp)
    if status is not None:
        text = replace_field(text, "谈价状态", status)
    if our_message is not None:
        message = re.sub(r"\s+", " ", our_message).strip()
        text = replace_field(text, "最后我方消息", message or "-")
    if seller_message is not None:
        message = re.sub(r"\s+", " ", seller_message).strip()
        text = replace_field(text, "最后卖家消息", message or "-")
        text = replace_field(text, "最后卖家消息哈希", message_digest(message) if message else "-")
        text = replace_field(text, "最后卖家消息摘要", message[:160] if message else "-")
    if next_follow_up is not None:
        text = replace_field(text, "下次跟进", next_follow_up or "-")
    if append_event:
        text = append_timeline(text, timestamp, note)
    path.write_text(text, encoding="utf-8")


def cmd_validate(args: argparse.Namespace) -> int:
    errors, records = validate_records(args.records_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {len(records)} 条谈价记录通过校验")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    records = all_records(args.records_dir)
    items = [public_record(record) for record in records]
    if args.active_only:
        items = [item for item in items if item["status"] in ACTIVE_STATUSES]
    if args.due_only:
        items = [item for item in items if item["follow_up_due"]]
    if args.json:
        print_json(items)
    else:
        for item in items:
            due = " [到跟进时间]" if item["follow_up_due"] else ""
            print(
                f"{item['id']} | {item['model']} | {item['status']} | "
                f"{item['current_price']:g} 元 | 下次 {item['next_follow_up']}{due}"
            )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    record, records = find_by_id(args.records_dir, args.listing_id)
    if not record:
        count = sum(1 for item in records if item["id"] == args.listing_id)
        detail = "未找到" if count == 0 else f"发现重复 {count} 条"
        print(f"ERROR: 商品 {args.listing_id} {detail}", file=sys.stderr)
        return 1
    print_json(public_record(record))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    records = all_records(args.records_dir)
    counts = Counter(str(record["status"]) for record in records)
    items = [public_record(record) for record in records]
    due = [
        item
        for item in items
        if item["status"] in ACTIVE_STATUSES and item["follow_up_due"]
    ]
    if args.json:
        print_json(
            {
                "total": len(records),
                "by_status": dict(sorted(counts.items())),
                "active": sum(counts[status] for status in ACTIVE_STATUSES),
                "due_follow_ups": due,
            }
        )
    else:
        print(f"总计 {len(records)} 条，active {sum(counts[s] for s in ACTIVE_STATUSES)} 条")
        for status, count in sorted(counts.items()):
            print(f"- {status}: {count}")
        if due:
            print("到跟进时间：")
            for item in due:
                print(f"- {item['id']} {item['model']} ({item['status']})")
    return 0


def cmd_transition(args: argparse.Namespace) -> int:
    record, records = find_by_id(args.records_dir, args.listing_id)
    if not record:
        count = sum(1 for item in records if item["id"] == args.listing_id)
        detail = "未找到" if count == 0 else f"发现重复 {count} 条"
        print(f"ERROR: 商品 {args.listing_id} {detail}", file=sys.stderr)
        return 1
    current = str(record["status"])
    try:
        ensure_transition(current, args.status)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.status == "awaiting_reply":
        if not args.our_message.strip():
            print("ERROR: 进入 awaiting_reply 时必须提供 --our-message", file=sys.stderr)
            return 1
        if parse_time(args.next_follow_up) is None:
            print(
                "ERROR: 进入 awaiting_reply 时必须提供 --next-follow-up YYYY-MM-DD HH:MM",
                file=sys.stderr,
            )
            return 1
    timestamp = args.at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    note = args.note or f"状态 {current} → {args.status}"
    update_record(
        record["path"],
        str(record["text"]),
        timestamp,
        note=note,
        status=args.status,
        our_message=args.our_message or None,
        next_follow_up=args.next_follow_up or None,
    )
    print(f"OK: {args.listing_id} {current} → {args.status}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    record, records = find_by_id(args.records_dir, args.listing_id)
    if not record:
        count = sum(1 for item in records if item["id"] == args.listing_id)
        detail = "未找到" if count == 0 else f"发现重复 {count} 条"
        print(f"ERROR: 商品 {args.listing_id} {detail}", file=sys.stderr)
        return 1

    current = str(record["status"])
    new_status = args.status
    if new_status is None and args.seller_message and current == "awaiting_reply":
        new_status = "negotiating"
    if new_status is not None:
        try:
            ensure_transition(current, new_status)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    if args.next_follow_up:
        if parse_time(args.next_follow_up) is None:
            print("ERROR: 下次跟进时间格式应为 YYYY-MM-DD HH:MM", file=sys.stderr)
            return 1

    timestamp = args.at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    events = []
    if new_status:
        events.append(f"状态 {current} → {new_status}")
    if args.seller_message:
        events.append(f"收到卖家消息：{args.seller_message[:120]}")
    if args.next_follow_up:
        events.append(f"下次跟进 {args.next_follow_up}")
    note = args.note or "；".join(events) or "只读检查，无状态变化"

    update_record(
        record["path"],
        str(record["text"]),
        timestamp,
        note=note,
        status=new_status,
        our_message=None,
        seller_message=args.seller_message,
        next_follow_up=args.next_follow_up,
        append_event=bool(events or args.note),
    )
    print(f"OK: 已更新 {args.listing_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trove 谈价状态管理")
    parser.add_argument(
        "--records-dir",
        type=Path,
        default=find_records_dir(),
        help="谈价记录目录",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="校验所有谈价记录")
    validate.set_defaults(func=cmd_validate)

    list_cmd = subparsers.add_parser("list", help="列出谈价记录")
    list_cmd.add_argument("--active-only", action="store_true")
    list_cmd.add_argument("--due-only", action="store_true")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    show = subparsers.add_parser("show", help="按商品 ID 显示一条记录")
    show.add_argument("listing_id")
    show.set_defaults(func=cmd_show)

    summary = subparsers.add_parser("summary", help="统计状态和到期跟进")
    summary.add_argument("--json", action="store_true")
    summary.set_defaults(func=cmd_summary)

    transition = subparsers.add_parser("transition", help="执行合法状态迁移")
    transition.add_argument("listing_id")
    transition.add_argument("status", choices=sorted(STATUSES))
    transition.add_argument("--our-message", default="")
    transition.add_argument("--next-follow-up", default="")
    transition.add_argument("--note", default="")
    transition.add_argument("--at", default="")
    transition.set_defaults(func=cmd_transition)

    check = subparsers.add_parser("check", help="记录一次回复检查")
    check.add_argument("listing_id")
    check.add_argument("--status", choices=sorted(STATUSES))
    check.add_argument("--seller-message", default="")
    check.add_argument("--next-follow-up", default="")
    check.add_argument("--note", default="")
    check.add_argument("--at", default="")
    check.set_defaults(func=cmd_check)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
