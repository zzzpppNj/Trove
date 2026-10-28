#!/usr/bin/env python3
"""Review market results and trigger first-contact negotiation candidates.

This script only creates draft negotiation records. The collection agent must
live-check each immediate candidate before sending its first message.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "negotiation_trigger.json"
PRICING_PATH = ROOT / "config" / "pricing.json"
MARKET_DIR = ROOT / "records" / "market"
STATS_DIR = MARKET_DIR / "stats"
NEGOTIATION_DIR = ROOT / "records" / "negotiation"
DECISION_DIR = NEGOTIATION_DIR / "trigger-decisions"
STATE_SCRIPT = ROOT / ".codex" / "skills" / "price-negotiation" / "scripts" / "negotiation_state.py"

sys.path.insert(0, str(ROOT / "scripts"))

import acquisition_policy  # noqa: E402


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_pricing() -> list[dict]:
    return list(load_json(PRICING_PATH).get("items", []))


def price_item_for_model(model: str, pricing: list[dict]) -> dict | None:
    for item in pricing:
        names = [item.get("model", ""), *(item.get("aliases") or [])]
        if model in names:
            return item
    return None


def load_stats() -> dict[str, dict]:
    result = {}
    for path in sorted(STATS_DIR.glob("*.json")):
        item = load_json(path)
        model = str(item.get("model", "")).strip()
        if model:
            result[model] = item
    return result


def read_negotiations() -> list[dict]:
    result = subprocess.run(
        [
            "python3",
            str(STATE_SCRIPT),
            "list",
            "--include-archived",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "读取谈价记录失败")
    return json.loads(result.stdout or "[]")


def reject_reason(record: dict, config: dict) -> str | None:
    flags = set(record.get("flags") or [])
    rejected = sorted(flags.intersection(config.get("reject_flags", [])))
    if rejected:
        return f"风险标记：{', '.join(rejected)}"
    text = f"{record.get('title', '')} {record.get('notes', '')}"
    matched_patterns = [
        pattern for pattern in config.get("reject_text_patterns", [])
        if pattern in text
    ]
    if matched_patterns:
        return f"描述包含高风险信息：{', '.join(matched_patterns)}"
    if record.get("seller_type") not in config.get("allowed_seller_types", ["personal"]):
        return f"卖家类型不适合首谈：{record.get('seller_type') or 'unknown'}"
    price = record.get("listing_price")
    if not isinstance(price, (int, float)):
        return "挂牌价无效"
    if price > float(config.get("max_listing_price", 1000)):
        return "超过单件预算上限"
    return None


def priority_score(record: dict, result: dict) -> tuple[float, list[str]]:
    profit = float(result.get("expected_profit") or 0)
    roi = float(result.get("roi_pct") or 0)
    score = round(profit, 2) + round(roi, 2)
    reasons = [f"预计净利 {profit:g} 元、ROI {roi:g}%"]

    if record.get("seller_type") == "personal":
        score += 10
        reasons.append("个人卖家")
    if record.get("platform_inspection"):
        score += 5
        reasons.append("支持平台验货")
    if record.get("face_to_face"):
        score += 5
        reasons.append("支持面交")
    text = f"{record.get('title', '')} {record.get('notes', '')}"
    if re.search(r"原盒|原包装|带盒", text):
        score += 4
        reasons.append("描述含原盒")
    if re.search(r"绑带|绑腿", text):
        score += 3
        reasons.append("描述含绑带")
    return round(score, 2), reasons


def slugify_model(model: str) -> str:
    value = re.sub(r"[\s/]+", "-", model.strip())
    value = re.sub(r"[^\w\-\u4e00-\u9fff]", "", value)
    return value.strip("-") or "item"


def draft_path(day: str, record: dict) -> Path:
    return NEGOTIATION_DIR / f"{day}-{slugify_model(record['model'])}-{record['id']}.md"


def draft_text(record: dict, stats: dict, item: dict, trigger: dict, decision: dict) -> str:
    price = float(record["listing_price"])
    result = decision.get("policy") or {}
    p25 = float(stats.get("p25") or item["good_price_line"])
    p75 = float(stats.get("p75") or item["reference_price"]["max"])
    first_offer = max(1, round(price * (1 - float(trigger["first_offer_discount_pct"]) / 100)))
    max_buy_price = float(result.get("max_buy_price") or price)
    target_price = max(1, round(min(price, max_buy_price)))
    first_offer = max(1, min(first_offer, target_price))
    exit_price = float(result.get("expected_exit_price") or 0)
    estimated_low = max(0, round(exit_price))
    estimated_high = max(estimated_low, round(float(stats.get("p75") or exit_price)))
    score, reasons = priority_score(record, result)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = f"# 谈价记录：{record['model']}\n"
    fields = [
        f"- 商品 ID：{record['id']}",
        f"- 平台：{record.get('source', 'xianyu')}",
        f"- 链接：{record.get('url', '')}",
        "- 卖家：待实时复核",
        f"- 卖家类型：{record.get('seller_type', 'unknown')}",
        f"- 地区：{record.get('region', '未知')}",
        f"- 当前挂牌价：{price:g} 元",
        f"- 邮费：{result.get('shipping_note', '待确认')}",
        "- 商品状态：待实时复核",
        f"- 成色与配件：{record.get('condition', '未知')}；{record.get('notes', '')}".rstrip("；"),
        f"- 市场样本：{stats.get('sample_count', 0)} 条，跨度 {stats.get('time_span_days', 0)} 天",
        f"- 市场参考价：P25 {p25:g} 元，P75 {p75:g} 元",
        f"- 估算合理成交价：{estimated_low}–{estimated_high} 元",
        "- 购买模式：可盈利转卖",
        f"- 全包买入成本：{result.get('landed_buy_cost', price):g} 元",
        f"- 预计卖出价：{exit_price:g} 元（置信度：{result.get('exit_confidence', 'unknown')}）",
        f"- 卖出成本：快递 {result.get('shipping_out', 0):g} 元 + 包材 {result.get('packaging', 0):g} 元 + 平台费 {result.get('platform_fee', 0):g} 元",
        f"- 风险准备金：{result.get('risk_reserve', 0):g} 元",
        f"- 预计净利润：{result.get('expected_profit', 0):g} 元",
        f"- 预计 ROI：{result.get('roi_pct', 0):g}%",
        f"- 首报：{first_offer} 元（待复核后调整）",
        f"- 目标价：{target_price} 元",
        f"- 最高可接受价：{max(0, max_buy_price):g} 元",
        "- 谈价状态：draft",
        f"- 最后检查时间：{now}",
        "- 最后我方消息：无",
        "- 最后卖家消息：无",
        "- 最后卖家消息摘要：无",
        "- 最后卖家消息哈希：无",
        "- 下次跟进：-",
        "- 卖家承诺：无",
        f"- 风险事项：{'；'.join(record.get('flags') or []) or '待实时复核'}",
        "- 页面截图：无",
        f"- 触发分数：{score:g}",
        f"- 触发原因：{'；'.join(reasons)}",
    ]
    body = [
        "",
        "## 触发评审",
        "",
        f"- 市场门槛：{stats.get('status', 'insufficient')}",
        f"- 购买模式：{result.get('mode', '可盈利转卖')}",
        f"- 预计净利润：{result.get('expected_profit', 0):g} 元",
        f"- 预计 ROI：{result.get('roi_pct', 0):g}%",
        f"- 退出价基准：{result.get('exit_source', 'unknown')}，置信度 {result.get('exit_confidence', 'unknown')}",
        f"- 原始标题：{record.get('title', '')}",
        "",
        "## 只读复核",
        "",
        "- 待采集 Agent 实时确认商品、价格、卖家、成色、功能和风险。",
        "",
        "## 话术",
        "",
        "- 开场：待实时复核后生成。",
        "- 首轮报价：以记录中的首报为起点，结合运输和货况调整。",
        "- 让步顺序：最多两次，不高于最高可接受价。",
        "",
        "## 消息时间线",
        "",
        "| 时间 | 发送方 | 内容或事件 |",
        "| --- | --- | --- |",
        f"| {now} | 系统 | 采集后评审触发 draft |",
        "",
    ]
    return title + "\n".join(fields) + "\n" + "\n".join(body)


def evaluate(day: str, trigger: dict) -> dict:
    market_path = MARKET_DIR / f"{day}.json"
    if not market_path.exists():
        raise FileNotFoundError(f"找不到市场数据：{market_path}")
    market = load_json(market_path)
    pricing = load_pricing()
    stats_by_model = load_stats()
    negotiations = read_negotiations()
    policy_config = acquisition_policy.load_policy_config()

    existing_ids = {str(item["id"]) for item in negotiations}
    active = [
        item for item in negotiations
        if item["status"] in {"awaiting_reply", "negotiating", "awaiting_user", "handoff"}
    ]
    active_by_tier = Counter()
    active_by_model = Counter()
    blocked_models = {
        str(item["model"])
        for item in negotiations
        if item["status"] in {"handoff", "completed"}
    }

    for item in active:
        pricing_item = price_item_for_model(str(item["model"]), pricing)
        tier = str((pricing_item or {}).get("risk_tier", "high"))
        active_by_tier[tier] += 1
        active_by_model[str(item["model"])] += 1
    decisions = []
    for record in market.get("records", []):
        listing_id = str(record.get("id", ""))
        model = str(record.get("model", ""))
        pricing_item = price_item_for_model(model, pricing)
        if not pricing_item:
            decisions.append({"id": listing_id, "model": model, "action": "watch", "reason": "未配置谈价门槛"})
            continue
        stats = stats_by_model.get(str(pricing_item.get("model")))
        if not stats or stats.get("status") != "ready":
            decisions.append({"id": listing_id, "model": model, "action": "watch", "reason": "样本或观察期未达门槛"})
            continue
        if listing_id in existing_ids:
            decisions.append({"id": listing_id, "model": model, "action": "existing", "reason": "已有谈价或归档记录"})
            continue
        if model in blocked_models:
            decisions.append({"id": listing_id, "model": model, "action": "reject", "reason": "已购买同型号，停止重复谈价"})
            continue
        rejected = reject_reason(record, trigger)
        if rejected:
            decisions.append({"id": listing_id, "model": model, "action": "reject", "reason": rejected})
            continue

        result = acquisition_policy.evaluate(record, stats, policy_config)
        if not result.get("eligible"):
            decisions.append(
                {
                    "id": listing_id,
                    "model": model,
                    "action": "watch",
                    "reason": result.get("reason", "未达到盈利门槛"),
                    "policy": result,
                }
            )
            continue

        min_confidence = str(
            acquisition_policy.mode_config(policy_config).get(
                "auto_trigger_min_confidence",
                "high",
            )
        )
        if result.get("exit_confidence") == "low" and min_confidence not in {"low", "any"}:
            decisions.append(
                {
                    "id": listing_id,
                    "model": model,
                    "action": "watch",
                    "reason": f"退出价仅估算（低置信度），需人工复核；{result['reason']}",
                    "policy": result,
                }
            )
            continue

        score, reasons = priority_score(record, result)
        tier = str(pricing_item.get("risk_tier", "high"))
        tier_limit = int(trigger["active_slots"].get(tier, 1))
        model_limit = int(trigger["same_model_slots"].get(tier, 1))
        has_capacity = (
            active_by_tier[tier] < tier_limit
            and active_by_model[model] < model_limit
        )
        decisions.append(
            {
                "id": listing_id,
                "model": model,
                "price": price,
                "score": score,
                "risk_tier": tier,
                "action": "immediate" if has_capacity else "backup",
                "reason": "；".join(reasons) if has_capacity else "满足谈价条件但名额已满",
                "record": record,
                "stats": stats,
                "pricing_item": pricing_item,
                "policy": result,
            }
        )

    immediate = sorted(
        [item for item in decisions if item["action"] == "immediate"],
        key=lambda item: float(item.get("score", 0)),
        reverse=True,
    )
    selected = []
    for item in immediate:
        tier = item["risk_tier"]
        model = item["model"]
        tier_limit = int(trigger["active_slots"].get(tier, 1))
        model_limit = int(trigger["same_model_slots"].get(tier, 1))
        if active_by_tier[tier] >= tier_limit or active_by_model[model] >= model_limit:
            item["action"] = "backup"
            item["reason"] = "满足谈价条件但名额已满"
            continue
        selected.append(item)
        active_by_tier[tier] += 1
        active_by_model[model] += 1

    for item in decisions:
        item.pop("record", None)
        item.pop("stats", None)
        item.pop("pricing_item", None)
    return {
        "date": day,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": acquisition_policy.active_mode(policy_config),
        "active_count": len(active),
        "decisions": decisions,
        "immediate_ids": [item["id"] for item in selected],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Trove 谈价触发评审")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    trigger = load_json(CONFIG_PATH)
    if not trigger.get("enabled", False) and not args.dry_run:
        print("谈价触发器未启用")
        return 0

    result = evaluate(args.date, trigger)
    immediate_ids = set(result["immediate_ids"])
    selected_by_id = {
        item["id"]: item for item in result["decisions"]
        if item["id"] in immediate_ids
    }
    market = load_json(MARKET_DIR / f"{args.date}.json")
    by_id = {str(item.get("id", "")): item for item in market.get("records", [])}
    pricing = load_pricing()
    stats_by_model = load_stats()

    created = []
    if not args.dry_run:
        DECISION_DIR.mkdir(parents=True, exist_ok=True)
        for listing_id in result["immediate_ids"]:
            decision = selected_by_id[listing_id]
            record = by_id[listing_id]
            item = price_item_for_model(record["model"], pricing)
            stats = stats_by_model[item["model"]]
            path = draft_path(args.date, record)
            if not path.exists():
                path.write_text(
                    draft_text(record, stats, item, trigger, decision),
                    encoding="utf-8",
                )
                created.append(str(path))
        write_json(DECISION_DIR / f"{args.date}.json", result)

    output = {**result, "created": created, "dry_run": args.dry_run}
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(
            f"{args.date}: {len(result['decisions'])} 条候选，"
            f"立即触发 {len(result['immediate_ids'])} 条，已建 draft {len(created)} 条"
        )
        for item in result["decisions"]:
            print(
                f"- {item['id']} | {item['model']} | {item['action']} | {item['reason']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
