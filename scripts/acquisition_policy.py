#!/usr/bin/env python3
"""Acquisition policy: pluggable buy decision logic.

The policy module is intentionally free of file-system side effects. It turns a
market record plus aggregate stats into one deterministic decision. New modes
(for example ``personal_use``) can be registered later without changing the
trigger script.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = ROOT / "config" / "acquisition_policy.json"
DEFAULT_COST_PROFILE = {
    "shipping_out": 15,
    "packaging": 5,
    "inbound_shipping_default": 15,
}
EPSILON = 0.005


def load_policy_config(path: Path | None = None) -> dict:
    config_path = path or DEFAULT_POLICY_PATH
    config = json.loads(config_path.read_text(encoding="utf-8"))
    mode = str(config.get("active_mode", ""))
    modes = config.get("modes") or {}
    if mode not in modes:
        raise ValueError(f"未知购买模式：{mode or '<empty>'}")
    return config


def active_mode(config: dict) -> str:
    return str(config.get("active_mode", ""))


def mode_config(config: dict) -> dict:
    return dict((config.get("modes") or {}).get(active_mode(config)) or {})


def _number(value: object, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _round(value: float, digits: int = 2) -> float:
    return round(value, digits)


def cost_profile(category: object, config: dict) -> dict:
    profiles = config.get("cost_profiles") or {}
    profile = profiles.get(str(category or "")) or DEFAULT_COST_PROFILE
    return {
        "shipping_out": float(profile.get("shipping_out", DEFAULT_COST_PROFILE["shipping_out"])),
        "packaging": float(profile.get("packaging", DEFAULT_COST_PROFILE["packaging"])),
        "inbound_shipping_default": float(
            profile.get(
                "inbound_shipping_default",
                DEFAULT_COST_PROFILE["inbound_shipping_default"],
            )
        ),
    }


def inbound_shipping(record: dict, profile: dict) -> tuple[float, str]:
    """Return (shipping_fee_in, source_description)."""
    text = f"{record.get('title', '')} {record.get('notes', '')}"
    explicit = record.get("shipping_included")
    extra = _number(record.get("shipping_cost_in"))
    default = float(profile["inbound_shipping_default"])

    if explicit is True:
        return 0.0, "卖家包邮"
    if explicit is False:
        if extra is not None:
            return max(0.0, extra), "邮费已标注"
        return default, f"不包邮，按默认 {default:g} 元估算"

    if "不包邮" in text or "邮费另" in text or "另需" in text:
        if extra is not None:
            return max(0.0, extra), "邮费已标注"
        return default, f"不包邮，按默认 {default:g} 元估算"
    if "包邮" in text:
        return 0.0, "描述标注包邮"
    return default, f"邮费未明示，按默认 {default:g} 元估算"


def exit_reference(stats: dict, policy: dict) -> tuple[float | None, str, str]:
    """Pick the most trustworthy exit price source.

    Returns (exit_price, confidence, source). Sold comps beat listing medians.
    """
    sold_count = int(stats.get("sold_sample_count") or 0)
    sold_p25 = _number(stats.get("sold_p25"))
    min_sold = int(policy.get("min_sold_comps", 5))
    if sold_count >= min_sold and sold_p25 is not None and sold_p25 > 0:
        return _round(sold_p25), "high", "sold_p25"

    allow_estimate = bool(policy.get("allow_estimated_exit", False))
    if allow_estimate:
        median = (
            _number(stats.get("personal_median"))
            or _number(stats.get("overall_median"))
            or _number(stats.get("median"))
        )
        if median is not None and median > 0:
            ratio = float(policy.get("listing_estimate_pct", 85)) / 100
            return _round(median * ratio), "low", "listing_median_estimate"
    return None, "none", ""


def _invalid(reason: str) -> dict:
    return {
        "mode": "resale_profit",
        "eligible": False,
        "reason": reason,
        "exit_confidence": "none",
    }


def evaluate_resale_profit(record: dict, stats: dict, config: dict) -> dict:
    policy = mode_config(config)
    profile = cost_profile(record.get("category"), config)
    listing_price = _number(record.get("listing_price"))
    if listing_price is None or listing_price < 0:
        return _invalid("挂牌价无效")

    shipping_in, shipping_note = inbound_shipping(record, profile)
    landed_buy_cost = _round(listing_price + shipping_in)

    exit_price, confidence, exit_source = exit_reference(stats, policy)
    if exit_price is None:
        return {
            **_invalid("无可用退出价基准（已售样本不足，且未允许用挂牌价估算）"),
            "landed_buy_cost": landed_buy_cost,
            "shipping_in": shipping_in,
            "shipping_note": shipping_note,
        }

    shipping_out = float(profile["shipping_out"])
    packaging = float(profile["packaging"])
    platform_fee = _round(exit_price * float(policy.get("platform_fee_pct", 0)) / 100)
    net_proceeds = _round(exit_price - shipping_out - packaging - platform_fee)

    risk_reserve = _round(
        max(
            float(policy.get("risk_reserve_min", 0)),
            exit_price * float(policy.get("risk_reserve_pct", 0)) / 100,
        )
    )
    expected_profit = _round(net_proceeds - landed_buy_cost - risk_reserve)
    roi_pct = _round(expected_profit / landed_buy_cost * 100) if landed_buy_cost > 0 else 0.0

    min_net_profit = float(policy.get("min_net_profit", 0))
    min_roi_pct = float(policy.get("min_roi_pct", 0))
    eligible = (
        expected_profit + EPSILON >= min_net_profit
        and roi_pct + EPSILON >= min_roi_pct
    )

    max_buy_landed = _round(net_proceeds - risk_reserve - min_net_profit)
    max_buy_price = _round(max_buy_landed - shipping_in)
    reason = (
        f"预计净利 {expected_profit:g} 元、ROI {roi_pct:g}%"
        if eligible
        else (
            f"预计净利 {expected_profit:g} 元、ROI {roi_pct:g}%，"
            f"未达门槛（净利 ≥ {min_net_profit:g} 元且 ROI ≥ {min_roi_pct:g}%）"
        )
    )

    return {
        "mode": "resale_profit",
        "eligible": eligible,
        "reason": reason,
        "listing_price": listing_price,
        "shipping_in": shipping_in,
        "shipping_note": shipping_note,
        "landed_buy_cost": landed_buy_cost,
        "expected_exit_price": exit_price,
        "exit_confidence": confidence,
        "exit_source": exit_source,
        "shipping_out": shipping_out,
        "packaging": packaging,
        "platform_fee": platform_fee,
        "net_proceeds": net_proceeds,
        "risk_reserve": risk_reserve,
        "expected_profit": expected_profit,
        "roi_pct": roi_pct,
        "max_buy_landed": max_buy_landed,
        "max_buy_price": max_buy_price,
        "min_net_profit": min_net_profit,
        "min_roi_pct": min_roi_pct,
    }


EVALUATORS: dict[str, Callable[[dict, dict, dict], dict]] = {
    "resale_profit": evaluate_resale_profit,
}


def evaluate(record: dict, stats: dict, config: dict) -> dict:
    evaluator = EVALUATORS.get(active_mode(config))
    if evaluator is None:
        raise ValueError(f"未实现的购买模式：{active_mode(config)}")
    return evaluator(record, stats, config)
