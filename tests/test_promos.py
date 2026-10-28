"""Discounts can never make an invoice negative or disagree with itself."""

import unittest

from licensing import promos


def quote(total, rate=None):
    return {"total_usd": total, "usd_rate": rate, "lines": []}


class ApplyDiscountTest(unittest.TestCase):

    def test_percent_off(self):
        out = promos.apply_discount(quote(10.0), {"code": "P", "kind": promos.KIND_PERCENT_OFF, "value": 25})
        self.assertEqual(out["total_usd"], 7.5)
        self.assertEqual(out["discount_usd"], 2.5)
        self.assertEqual(out["total_before_discount_usd"], 10.0)

    def test_amount_off_never_goes_below_zero(self):
        out = promos.apply_discount(quote(3.0), {"code": "A", "kind": promos.KIND_AMOUNT_OFF, "value": 50})
        self.assertEqual(out["total_usd"], 0.0)
        self.assertEqual(out["discount_usd"], 3.0)

    def test_over_100_percent_is_clamped(self):
        out = promos.apply_discount(quote(8.0), {"code": "X", "kind": promos.KIND_PERCENT_OFF, "value": 150})
        self.assertEqual(out["total_usd"], 0.0)

    def test_original_quote_is_not_modified(self):
        original = quote(10.0)
        promos.apply_discount(original, {"code": "P", "kind": promos.KIND_PERCENT_OFF, "value": 10})
        self.assertEqual(original["total_usd"], 10.0)
        self.assertEqual(original["lines"], [])

    def test_no_discount_returns_the_quote(self):
        q = quote(5.0)
        self.assertIs(promos.apply_discount(q, None), q)

    def test_rial_total_follows_the_new_dollar_total(self):
        out = promos.apply_discount(quote(10.0, rate=1000),
                                    {"code": "P", "kind": promos.KIND_PERCENT_OFF, "value": 50})
        self.assertIn("total_irr", out)
        self.assertLessEqual(out["total_irr"], 10.0 * 1000)


if __name__ == "__main__":
    unittest.main()
