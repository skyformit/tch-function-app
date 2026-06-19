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

        with patch("app.use_cases.general_bot._resolve_config") as resolve_config, patch("app.use_cases.general_bot._invoke_general_bot_workflow") as invoke_workflow:
            response = asyncio.run(invoke_general_bot(request))

        resolve_config.assert_not_called()
        invoke_workflow.assert_not_called()
        self.assertEqual(response.status_code, 200)
        raw_body = getattr(response, "body", None)
        if raw_body is None:
            raw_body = response.get_body()
        payload = json.loads(raw_body.decode())
        self.assertEqual(payload["source"], "backend")
        self.assertEqual(payload["origin"], "backend")
        self.assertEqual(payload["source_type"], "backend")
        self.assertEqual(payload["response_type"], "small_talk")
        self.assertEqual(payload["status"], "completed")
        self.assertIn("vendor lookup", payload["text"])

    def test_hello_with_punctuation_is_answered_without_foundry_call(self) -> None:
        request = _FakeRequest({"text": "Hello!!"})

        with patch("app.use_cases.general_bot._resolve_config") as resolve_config, patch("app.use_cases.general_bot._invoke_general_bot_workflow") as invoke_workflow:
            response = asyncio.run(invoke_general_bot(request))

        resolve_config.assert_not_called()
        invoke_workflow.assert_not_called()
        self.assertEqual(response.status_code, 200)
        raw_body = getattr(response, "body", None) or response.get_body()
        payload = json.loads(raw_body.decode())
        self.assertEqual(payload["source"], "backend")
        self.assertEqual(payload["origin"], "backend")
        self.assertEqual(payload["source_type"], "backend")
        self.assertEqual(payload["response_type"], "small_talk")


if __name__ == "__main__":
    unittest.main()
