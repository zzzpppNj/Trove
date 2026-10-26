#!/usr/bin/env python3
"""周度更新 config/pricing.json 的参考价与好价线。

规则：
- 读取 records/market/YYYY-MM-DD.json 最近 30 天数据。
- 每个型号优先用个人卖家样本；个人样本少于 3 条时退回全体样本。
- 达到门槛（风险档对应的样本数与观察天数）才更新：
    reference_price = [P25, P75]（上限 1000 元）
    good_price_line = P25
- 未达门槛则保持原值不变。
"""

import datetime
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "records" / "market"
PRICING = ROOT / "config" / "pricing.json"

THRESHOLDS = {
    "safe": {"samples": 15, "days": 7},
    "medium": {"samples": 20, "days": 14},
    "high": {"samples": 30, "days": 21},
}
WINDOW_DAYS = 30


def load_records():
    today = datetime.date.today()
    rows = []
    for f in sorted(MARKET.glob("*.json")):
        if len(f.stem) != 10:
            continue
        try:
            day = datetime.date.fromisoformat(f.stem)
        except ValueError:
            continue
        if (today - day).days > WINDOW_DAYS:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.extend([r for r in data.get("records", []) if isinstance(r, dict)])
    return rows


def quartile(xs, p):
    xs = sorted(xs)
    n = len(xs)
    k = (n - 1) * p
    lo = int(k)
    hi = min(lo + 1, n - 1)
    frac = k - lo
    return xs[lo] + (xs[hi] - xs[lo]) * frac


def span_days(rows):
    dates = set()
    for r in rows:
        rid = r.get("id", "")
        if isinstance(rid, str) and len(rid) >= 10:
            try:
                dates.add(datetime.date.fromisoformat(rid[:10]))
            except ValueError:
                pass
    if not dates:
        return 0
    return (max(dates) - min(dates)).days + 1


def main():
    rows = load_records()
    pricing = json.loads(PRICING.read_text(encoding="utf-8"))
    span = span_days(rows)
    changed = False

    for item in pricing.get("items", []):
        names = item.get("aliases") or [item.get("model")]
        tier = item.get("risk_tier", "safe")
        need = THRESHOLDS.get(tier, THRESHOLDS["safe"])

        personal = [
            r.get("listing_price") for r in rows
            if r.get("model") in names and r.get("seller_type") == "personal"
            and isinstance(r.get("listing_price"), (int, float))
        ]
        overall = [
            r.get("listing_price") for r in rows
            if r.get("model") in names and isinstance(r.get("listing_price"), (int, float))
        ]
        src = personal if len(personal) >= 3 else overall
        if len(src) < need["samples"] or span < need["days"]:
            continue

        p25 = round(quartile(src, 0.25))
        p75 = round(quartile(src, 0.75))
        p25 = min(p25, 1000)
        p75 = min(max(p75, p25), 1000)
        item["reference_price"] = {"min": p25, "max": p75}
        item["good_price_line"] = p25
        item["notes"] = f"个人样本{len(personal)}/全体{len(overall)}，跨度{span}天"
        changed = True

    if changed:
        pricing["updated_at"] = datetime.date.today().isoformat()
        PRICING.write_text(
            json.dumps(pricing, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"changed={changed} updated_at={pricing.get('updated_at')}")


if __name__ == "__main__":
    main()
