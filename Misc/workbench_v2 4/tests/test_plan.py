import unittest
from app.core.plan import plan_status as ps


class PlanTests(unittest.TestCase):
    def test_statuses(self):
        self.assertEqual(ps(100, 90, 130, 85)["status"], "on_plan")
        self.assertEqual(ps(86, 90, 130, 85)["status"], "near_stop")      # within 3% above stop (also in buy zone)
        self.assertEqual(ps(86, 90, 130, 85)["flags"], ["near_stop", "buy_zone"])
        self.assertEqual(ps(84, 90, 130, 85)["status"], "stop_breached")
        self.assertEqual(ps(127, 90, 130, 85)["status"], "near_target")
        self.assertEqual(ps(131, None, 130, None)["status"], "target_reached")
        self.assertEqual(ps(88, 90, None, None)["status"], "buy_zone")

    def test_distances_and_empty(self):
        r = ps(100, None, 120, 90)
        self.assertEqual((r["to_target"], r["to_stop"], r["to_buy"]), (0.2, -0.1, None))
        self.assertIsNone(ps(None, 1, 2, 3)); self.assertIsNone(ps(0, 1, 2, 3))


if __name__ == "__main__":
    unittest.main()
