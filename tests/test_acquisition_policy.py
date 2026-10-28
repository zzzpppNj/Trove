import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import acquisition_policy as policy  # noqa: E402


CONFIG = {
    "version": 1,
    "active_mode": "resale_profit",
    "modes": {
        "resale_profit": {
            "min_net_profit": 20,
            "min_roi_pct": 15,
            "risk_reserve_pct": 10,
            "risk_reserve_min": 10,
            "platform_fee_pct": 0,
            "listing_estimate_pct": 85,
            "min_sold_comps": 5,
            "allow_estimated_exit": True,
        }
    },
    "cost_profiles": {
        "图书绘本游戏卡带": {
            "shipping_out": 10,
            "packaging": 2,
            "inbound_shipping_default": 10,
        }
    },
}


class ResaleProfitPolicyTest(unittest.TestCase):
    def test_exit_reference_prefers_sold_comps(self):
        stats = {
            "personal_median": 200,
            "sold_sample_count": 6,
            "sold_p25": 150,
        }
        exit_price, confidence, source = policy.exit_reference(
            stats, CONFIG["modes"]["resale_profit"]
        )
        self.assertEqual(exit_price, 150)
        self.assertEqual(confidence, "high")
        self.assertEqual(source, "sold_p25")

    def test_exit_reference_falls_back_to_listing_estimate(self):
        stats = {
            "personal_median": 200,
            "sold_sample_count": 0,
        }
        exit_price, confidence, source = policy.exit_reference(
            stats, CONFIG["modes"]["resale_profit"]
        )
        self.assertEqual(exit_price, 170)
        self.assertEqual(confidence, "low")
        self.assertEqual(source, "listing_median_estimate")

    def test_eligible_listing_reports_profit_and_max_price(self):
        record = {
            "category": "图书绘本游戏卡带",
            "listing_price": 120,
            "title": "包邮",
            "notes": "",
        }
        stats = {
            "personal_median": 200,
            "sold_sample_count": 0,
        }
        result = policy.evaluate(record, stats, CONFIG)
        self.assertTrue(result["eligible"], result)
        self.assertEqual(result["landed_buy_cost"], 120)
        self.assertGreater(result["expected_profit"], 0)
        self.assertGreater(result["max_buy_price"], 0)
        self.assertEqual(result["mode"], "resale_profit")

    def test_ineligible_listing_has_reason(self):
        record = {
            "category": "图书绘本游戏卡带",
            "listing_price": 170,
            "title": "不包邮",
            "notes": "",
        }
        stats = {
            "personal_median": 190,
            "sold_sample_count": 0,
        }
        result = policy.evaluate(record, stats, CONFIG)
        self.assertFalse(result["eligible"])
        self.assertIn("未达门槛", result["reason"])


if __name__ == "__main__":
    unittest.main()
