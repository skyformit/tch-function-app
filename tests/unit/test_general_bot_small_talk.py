import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.use_cases.general_bot import invoke_general_bot


class _FakeRequest:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self):
        return self._body


class GeneralBotSmallTalkTest(unittest.TestCase):
    def test_hello_is_answered_without_foundry_call(self) -> None:
        request = _FakeRequest({"text": "hello"})

        with patch("app.use_cases.general_bot._lookup_response", return_value=None), patch(
            "app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)
        ) as resolve_config, patch("app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM hello"}))) as invoke_workflow:
            response = asyncio.run(invoke_general_bot(request))

        resolve_config.assert_called_once()
        invoke_workflow.assert_called_once()
        self.assertEqual(response.status_code, 200)
        raw_body = getattr(response, "body", None)
        if raw_body is None:
            raw_body = response.get_body()
        payload = json.loads(raw_body.decode())
        self.assertEqual(payload["source"], "llm")
        self.assertEqual(payload["origin"], "llm")
        self.assertEqual(payload["source_type"], "llm")
        self.assertEqual(payload["text"], "LLM hello")

    def test_hello_with_punctuation_is_answered_without_foundry_call(self) -> None:
        request = _FakeRequest({"text": "Hello!!"})

        with patch("app.use_cases.general_bot._lookup_response", return_value=None), patch(
            "app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)
        ) as resolve_config, patch("app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM hello"}))) as invoke_workflow:
            response = asyncio.run(invoke_general_bot(request))

        resolve_config.assert_called_once()
        invoke_workflow.assert_called_once()
        self.assertEqual(response.status_code, 200)
        raw_body = getattr(response, "body", None) or response.get_body()
        payload = json.loads(raw_body.decode())
        self.assertEqual(payload["source"], "llm")
        self.assertEqual(payload["origin"], "llm")
        self.assertEqual(payload["source_type"], "llm")

    def test_who_are_you_is_answered_without_foundry_call(self) -> None:
        request = _FakeRequest({"text": "who are you"})

        with patch("app.use_cases.general_bot._lookup_response", return_value=None), patch(
            "app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)
        ) as resolve_config, patch("app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM who are you"}))) as invoke_workflow:
            response = asyncio.run(invoke_general_bot(request))

        resolve_config.assert_called_once()
        invoke_workflow.assert_called_once()
        self.assertEqual(response.status_code, 200)
        raw_body = getattr(response, "body", None) or response.get_body()
        payload = json.loads(raw_body.decode())
        self.assertEqual(payload["source"], "llm")
        self.assertEqual(payload["origin"], "llm")
        self.assertEqual(payload["source_type"], "llm")
        self.assertEqual(payload["text"], "LLM who are you")

    def test_what_can_you_do_is_answered_without_foundry_call(self) -> None:
        request = _FakeRequest({"text": "what can you do"})

        with patch("app.use_cases.general_bot._lookup_response", return_value=None), patch(
            "app.use_cases.general_bot._resolve_config", return_value=({"project_endpoint": "https://example", "agent_id": "agent", "token_scope": "scope"}, None)
        ) as resolve_config, patch("app.use_cases.general_bot._invoke_general_bot_workflow", new=AsyncMock(return_value=(200, {"ok": True, "text": "LLM what can you do"}))) as invoke_workflow:
            response = asyncio.run(invoke_general_bot(request))

        resolve_config.assert_called_once()
        invoke_workflow.assert_called_once()
        self.assertEqual(response.status_code, 200)
        raw_body = getattr(response, "body", None) or response.get_body()
        payload = json.loads(raw_body.decode())
        self.assertEqual(payload["source"], "llm")
        self.assertEqual(payload["origin"], "llm")
        self.assertEqual(payload["source_type"], "llm")
        self.assertEqual(payload["text"], "LLM what can you do")


if __name__ == "__main__":
    unittest.main()
