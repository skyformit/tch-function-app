import asyncio
import json
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from app.use_cases.general_bot import invoke_general_bot, _split_lookup_text
from app.use_cases.trade_license_expiry import TradeLicenseExpiryDecision
from app.use_cases.trade_license_routing import TradeLicenseWorkflowRoute


class _FakeRequest:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self):
        return self._body


class _FakeTbmsResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def get_body(self):
        return json.dumps(self._payload).encode()


class _FakeTextTbmsResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class GeneralBotLookupTest(unittest.TestCase):
    def test_non_lookup_text_returns_llm_source(self) -> None:
        request = _FakeRequest({"text": "Please summarize the latest vendor changes."})

        with patch("app.use_cases.general_bot._lookup_response", return_value=None), patch(
            "app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)
        ), patch("app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM answer"}))):
            response = asyncio.run(invoke_general_bot(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["source"], "llm")
        self.assertEqual(payload["origin"], "llm")
        self.assertEqual(payload["source_type"], "llm")

    def test_company_name_goes_to_tbms_lookup(self) -> None:
        request = _FakeRequest({"text": "Abdul Jaleel Al Saadi Trading LLC"})

        fake_tbms_response = _FakeTbmsResponse({"ok": True, "data": {"results": []}, "status_code": 200})
        with patch("app.use_cases.general_bot._call_tbms_api", return_value=fake_tbms_response) as call_tbms, patch(
            "app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock()
        ) as invoke_workflow:
            response = asyncio.run(invoke_general_bot(request))

        call_tbms.assert_called_once()
        invoke_workflow.assert_not_called()
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source"], "tbms")
        self.assertEqual(payload["origin"], "tbms")
        self.assertEqual(payload["source_type"], "tbms")
        self.assertIn("data", payload)

    def test_mixed_company_and_license_tries_both_then_license_only(self) -> None:
        request = _FakeRequest({"text": "Abdul Jaleel Al Saadi Trading LLC 526422"})

        responses = [
            _FakeTbmsResponse({"ok": True, "data": {"results": []}, "status_code": 200}),
            _FakeTbmsResponse({"ok": True, "data": {"results": [{"vendorName": "Abdul Jaleel Al Saadi Trading LLC"}]}, "status_code": 200}),
        ]

        with patch("app.use_cases.general_bot._call_tbms_api", side_effect=responses) as call_tbms:
            response = asyncio.run(invoke_general_bot(request))

        self.assertEqual(call_tbms.call_count, 2)
        first_call_payload = call_tbms.call_args_list[0].args[1]
        second_call_payload = call_tbms.call_args_list[1].args[1]
        self.assertEqual(first_call_payload["vendorName"], "Abdul Jaleel Al Saadi Trading LLC")
        self.assertEqual(first_call_payload["licenseNo"], "526422")
        self.assertEqual(second_call_payload["vendorName"], "")
        self.assertEqual(second_call_payload["licenseNo"], "526422")
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source"], "tbms")
        self.assertEqual(payload["origin"], "tbms")
        self.assertEqual(payload["source_type"], "tbms")

    def test_labeled_company_and_license_are_split_correctly(self) -> None:
        company_text, license_number = _split_lookup_text("my license is 526422 and company Abdul Jaleel Al Saadi Trading LLC")

        self.assertEqual(company_text, "Abdul Jaleel Al Saadi Trading LLC")
        self.assertEqual(license_number, "526422")

    def test_alphanumeric_license_and_company_are_split_correctly(self) -> None:
        company_text, license_number = _split_lookup_text("Abdul Jaleel Al Saadi Trading LLC CN-1067688")

        self.assertEqual(company_text, "Abdul Jaleel Al Saadi Trading LLC")
        self.assertEqual(license_number, "CN-1067688")

    def test_trade_license_label_only_returns_license_without_company(self) -> None:
        company_text, license_number = _split_lookup_text("trade license no 526422")

        self.assertEqual(company_text, "")
        self.assertEqual(license_number, "526422")

    def test_vendor_name_label_only_returns_company_without_license(self) -> None:
        company_text, license_number = _split_lookup_text("vendor name Abdul Jaleel Al Saadi Trading LLC")

        self.assertEqual(company_text, "Abdul Jaleel Al Saadi Trading LLC")
        self.assertIsNone(license_number)

    def test_trade_license_number_goes_to_tbms_lookup(self) -> None:
        request = _FakeRequest({"text": "526422"})

        fake_tbms_response = _FakeTbmsResponse({"ok": True, "data": {"results": []}, "status_code": 200})
        with patch("app.use_cases.general_bot._call_tbms_api", return_value=fake_tbms_response) as call_tbms:
            response = asyncio.run(invoke_general_bot(request))

        call_tbms.assert_called_once()
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertTrue(payload["ok"])

    def test_tbms_parse_error_reports_body_shape(self) -> None:
        from app.use_cases.general_bot import _tbms_http_response_to_payload

        payload = _tbms_http_response_to_payload(_FakeTextTbmsResponse("not-json", 502))
        self.assertEqual(payload["error"]["code"], "response_parse_error")
        self.assertEqual(payload["error"]["body_type"], "str")
        self.assertEqual(payload["error"]["status_code"], 502)

    def test_greeting_prefixed_company_name_strips_greeting_before_lookup(self) -> None:
        request = _FakeRequest({"text": "hello Abdul Jaleel Al Saadi Trading LLC"})

        fake_tbms_response = _FakeTbmsResponse({"ok": True, "data": {"results": [{"vendorName": "Abdul Jaleel Al Saadi Trading LLC"}]}, "status_code": 200})
        with patch("app.use_cases.general_bot._call_tbms_api", return_value=fake_tbms_response) as call_tbms:
            response = asyncio.run(invoke_general_bot(request))

        call_tbms.assert_called_once()
        payload_sent = call_tbms.call_args.args[1]
        self.assertEqual(payload_sent["vendorName"], "Abdul Jaleel Al Saadi Trading LLC")
        self.assertEqual(payload_sent["licenseNo"], "")
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertTrue(payload["ok"])

    def test_person_name_requests_clarification(self) -> None:
        request = _FakeRequest({"text": "Abdul Jaleel Al Saadi"})

        with patch("app.use_cases.general_bot._call_tbms_api") as call_tbms, patch("app.use_cases.general_bot._resolve_config") as resolve_config:
            response = asyncio.run(invoke_general_bot(request))

        call_tbms.assert_not_called()
        resolve_config.assert_not_called()
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["source"], "backend")
        self.assertEqual(payload["origin"], "backend")
        self.assertEqual(payload["source_type"], "backend")
        self.assertEqual(payload["response_type"], "lookup_clarification")
        self.assertEqual(payload["status"], "needs_clarification")

    def test_trade_license_routing_sets_workflow_source(self) -> None:
        request = _FakeRequest({"text": "my trade license is 526422"})

        with patch("app.use_cases.general_bot._lookup_response", return_value=None), patch(
            "app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)
        ), patch("app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "Trade License Expiry Date: 14 May 2017"}))), patch(
            "app.use_cases.general_bot.classify_trade_license_routing",
            return_value=TradeLicenseWorkflowRoute(
                decision=TradeLicenseExpiryDecision(date(2017, 5, 14), -3330, "expired"),
                workflow_name="TCG-Vendor-Approval-Workflow",
                workflow_url="https://example.com/approval",
                message="Trade license expired on 14 May 2017. Starting TCG-Vendor-Approval-Workflow.",
            ),
        ), patch("app.use_cases.general_bot.invoke_activity_workflow", return_value=(200, {"ok": True, "text": "started"})):
            response = asyncio.run(invoke_general_bot(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["source"], "workflow")
        self.assertEqual(payload["origin"], "workflow")
        self.assertEqual(payload["source_type"], "workflow")


if __name__ == "__main__":
    unittest.main()
