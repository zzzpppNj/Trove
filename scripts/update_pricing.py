#!/usr/bin/env python3
"""周度更新 config/pricing.json 的参考价与好价线。

规则：
- 读取 records/market/YYYY-MM-DD.json 最近 30 天数据。
- 每个型号优先用个人卖家样本；个人样本少于 3 条时退回全体样本。
- 达到门槛（风险档对应的样本数与观察天数）才更新：
    reference_price = [P25, P75]（上限 1000 元）
    good_price_line = P25
- 额外从 records 中的已售样本聚合 sold_median / sold_p25 等退出价指标，
  写回 records/market/stats/ 下对应的聚合文件（仅当存在已售样本时更新）。
- 未达门槛则保持原值不变。
"""

import datetime
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "records" / "market"
PRICING = ROOT / "config" / "pricing.json"
STATS_DIR = MARKET / "stats"

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


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    if n % 2 == 1:
        return xs[n // 2]
    return (xs[n // 2 - 1] + xs[n // 2]) / 2


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def span_days(rows):
    dates = set()
    for r in rows:
        raw = r.get("listed_at") or r.get("sold_at")
        if not isinstance(raw, str) or len(raw) < 10 or "-" not in raw:
            continue
        try:
            dates.add(datetime.date.fromisoformat(raw[:10]))
        except ValueError:
            continue
    if not dates:
        return 0
    return (max(dates) - min(dates)).days + 1


def sold_metrics(rows: list[dict]) -> dict:
    prices = [
        r.get("sold_price")
        for r in rows
        if isinstance(r.get("sold_price"), (int, float))
        and r.get("sold") is not False
    ]
    dates = set()
    for r in rows:
        if not isinstance(r.get("sold_price"), (int, float)):
            continue
        if r.get("sold") is False:
            continue
        raw = r.get("sold_at")
        if isinstance(raw, str) and len(raw) >= 10:
            try:
                dates.add(datetime.date.fromisoformat(raw[:10]))
            except ValueError:
                pass
    sold_count = len(prices)
    return {
        "sold_sample_count": sold_count,
        "sold_median": round(median(prices), 2) if prices else None,
        "sold_p25": round(quartile(prices, 0.25), 2) if prices else None,
        "sold_p75": round(quartile(prices, 0.75), 2) if prices else None,
        "sold_span_days": (max(dates) - min(dates)).days + 1 if dates else None,
    }


def stats_file_for_model(names: list[str]) -> Path | None:
    if not STATS_DIR.is_dir():
        return None
    for path in sorted(STATS_DIR.glob("*.json")):
        try:
            item = load_json(path)
        except Exception:
            continue
        model = str(item.get("model", ""))
        if model in names:
            return path
    return None


def main():
    rows = load_records()
    pricing = load_json(PRICING)
    changed = False
    stats_changed = False

    for item in pricing.get("items", []):
        names = list(dict.fromkeys([item.get("model"), *(item.get("aliases") or [])]))
        model_rows = [r for r in rows if r.get("model") in names]
        tier = item.get("risk_tier", "safe")
        need = THRESHOLDS.get(tier, THRESHOLDS["safe"])

        personal = [
            r.get("listing_price") for r in model_rows
            if r.get("model") in names and r.get("seller_type") == "personal"
            and isinstance(r.get("listing_price"), (int, float))
        ]
        overall = [
            r.get("listing_price") for r in model_rows
            if r.get("model") in names and isinstance(r.get("listing_price"), (int, float))
        ]
        src = personal if len(personal) >= 3 else overall
        model_span = span_days(model_rows)
        if len(src) < need["samples"] or model_span < need["days"]:
            stats_path = stats_file_for_model(names)
            if stats_path is not None:
                sold = sold_metrics(model_rows)
                if sold["sold_sample_count"]:
                    stats_item = load_json(stats_path)
                    stats_item.update(sold)
                    write_json(stats_path, stats_item)
                    stats_changed = True
            continue

        p25 = round(quartile(src, 0.25))
        p75 = round(quartile(src, 0.75))
        p25 = min(p25, 1000)
        p75 = min(max(p75, p25), 1000)
        item["reference_price"] = {"min": p25, "max": p75}
        item["good_price_line"] = p25
        item["notes"] = f"个人样本{len(personal)}/全体{len(overall)}，跨度{model_span}天"
        changed = True

        stats_path = stats_file_for_model(names)
        if stats_path is not None:
            stats_item = load_json(stats_path)
            stats_item["sample_count"] = len(src)
            stats_item["time_span_days"] = model_span
            stats_item["personal_median"] = round(median(personal), 2) if personal else None
            stats_item["overall_median"] = round(median(overall), 2) if overall else None
            stats_item["p25"] = p25
            stats_item["p75"] = p75
            stats_item["fair_price_range"] = [p25, p75]
            sold = sold_metrics(model_rows)
            if sold["sold_sample_count"]:
                stats_item.update(sold)
            write_json(stats_path, stats_item)
            stats_changed = True

    if changed:
        pricing["updated_at"] = datetime.date.today().isoformat()
        write_json(PRICING, pricing)
    print(
        f"changed={changed} stats_changed={stats_changed} "
        f"updated_at={pricing.get('updated_at')}"
    )


if __name__ == "__main__":
    main()
