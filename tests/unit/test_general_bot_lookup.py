import asyncio
import json
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from app.use_cases.general_bot import GENERAL_BOT_SYSTEM_PROMPT, _general_bot_prompt, invoke_general_bot
from app.use_cases.general_bot_memory import clear_conversation_entities, clear_trusted_trade_document, get_trusted_trade_document, remember_trusted_trade_document
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

        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=False,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "chat", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.92, "reason": "General chat."},
        ), patch(
            "app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)
        ), patch("app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM answer"}))):
            response = asyncio.run(invoke_general_bot(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["source"], "llm")
        self.assertEqual(payload["origin"], "llm")
        self.assertEqual(payload["source_type"], "llm")
        self.assertIn("context", payload)
        self.assertEqual(payload["context"]["intent"], "chat")
        self.assertEqual(payload["context"]["document_type"], "unknown")
        self.assertEqual(payload["context"]["entities"]["company_name"], "")
        self.assertEqual(payload["context"]["entities"]["trade_license_number"], "")
        self.assertEqual(payload["context"]["next_action"], "general_chat")
        self.assertIn("llm_response", payload)
        self.assertEqual(payload["llm_response"]["text"], "LLM answer")

    def test_general_bot_prompt_wraps_user_message(self) -> None:
        prompt = _general_bot_prompt("my company name is SOTI")
        self.assertIn(GENERAL_BOT_SYSTEM_PROMPT.splitlines()[0], prompt)
        self.assertIn("User message:", prompt)
        self.assertIn("my company name is SOTI", prompt)

    def test_general_bot_prompt_includes_remembered_context(self) -> None:
        prompt = _general_bot_prompt(
            "lets start with vat",
            remembered_entities={"company_name": "Eurocon Building Industries", "trade_license_number": "3437"},
            conversation_id="conv-123",
            context_mode="continue",
        )
        self.assertIn("Conversation context:", prompt)
        self.assertIn("conversation_id: conv-123", prompt)
        self.assertIn("context_mode: continue", prompt)
        self.assertIn("remembered_company_name: Eurocon Building Industries", prompt)
        self.assertIn("remembered_trade_license_number: 3437", prompt)
        self.assertIn("Use the conversation context only as a continuity hint.", prompt)

    def test_lookup_text_uses_llm_only_when_tbms_disabled(self) -> None:
        request = _FakeRequest({"text": "my trade license number is 206558"})

        with patch("app.use_cases.general_bot.enable_tbms_lookup", return_value=False), patch(
            "app.use_cases.general_bot._call_tbms_api"
        ) as call_tbms, patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM answer"}))
        ) as invoke_workflow:
            response = asyncio.run(invoke_general_bot(request))

        call_tbms.assert_not_called()
        invoke_workflow.assert_called_once()
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["source"], "llm")
        self.assertEqual(payload["origin"], "llm")
        self.assertEqual(payload["source_type"], "llm")

    def test_company_name_goes_to_tbms_lookup(self) -> None:
        request = _FakeRequest({"text": "Abdul Jaleel Al Saadi Trading LLC"})

        fake_tbms_response = _FakeTbmsResponse({"ok": True, "data": {"results": [{"vendorName": "Abdul Jaleel Al Saadi Trading LLC"}]}, "status_code": 200})
        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "tbms", "lookup_type": "company_name", "vendor_name": "Abdul Jaleel Al Saadi Trading LLC", "license_no": "", "confidence": 0.98, "reason": "Company lookup."},
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._call_tbms_api", return_value=fake_tbms_response
        ) as call_tbms, patch(
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
        self.assertIn("lookup_match", payload)
        self.assertEqual(payload["lookup_match"]["requested_company_name"], "Abdul Jaleel Al Saadi Trading LLC")
        self.assertEqual(payload["lookup_match"]["matched_company_name"], "Abdul Jaleel Al Saadi Trading LLC")
        self.assertEqual(payload["lookup_match"]["match_status"], "exact")
        self.assertEqual(payload["context"]["intent"], "lookup")
        self.assertEqual(payload["context"]["entities"]["company_name"], "Abdul Jaleel Al Saadi")

    def test_company_name_tbms_mismatch_is_marked_as_mismatch(self) -> None:
        request = _FakeRequest({"text": "Abdul Jaleel Al Saadi Trading LLC"})

        fake_tbms_response = _FakeTbmsResponse({"ok": True, "data": {"results": [{"vendorName": "Different Vendor LLC"}]}, "status_code": 200})
        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "tbms", "lookup_type": "company_name", "vendor_name": "Abdul Jaleel Al Saadi Trading LLC", "license_no": "", "confidence": 0.98, "reason": "Company lookup."},
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._call_tbms_api", return_value=fake_tbms_response
        ) as call_tbms:
            response = asyncio.run(invoke_general_bot(request))

        call_tbms.assert_called_once()
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertIn("lookup_match", payload)
        self.assertEqual(payload["lookup_match"]["match_status"], "mismatch")
        self.assertLess(payload["lookup_match"]["similarity_percent"], 80.0)

    def test_mixed_company_and_license_tries_both_then_license_only(self) -> None:
        request = _FakeRequest({"text": "Abdul Jaleel Al Saadi Trading LLC 526422"})

        responses = [
            _FakeTbmsResponse({"ok": True, "data": {"results": []}, "status_code": 200}),
            _FakeTbmsResponse({"ok": True, "data": {"results": [{"vendorName": "Abdul Jaleel Al Saadi Trading LLC"}]}, "status_code": 200}),
        ]

        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "tbms", "lookup_type": "company_name", "vendor_name": "Abdul Jaleel Al Saadi Trading LLC", "license_no": "526422", "confidence": 0.98, "reason": "Company and license lookup."},
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._call_tbms_api", side_effect=responses
        ) as call_tbms:
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
        self.assertEqual(payload["context"]["intent"], "lookup")
        self.assertEqual(payload["context"]["entities"]["company_name"], "Abdul Jaleel Al Saadi")
        self.assertEqual(payload["context"]["entities"]["trade_license_number"], "526422")
        self.assertEqual(payload["context"]["next_action"], "tbms_lookup")

    def test_trade_license_number_goes_to_tbms_lookup(self) -> None:
        request = _FakeRequest({"text": "526422"})

        fake_tbms_response = _FakeTbmsResponse({"ok": True, "data": {"results": []}, "status_code": 200})
        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "tbms", "lookup_type": "trade_license_number", "vendor_name": "", "license_no": "526422", "confidence": 0.99, "reason": "License lookup."},
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._call_tbms_api", return_value=fake_tbms_response
        ) as call_tbms:
            response = asyncio.run(invoke_general_bot(request))

        call_tbms.assert_called_once()
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["context"]["intent"], "lookup")
        self.assertEqual(payload["context"]["entities"]["trade_license_number"], "526422")
        self.assertEqual(payload["context"]["next_action"], "tbms_lookup")

    def test_non_business_year_question_does_not_go_to_tbms(self) -> None:
        request = _FakeRequest({"text": "who win world cup cricket 1983"})

        with patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "chat", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.88, "reason": "General chat."},
        ), patch("app.use_cases.general_bot._call_tbms_api") as call_tbms, patch(
            "app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)
        ), patch("app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM answer"}))) as invoke_workflow:
            response = asyncio.run(invoke_general_bot(request))

        call_tbms.assert_not_called()
        invoke_workflow.assert_called_once()
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["source"], "llm")

    def test_trade_details_question_uses_trusted_trade_document(self) -> None:
        conversation_id = "conv-trusted-trade"
        clear_trusted_trade_document(conversation_id)
        remember_trusted_trade_document(
            conversation_id,
            {
                "document_type": "trade",
                "company_name": "CONSTRUCTION MACHINERY CENTER",
                "trade_license_number": "206558",
                "expiry_date": "2027-04-06",
                "licensed_activities": "Construction Equipment Trading",
                "document_acceptance": {"status": "approved", "expiry_date": "2027-04-06", "is_expired": False},
                "results": {
                    "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER", "confidence": 0.98},
                    "LicenseNo": {"value": "206558", "confidence": 0.99},
                    "ExpiryDate": {"value": "06/04/2027", "confidence": 0.99},
                    "LicenceActivities": {"value": "Construction Equipment Trading", "confidence": 0.99},
                },
            },
        )
        request = _FakeRequest({"text": "what are my trade license details", "conversation_id": conversation_id})

        with patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock()
        ) as invoke_workflow, patch("app.use_cases.general_bot._call_tbms_api") as call_tbms:
            response = asyncio.run(invoke_general_bot(request))

        call_tbms.assert_not_called()
        invoke_workflow.assert_not_called()
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["source"], "backend")
        self.assertEqual(payload["origin"], "backend")
        self.assertEqual(payload["source_type"], "backend")
        self.assertEqual(payload["context"]["document_type"], "trade")
        self.assertEqual(payload["context"]["intent"], "lookup")
        self.assertEqual(payload["trade_document"]["trade_license_number"], "206558")
        self.assertEqual(payload["trade_document"]["company_name"], "CONSTRUCTION MACHINERY CENTER")
        self.assertIn("Verified trade license details", payload["text"])

    def test_general_trading_phrase_stays_chat(self) -> None:
        request = _FakeRequest({"text": "abc general trading"})

        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "chat", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.52, "reason": "General chat."},
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM answer"}))
        ):
            response = asyncio.run(invoke_general_bot(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["context"]["intent"], "chat")
        self.assertEqual(payload["context"]["next_action"], "general_chat")
        self.assertEqual(payload["context"]["entities"]["company_name"], "")

    def test_short_company_name_is_backfilled_from_llm_response(self) -> None:
        request = _FakeRequest({"text": "SOTI", "conversation_id": "conv-soti"})

        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "chat", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.5, "reason": "General chat."},
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._invoke_general_bot_workflow",
            new=AsyncMock(
                return_value=(
                    200,
                    {
                        "ok": True,
                        "text": json.dumps(
                            {
                                "ok": True,
                                "text": "Thank you for providing your company name: SOTI.",
                                "context": {
                                    "intent": "lookup",
                                    "document_type": "unknown",
                                    "entities": {"company_name": "SOTI", "trade_license_number": ""},
                                    "next_action": "tbms_lookup",
                                    "classification": {"label": "company_name", "confidence": 0.98, "reason": "Explicit company name."},
                                },
                            }
                        ),
                    },
                )
            ),
        ):
            response = asyncio.run(invoke_general_bot(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["context"]["entities"]["company_name"], "SOTI")
        self.assertEqual(payload["context"]["intent"], "lookup")
        self.assertEqual(payload["context"]["next_action"], "tbms_lookup")

    def test_company_name_suffix_is_normalized_and_routes_to_tbms(self) -> None:
        request = _FakeRequest({"text": "I want to onboard new company FISCHER FIXING"})

        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=False,
        ), patch(
            "app.use_cases.general_bot._resolve_config",
            return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None),
        ), patch(
            "app.use_cases.general_bot._invoke_general_bot_workflow",
            new=AsyncMock(
                return_value=(
                    200,
                    {
                        "ok": True,
                        "text": json.dumps(
                            {
                                "ok": True,
                                "text": "Thank you for sharing your company name, FISCHER FIXING trading. Please provide your trade license number.",
                                "context": {
                                    "intent": "chat",
                                    "document_type": "unknown",
                                    "entities": {"company_name": "FISCHER FIXING trading", "trade_license_number": ""},
                                    "next_action": "ask_clarification",
                                    "classification": {"label": "company_name", "confidence": 0.95, "reason": "The user explicitly stated their company name."},
                                },
                            }
                        ),
                    },
                )
            ),
        ):
            response = asyncio.run(invoke_general_bot(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["context"]["entities"]["company_name"], "FISCHER FIXING")
        self.assertEqual(payload["context"]["intent"], "lookup")
        self.assertEqual(payload["context"]["next_action"], "tbms_lookup")

    def test_quoted_company_name_in_llm_response_is_backfilled(self) -> None:
        request = _FakeRequest({"text": "SOTI", "conversation_id": "conv-soti-quoted"})

        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "chat", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.5, "reason": "General chat."},
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._invoke_general_bot_workflow",
            new=AsyncMock(
                return_value=(
                    200,
                    {
                        "ok": True,
                        "text": json.dumps(
                            {
                                "ok": True,
                                "text": "Thank you for confirming you want to onboard \"CONSTRUCTION MACHINERY CENTER\" as a supplier with Trojan Construction Holdings.",
                                "context": {
                                    "intent": "lookup",
                                    "document_type": "unknown",
                                    "entities": {"company_name": "CONSTRUCTION MACHINERY CENTER", "trade_license_number": ""},
                                    "next_action": "tbms_lookup",
                                    "classification": {"label": "company_name", "confidence": 0.98, "reason": "Explicit company name."},
                                },
                            }
                        ),
                    },
                )
            ),
        ):
            response = asyncio.run(invoke_general_bot(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["context"]["entities"]["company_name"], "CONSTRUCTION MACHINERY CENTER")
        self.assertEqual(payload["context"]["intent"], "lookup")
        self.assertEqual(payload["context"]["next_action"], "tbms_lookup")

    def test_assistant_fallback_does_not_capture_document_list_text(self) -> None:
        request = _FakeRequest({"text": "onboarding as supplier", "conversation_id": "conv-doc-list"})

        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "chat", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.5, "reason": "General chat."},
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._invoke_general_bot_workflow",
            new=AsyncMock(
                return_value=(
                    200,
                    {
                        "ok": True,
                        "text": json.dumps(
                            {
                                "ok": True,
                                "text": "Thank you for confirming you want to onboard \"CONSTRUCTION MACHINERY CENTER\" as a supplier with Trojan Construction Holdings.\n\nTo complete supplier onboarding, please provide the following documents and details:\n1. Trade License\n2. VAT Certificate\n3. Bank Proof Document\n\nIf you need help, let me know what you need.",
                                "context": {
                                    "intent": "lookup",
                                    "document_type": "unknown",
                                    "entities": {"company_name": "CONSTRUCTION MACHINERY CENTER", "trade_license_number": ""},
                                    "next_action": "tbms_lookup",
                                    "classification": {"label": "company_name", "confidence": 0.98, "reason": "Explicit company name."},
                                },
                            }
                        ),
                    },
                )
            ),
        ):
            response = asyncio.run(invoke_general_bot(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["context"]["entities"]["company_name"], "CONSTRUCTION MACHINERY CENTER")
        self.assertEqual(payload["context"]["next_action"], "tbms_lookup")

    def test_tbms_parse_error_reports_body_shape(self) -> None:
        from app.use_cases.general_bot import _tbms_http_response_to_payload

        payload = _tbms_http_response_to_payload(_FakeTextTbmsResponse("not-json", 502))
        self.assertEqual(payload["error"]["code"], "response_parse_error")
        self.assertEqual(payload["error"]["body_type"], "str")
        self.assertEqual(payload["error"]["status_code"], 502)

    def test_greeting_prefixed_company_name_strips_greeting_before_lookup(self) -> None:
        request = _FakeRequest({"text": "hello Abdul Jaleel Al Saadi Trading LLC"})

        fake_tbms_response = _FakeTbmsResponse({"ok": True, "data": {"results": [{"vendorName": "Abdul Jaleel Al Saadi Trading LLC"}]}, "status_code": 200})
        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "tbms", "lookup_type": "company_name", "vendor_name": "Abdul Jaleel Al Saadi Trading LLC", "license_no": "", "confidence": 0.98, "reason": "Company lookup."},
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._call_tbms_api", return_value=fake_tbms_response
        ) as call_tbms:
            response = asyncio.run(invoke_general_bot(request))

        call_tbms.assert_called_once()
        payload_sent = call_tbms.call_args.args[1]
        self.assertEqual(payload_sent["vendorName"], "Abdul Jaleel Al Saadi Trading LLC")
        self.assertEqual(payload_sent["licenseNo"], "")
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["context"]["entities"]["company_name"], "Abdul Jaleel Al Saadi")

    def test_company_name_label_after_preamble_is_extracted(self) -> None:
        request = _FakeRequest({"text": "i want to register as suppler company name abc"})

        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "tbms", "lookup_type": "company_name", "vendor_name": "abc", "license_no": "", "confidence": 0.98, "reason": "Company lookup."},
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._call_tbms_api", return_value=_FakeTbmsResponse({"ok": True, "data": {"results": []}, "status_code": 200})
        ):
            response = asyncio.run(invoke_general_bot(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["context"]["entities"]["company_name"], "abc")
        self.assertEqual(payload["context"]["next_action"], "tbms_lookup")

    def test_onboarding_preamble_is_stripped_from_company_name(self) -> None:
        request = _FakeRequest({"text": "new onboarding company naem FISCHER FIXING"})

        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            return_value={"route": "tbms", "lookup_type": "company_name", "vendor_name": "FISCHER FIXING", "license_no": "", "confidence": 0.98, "reason": "Company lookup."},
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._call_tbms_api", return_value=_FakeTbmsResponse({"ok": True, "data": {"results": []}, "status_code": 200})
        ):
            response = asyncio.run(invoke_general_bot(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["context"]["entities"]["company_name"], "FISCHER FIXING")
        self.assertEqual(payload["context"]["next_action"], "tbms_lookup")

    def test_company_name_is_not_reused_for_general_chat(self) -> None:
        first_request = _FakeRequest({"text": "company name abc studio inc", "conversation_id": "conv-1"})
        second_request = _FakeRequest({"text": "what is the leave policy", "conversation_id": "conv-1"})

        clear_conversation_entities("conv-1")
        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            side_effect=[
                {"route": "tbms", "lookup_type": "company_name", "vendor_name": "abc studio inc", "license_no": "", "confidence": 0.98, "reason": "Company lookup."},
                {"route": "chat", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.5, "reason": "General chat."},
            ],
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._call_tbms_api", return_value=_FakeTbmsResponse({"ok": True, "data": {"results": [{"vendorName": "abc studio inc"}]}, "status_code": 200})
        ), patch("app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM answer"}))):
            first_response = asyncio.run(invoke_general_bot(first_request))
            second_response = asyncio.run(invoke_general_bot(second_request))

        first_payload = json.loads((getattr(first_response, "body", None) or first_response.get_body()).decode())
        second_payload = json.loads((getattr(second_response, "body", None) or second_response.get_body()).decode())
        self.assertEqual(first_payload["context"]["entities"]["company_name"], "abc studio inc")
        self.assertEqual(second_payload["context"]["entities"]["company_name"], "")
        self.assertEqual(second_payload["context"]["next_action"], "general_chat")

    def test_company_name_is_reused_when_continue_mode_is_requested(self) -> None:
        first_request = _FakeRequest({"text": "company name abc studio inc", "conversation_id": "conv-continue"})
        second_request = _FakeRequest({"text": "continue", "conversation_id": "conv-continue", "context_mode": "continue"})

        clear_conversation_entities("conv-continue")
        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            side_effect=[
                {"route": "tbms", "lookup_type": "company_name", "vendor_name": "abc studio inc", "license_no": "", "confidence": 0.98, "reason": "Company lookup."},
                {"route": "chat", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.5, "reason": "General chat."},
            ],
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._call_tbms_api", return_value=_FakeTbmsResponse({"ok": True, "data": {"results": [{"vendorName": "abc studio inc"}]}, "status_code": 200})
        ), patch("app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM answer"}))):
            first_response = asyncio.run(invoke_general_bot(first_request))
            second_response = asyncio.run(invoke_general_bot(second_request))

        first_payload = json.loads((getattr(first_response, "body", None) or first_response.get_body()).decode())
        second_payload = json.loads((getattr(second_response, "body", None) or second_response.get_body()).decode())
        self.assertEqual(first_payload["context"]["entities"]["company_name"], "abc studio inc")
        self.assertEqual(second_payload["context"]["entities"]["company_name"], "abc studio inc")

    def test_trusted_trade_document_memory_round_trip(self) -> None:
        conversation_id = "conv-storage-roundtrip"
        clear_trusted_trade_document(conversation_id)
        remember_trusted_trade_document(conversation_id, {"company_name": "FISCHER FIXING", "trade_license_number": "CN-1178590"})
        stored = get_trusted_trade_document(conversation_id)
        self.assertEqual(stored["company_name"], "FISCHER FIXING")
        self.assertEqual(stored["trade_license_number"], "CN-1178590")

    def test_unrelated_topic_clears_stored_company_memory(self) -> None:
        first_request = _FakeRequest({"text": "company name abc studio inc", "conversation_id": "conv-shift"})
        second_request = _FakeRequest({"text": "what is the leave policy", "conversation_id": "conv-shift"})
        third_request = _FakeRequest({"text": "continue", "conversation_id": "conv-shift", "context_mode": "continue"})

        clear_conversation_entities("conv-shift")
        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch(
            "app.use_cases.general_bot.classify_lookup_route",
            side_effect=[
                {"route": "tbms", "lookup_type": "company_name", "vendor_name": "abc studio inc", "license_no": "", "confidence": 0.98, "reason": "Company lookup."},
                {"route": "chat", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.5, "reason": "General chat."},
                {"route": "chat", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.5, "reason": "General chat."},
            ],
        ), patch("app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)), patch(
            "app.use_cases.general_bot._call_tbms_api", return_value=_FakeTbmsResponse({"ok": True, "data": {"results": [{"vendorName": "abc studio inc"}]}, "status_code": 200})
        ), patch("app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM answer"}))):
            first_response = asyncio.run(invoke_general_bot(first_request))
            second_response = asyncio.run(invoke_general_bot(second_request))
            third_response = asyncio.run(invoke_general_bot(third_request))

        first_payload = json.loads((getattr(first_response, "body", None) or first_response.get_body()).decode())
        second_payload = json.loads((getattr(second_response, "body", None) or second_response.get_body()).decode())
        third_payload = json.loads((getattr(third_response, "body", None) or third_response.get_body()).decode())
        self.assertEqual(first_payload["context"]["entities"]["company_name"], "abc studio inc")
        self.assertEqual(second_payload["context"]["entities"]["company_name"], "")
        self.assertEqual(third_payload["context"]["entities"]["company_name"], "")
        self.assertEqual(third_payload["context"]["context_mode"], "continue")

    def test_person_name_requests_clarification(self) -> None:
        request = _FakeRequest({"text": "Abdul Jaleel Al Saadi"})

        with patch(
            "app.use_cases.general_bot.enable_tbms_lookup",
            return_value=True,
        ), patch("app.use_cases.general_bot.classify_lookup_route", return_value={"route": "clarify", "lookup_type": "person_name", "vendor_name": "", "license_no": "", "confidence": 0.91, "reason": "Looks like a person name."}), patch(
            "app.use_cases.general_bot._call_tbms_api"
        ) as call_tbms, patch(
            "app.use_cases.general_bot._resolve_config",
            return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None),
        ) as resolve_config:
            response = asyncio.run(invoke_general_bot(request))

        call_tbms.assert_not_called()
        resolve_config.assert_called_once()
        self.assertEqual(response.status_code, 200)
        payload = json.loads((getattr(response, "body", None) or response.get_body()).decode())
        self.assertEqual(payload["source"], "backend")
        self.assertEqual(payload["origin"], "backend")
        self.assertEqual(payload["source_type"], "backend")
        self.assertEqual(payload["response_type"], "lookup_clarification")
        self.assertEqual(payload["status"], "needs_clarification")
        self.assertEqual(payload["context"]["intent"], "lookup")
        self.assertEqual(payload["context"]["next_action"], "ask_clarification")

    def test_trade_license_routing_sets_workflow_source(self) -> None:
        request = _FakeRequest({"text": "my trade license is 526422"})

        with patch("app.use_cases.general_bot.classify_lookup_route", return_value={"route": "chat", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.5, "reason": "General chat."}), patch(
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
        self.assertEqual(payload["context"]["intent"], "lookup")
        self.assertEqual(payload["context"]["next_action"], "workflow")


if __name__ == "__main__":
    unittest.main()
