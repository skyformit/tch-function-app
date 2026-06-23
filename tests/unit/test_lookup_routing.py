import unittest

from app.use_cases.lookup_routing import LOOKUP_ROUTING_PROMPT, _validate_decision


class LookupRoutingPromptTest(unittest.TestCase):
    def test_prompt_mentions_core_routes_and_examples(self) -> None:
        self.assertIn("tbms", LOOKUP_ROUTING_PROMPT)
        self.assertIn("chat", LOOKUP_ROUTING_PROMPT)
        self.assertIn("clarify", LOOKUP_ROUTING_PROMPT)
        self.assertIn("document_type", LOOKUP_ROUTING_PROMPT)
        self.assertIn("bank_certificate", LOOKUP_ROUTING_PROMPT)
        self.assertIn("bank_offer", LOOKUP_ROUTING_PROMPT)
        self.assertIn("my trade license number is 206558", LOOKUP_ROUTING_PROMPT)
        self.assertIn("vendor name Abdul Jaleel Al Saadi Trading LLC", LOOKUP_ROUTING_PROMPT)
        self.assertIn("my number is 206558", LOOKUP_ROUTING_PROMPT)

    def test_tbms_without_identifiers_uses_numeric_license(self) -> None:
        decision = _validate_decision(
            {"route": "tbms", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.9, "reason": "lookup"},
            "my number is 206558",
        )
        self.assertEqual(decision["route"], "tbms")
        self.assertEqual(decision["lookup_type"], "trade_license_number")
        self.assertEqual(decision["license_no"], "206558")

    def test_clarify_with_identifiers_upgrades_to_tbms(self) -> None:
        decision = _validate_decision(
            {"route": "clarify", "lookup_type": "unknown", "vendor_name": "Abdul Jaleel Al Saadi Trading LLC", "license_no": "", "confidence": 0.4, "reason": "unclear"},
            "vendor name Abdul Jaleel Al Saadi Trading LLC",
        )
        self.assertEqual(decision["route"], "tbms")
        self.assertEqual(decision["vendor_name"], "Abdul Jaleel Al Saadi Trading LLC")

    def test_clarify_with_numeric_identifier_upgrades_to_tbms(self) -> None:
        decision = _validate_decision(
            {"route": "clarify", "lookup_type": "unknown", "vendor_name": "", "license_no": "", "confidence": 0.4, "reason": "unclear"},
            "my number is 206558",
        )
        self.assertEqual(decision["route"], "tbms")
        self.assertEqual(decision["lookup_type"], "trade_license_number")
        self.assertEqual(decision["license_no"], "206558")

    def test_document_type_preserves_bank_subtypes(self) -> None:
        decision = _validate_decision(
            {"route": "tbms", "lookup_type": "company_name", "document_type": "bank_certificate", "vendor_name": "ABC", "license_no": "", "confidence": 0.9, "reason": "bank cert"},
            "bank certificate ABC",
        )
        self.assertEqual(decision["document_type"], "bank_certificate")
        self.assertEqual(decision["route"], "tbms")


if __name__ == "__main__":
    unittest.main()
