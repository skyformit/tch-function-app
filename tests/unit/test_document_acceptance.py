import unittest
from datetime import date
from unittest.mock import patch

from app.use_cases.document_acceptance import build_document_acceptance_response, evaluate_document_acceptance


class DocumentAcceptanceTest(unittest.TestCase):
    def test_trade_license_accepts_complete_active_document(self) -> None:
        payload = {
            "results": {
                "LicenseNo": {"value": "206558"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "accept")
        self.assertEqual(result.missing_fields, [])

    def test_trade_license_scores_qr_and_verification_signals(self) -> None:
        payload = {
            "results": {
                "LicenseNo": {"value": "206558"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            },
            "qr_codes": {"value": ["https://example.com/qr"]},
            "verification_urls": {"value": ["https://example.com/verify"]},
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "accept")
        self.assertEqual(result.score, 100)
        self.assertIn("QR code present.", result.reasons)
        self.assertIn("Verification URL present.", result.reasons)

    def test_trade_license_scores_gpt_review_contribution(self) -> None:
        payload = {
            "results": {
                "LicenseNo": {"value": "206558"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            },
            "gpt_review": {
                "is_consistent": True,
                "anomalies": [],
                "plausibility_score": 0.8,
                "reasoning": "Mostly consistent.",
            },
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "accept")
        self.assertIn("GPT review contribution: +12.", result.reasons)
        self.assertEqual(result.score, 72)

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=True)
    def test_trade_license_scores_logo_presence(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "LicenseNo": {"value": "206558"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21), file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "accept")
        self.assertIn("Logo present.", result.reasons)
        self.assertEqual(result.score, 70)
        mock_logo.assert_called_once()

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=True)
    def test_trade_license_scores_logo_and_gpt_review_together(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "LicenseNo": {"value": "206558"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            },
            "gpt_review": {
                "is_consistent": True,
                "anomalies": [],
                "plausibility_score": 1.0,
                "reasoning": "Looks consistent.",
            },
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21), file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "accept")
        self.assertIn("Logo present.", result.reasons)
        self.assertIn("GPT review contribution: +15.", result.reasons)
        self.assertEqual(result.score, 85)
        mock_logo.assert_called_once()

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=False)
    def test_trade_license_reports_logo_absence(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "LicenseNo": {"value": "206558"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21), file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "accept")
        self.assertIn("Logo not found.", result.reasons)
        self.assertEqual(result.score, 60)
        mock_logo.assert_called_once()

    def test_trade_license_rejects_expired_document(self) -> None:
        payload = {
            "results": {
                "LicenseNo": {"value": "206558"},
                "ExpiryDate": {"value": "06/04/2026"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "reject")
        self.assertIn("expiry_date", result.missing_fields)
        self.assertTrue(result.reasons)

    def test_vat_accepts_required_fields(self) -> None:
        payload = {
            "results": {
                "TaxRegistrationNumber": {"value": "100382292900003"},
                "LegalNameEnglish": {"value": "GREEN LIFE EQUIPMENT TRADING"},
            }
        }

        result = evaluate_document_acceptance("vat", payload)
        self.assertEqual(result.status, "accept")
        self.assertEqual(result.missing_fields, [])

    def test_vat_rejects_missing_company_name(self) -> None:
        payload = {"results": {"TaxRegistrationNumber": {"value": "100382292900003"}}}

        result = evaluate_document_acceptance("vat", payload)
        self.assertEqual(result.status, "reject")
        self.assertIn("company_name", result.missing_fields)

    def test_bank_accepts_company_name(self) -> None:
        payload = {"results": {"AccountName": {"value": "CICON EPOXY AND STEEL CUTTING PLANT LLC SPC"}}}

        result = evaluate_document_acceptance("bank", payload)
        self.assertEqual(result.status, "accept")
        self.assertEqual(result.missing_fields, [])

    def test_bank_rejects_missing_company_name(self) -> None:
        payload = {"results": {}}

        result = evaluate_document_acceptance("bank", payload)
        self.assertEqual(result.status, "reject")
        self.assertIn("company_name", result.missing_fields)

    def test_response_wrapper_returns_frontend_shape(self) -> None:
        payload = {
            "results": {
                "TaxRegistrationNumber": {"value": "100382292900003"},
                "LegalNameEnglish": {"value": "GREEN LIFE EQUIPMENT TRADING"},
            }
        }

        response = build_document_acceptance_response("vat", payload)
        self.assertEqual(response["status"], "accept")
        self.assertTrue(response["acceptable"])
        self.assertEqual(response["document_type"], "vat")
        self.assertEqual(response["missing_fields"], [])


if __name__ == "__main__":
    unittest.main()
