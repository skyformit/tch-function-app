import unittest

from app.use_cases.lookup_classifier import LOOKUP_CLASSIFICATION_PROMPT, classify_lookup_input


class LookupClassifierTest(unittest.TestCase):
    def test_company_name_is_classified(self) -> None:
        result = classify_lookup_input("Abdul Jaleel Al Saadi Trading LLC")
        self.assertEqual(result["label"], "company_name")
        self.assertGreater(result["confidence"], 0.9)

    def test_person_name_is_classified(self) -> None:
        result = classify_lookup_input("Abdul Jaleel Al Saadi")
        self.assertEqual(result["label"], "person_name")
        self.assertGreater(result["confidence"], 0.8)

    def test_trade_license_number_is_classified(self) -> None:
        result = classify_lookup_input("526422")
        self.assertEqual(result["label"], "trade_license_number")
        self.assertGreater(result["confidence"], 0.9)

    def test_trade_license_label_is_classified_as_license(self) -> None:
        result = classify_lookup_input("trade license no 526422")
        self.assertEqual(result["label"], "trade_license_number")
        self.assertGreater(result["confidence"], 0.9)

    def test_vendor_name_label_is_classified_as_company(self) -> None:
        result = classify_lookup_input("vendor name Abdul Jaleel Al Saadi Trading LLC")
        self.assertEqual(result["label"], "company_name")
        self.assertGreater(result["confidence"], 0.9)

    def test_company_name_label_is_classified_as_company(self) -> None:
        result = classify_lookup_input("company name: Abdul Jaleel Al Saadi Trading LLC")
        self.assertEqual(result["label"], "company_name")
        self.assertGreater(result["confidence"], 0.9)

    def test_prompt_contains_expected_labels(self) -> None:
        self.assertIn("company_name", LOOKUP_CLASSIFICATION_PROMPT)
        self.assertIn("person_name", LOOKUP_CLASSIFICATION_PROMPT)
        self.assertIn("trade_license_number", LOOKUP_CLASSIFICATION_PROMPT)


if __name__ == "__main__":
    unittest.main()
