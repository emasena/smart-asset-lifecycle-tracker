import sys
import unittest
from decimal import Decimal
from pathlib import Path


ASSET_API_DIR = Path(__file__).resolve().parents[1] / "asset_api"
sys.path.insert(0, str(ASSET_API_DIR))

from depreciation import DepreciationError, calculate_depreciation  # noqa: E402


class DepreciationTests(unittest.TestCase):
    def test_asset_placed_in_service_today_has_no_depreciation(self):
        result = calculate_depreciation(
            purchase_value="1200.00",
            salvage_value="200.00",
            useful_life_months=60,
            in_service_date="2026-09-29",
            as_of_date="2026-09-29",
        )

        self.assertEqual(result["elapsedMonths"], 0)
        self.assertEqual(
            result["accumulatedDepreciation"],
            Decimal("0.00"),
        )
        self.assertEqual(
            result["currentBookValue"],
            Decimal("1200.00"),
        )
        self.assertEqual(
            result["usefulLifeConsumedPercent"],
            Decimal("0.00"),
        )

    def test_asset_halfway_through_useful_life(self):
        result = calculate_depreciation(
            purchase_value="1400.00",
            salvage_value="200.00",
            useful_life_months=24,
            in_service_date="2025-09-29",
            as_of_date="2026-09-29",
        )

        self.assertEqual(result["elapsedMonths"], 12)
        self.assertEqual(
            result["annualDepreciation"],
            Decimal("600.00"),
        )
        self.assertEqual(
            result["accumulatedDepreciation"],
            Decimal("600.00"),
        )
        self.assertEqual(
            result["currentBookValue"],
            Decimal("800.00"),
        )
        self.assertEqual(
            result["usefulLifeConsumedPercent"],
            Decimal("50.00"),
        )

    def test_asset_older_than_useful_life_stops_at_salvage_value(self):
        result = calculate_depreciation(
            purchase_value="2000.00",
            salvage_value="500.00",
            useful_life_months=36,
            in_service_date="2020-01-15",
            as_of_date="2026-09-29",
        )

        self.assertEqual(
            result["accumulatedDepreciation"],
            Decimal("1500.00"),
        )
        self.assertEqual(
            result["currentBookValue"],
            Decimal("500.00"),
        )
        self.assertEqual(
            result["usefulLifeConsumedPercent"],
            Decimal("100.00"),
        )

    def test_salvage_value_cannot_exceed_purchase_value(self):
        with self.assertRaisesRegex(
            DepreciationError,
            "salvageValue cannot exceed purchaseValue",
        ):
            calculate_depreciation(
                purchase_value="500.00",
                salvage_value="600.00",
                useful_life_months=36,
                in_service_date="2026-01-01",
                as_of_date="2026-09-29",
            )

    def test_useful_life_must_be_positive_integer(self):
        with self.assertRaisesRegex(
            DepreciationError,
            "usefulLifeMonths must be a positive integer",
        ):
            calculate_depreciation(
                purchase_value="500.00",
                salvage_value="100.00",
                useful_life_months=0,
                in_service_date="2026-01-01",
                as_of_date="2026-09-29",
            )

    def test_future_in_service_date_has_no_depreciation(self):
        result = calculate_depreciation(
            purchase_value="1500.00",
            salvage_value="300.00",
            useful_life_months=48,
            in_service_date="2027-01-01",
            as_of_date="2026-09-29",
        )

        self.assertEqual(result["elapsedMonths"], 0)
        self.assertEqual(
            result["accumulatedDepreciation"],
            Decimal("0.00"),
        )
        self.assertEqual(
            result["currentBookValue"],
            Decimal("1500.00"),
        )

    def test_month_is_counted_only_after_monthly_anniversary(self):
        before_anniversary = calculate_depreciation(
            purchase_value="1300.00",
            salvage_value="100.00",
            useful_life_months=12,
            in_service_date="2026-01-31",
            as_of_date="2026-02-27",
        )
        after_anniversary = calculate_depreciation(
            purchase_value="1300.00",
            salvage_value="100.00",
            useful_life_months=12,
            in_service_date="2026-01-31",
            as_of_date="2026-02-28",
        )

        self.assertEqual(before_anniversary["elapsedMonths"], 0)
        self.assertEqual(after_anniversary["elapsedMonths"], 1)

    def test_replacement_date_handles_end_of_month(self):
        result = calculate_depreciation(
            purchase_value="1000.00",
            salvage_value="100.00",
            useful_life_months=1,
            in_service_date="2026-01-31",
            as_of_date="2026-01-31",
        )

        self.assertEqual(
            result["estimatedReplacementDate"],
            "2026-02-28",
        )


if __name__ == "__main__":
    unittest.main()
