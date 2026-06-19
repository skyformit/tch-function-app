import unittest
from datetime import date
from unittest.mock import patch

from app.use_cases.general_bot import _route_trade_license
from app.use_cases.trade_license_expiry import TradeLicenseExpiryDecision, classify_trade_license_expiry
from app.use_cases.trade_license_routing import TradeLicenseWorkflowRoute


class TradeLicenseRoutingTest(unittest.TestCase):
    def test_expired_license_is_detected(self) -> None:
        decision = classify_trade_license_expiry("Trade License Expiry Date: 14 May 2017", today=date(2026, 6, 19))
        self.assertIsNotNone(decision)
        self.assertEqual(decision.status, "expired")

    def test_license_within_60_days_requests_renewal(self) -> None:
        decision = classify_trade_license_expiry("Expiry Date: 10 Aug 2026", today=date(2026, 6, 19))
        self.assertIsNotNone(decision)
        self.assertEqual(decision.status, "renewal_due")

    def test_general_bot_routes_expired_license_to_approval_workflow(self) -> None:
        payload = {"ok": True, "text": "Trade License Expiry Date: 14 May 2017", "agent": {"name": "general"}}
        body = {"text": "my trade license is 526422", "conversation_id": "conv-1", "user_id": "user-1"}
        route = TradeLicenseWorkflowRoute(
            decision=TradeLicenseExpiryDecision(date(2017, 5, 14), -3330, "expired"),
            workflow_name="TCG-Vendor-Approval-Workflow",
            workflow_url="https://example.com/approval",
            message="Trade license expired on 14 May 2017. Starting TCG-Vendor-Approval-Workflow.",
        )

        with patch("app.use_cases.general_bot.classify_trade_license_routing", return_value=route), patch("app.use_cases.general_bot.invoke_activity_workflow", return_value=(200, {"ok": True, "text": "started"})):
            status_code, routed = _route_trade_license(payload, body)

        self.assertEqual(status_code, 200)
        self.assertFalse(routed["ok"])
        self.assertEqual(routed["status"], "expired")
        self.assertTrue(routed["workflow_started"])
        self.assertEqual(routed["routing"]["workflow_name"], "TCG-Vendor-Approval-Workflow")
        self.assertEqual(routed["error"]["code"], "trade_license_expired")

    def test_general_bot_routes_renewal_due_license_to_renewal_workflow(self) -> None:
        payload = {"ok": True, "text": "Trade License Expiry Date: 10 Aug 2026", "agent": {"name": "general"}}
        body = {"text": "my trade license is 526422", "conversation_id": "conv-1", "user_id": "user-1"}
        route = TradeLicenseWorkflowRoute(
            decision=TradeLicenseExpiryDecision(date(2026, 8, 10), 52, "renewal_due"),
            workflow_name="Renewal-Vendor-Approval-Workflow",
            workflow_url="https://example.com/renewal",
            message="Trade license expires on 10 Aug 2026 (52 days left). Starting Renewal-Vendor-Approval-Workflow.",
        )

        with patch("app.use_cases.general_bot.classify_trade_license_routing", return_value=route), patch("app.use_cases.general_bot.invoke_activity_workflow", return_value=(200, {"ok": True, "text": "started"})):
            status_code, routed = _route_trade_license(payload, body)

        self.assertEqual(status_code, 200)
        self.assertEqual(routed["status"], "renewal_due")
        self.assertTrue(routed["workflow_started"])
        self.assertEqual(routed["routing"]["workflow_name"], "Renewal-Vendor-Approval-Workflow")
        self.assertIn("warning", routed)


if __name__ == "__main__":
    unittest.main()
