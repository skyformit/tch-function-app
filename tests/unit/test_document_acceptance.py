import unittest
from datetime import date
from unittest.mock import patch

from app.use_cases.document_acceptance import build_document_acceptance_response, evaluate_document_acceptance


class DocumentAcceptanceTest(unittest.TestCase):
    def test_trade_license_accepts_complete_active_document(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.missing_fields, [])
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)

    def test_trade_license_accepts_without_license_number_when_name_is_present(self) -> None:
        payload = {
            "results": {
                "CompanyName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.missing_fields, [])
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)

    def test_trade_license_scores_qr_and_verification_signals(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            },
            "qr_codes": {"value": ["https://example.com/qr"]},
            "verification_urls": {"value": ["https://example.com/verify"]},
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "approved")
        self.assertEqual(result.score, 100)
        self.assertIn("QR code present.", result.reasons)
        self.assertIn("Verification URL present.", result.reasons)
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)

    def test_trade_license_scores_gpt_review_contribution(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
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
        self.assertEqual(result.status, "rejected")
        self.assertIn("Expert review contribution: +12.", result.reasons)
        self.assertEqual(result.score, 72)
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)

    def test_trade_license_reports_unavailable_gpt_review(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            },
            "gpt_review": {
                "is_consistent": False,
                "anomalies": ["Missing review configuration"],
                "plausibility_score": 0.0,
                "reasoning": "Missing review configuration",
                "skipped": True,
            },
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "rejected")
        self.assertIn("Expert review unavailable: Missing review configuration.", result.reasons)
        self.assertEqual(result.score, 60)
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=True)
    def test_trade_license_scores_logo_presence(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21), file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "rejected")
        self.assertIn("Logo present.", result.reasons)
        self.assertEqual(result.score, 70)
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)
        mock_logo.assert_called_once()

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=True)
    def test_trade_license_scores_logo_and_gpt_review_together(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
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
        self.assertEqual(result.status, "review")
        self.assertIn("Logo present.", result.reasons)
        self.assertIn("Expert review contribution: +15.", result.reasons)
        self.assertEqual(result.score, 85)
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)
        mock_logo.assert_called_once()

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=False)
    def test_trade_license_reports_logo_absence(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21), file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "rejected")
        self.assertIn("Logo not found.", result.reasons)
        self.assertEqual(result.score, 60)
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)
        mock_logo.assert_called_once()

    def test_trade_license_rejects_expired_document(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2026"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "rejected")
        self.assertIn("expiry_date", result.missing_fields)
        self.assertTrue(result.reasons)
        self.assertEqual(result.expiry_date, "2026-04-06")
        self.assertTrue(result.is_expired)

    def test_trade_license_parses_month_name_expiry_date(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "Sanath Swaroop Mulky CO"},
                "ExpiryDate": {"value": "31 December 2026"},
                "LicenceActivities": {"value": "Information Technology Consultancy"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertNotIn("expiry_date", result.missing_fields)
        self.assertNotIn("Expiry date is present but could not be parsed.", result.reasons)

    def test_trade_license_parses_requested_expiry_formats(self) -> None:
        payloads = [
            {"ExpiryDate": {"value": "2026-02-28"}},
            {"ExpiryDate": {"value": "2026/02/28"}},
            {"ExpiryDate": {"value": "28/02/2026"}},
            {"ExpiryDate": {"value": "28-02-2026"}},
            {"ExpiryDate": {"value": "28 Feb 2026"}},
            {"ExpiryDate": {"value": "28 February 2026"}},
        ]
        for payload_entry in payloads:
            with self.subTest(payload_entry=payload_entry):
                payload = {
                    "results": {
                        "TradeName": {"value": "Sanath Swaroop Mulky CO"},
                        "ExpiryDate": payload_entry["ExpiryDate"],
                        "LicenceActivities": {"value": "Information Technology Consultancy"},
                    }
                }
                result = evaluate_document_acceptance("trade", payload, today=date(2026, 1, 1))
                self.assertNotIn("expiry_date", result.missing_fields)
                self.assertNotIn("Expiry date is present but could not be parsed.", result.reasons)

    def test_trade_license_parses_fallback_python_date(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "Sanath Swaroop Mulky CO"},
                "ExpiryDate": {"value": "December 31, 2026"},
                "LicenceActivities": {"value": "Information Technology Consultancy"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 1, 1))
        self.assertNotIn("expiry_date", result.missing_fields)
        self.assertNotIn("Expiry date is present but could not be parsed.", result.reasons)

    def test_vat_accepts_required_fields(self) -> None:
        payload = {
            "results": {
                "TaxRegistrationNumber": {"value": "100382292900003"},
                "LegalNameEnglish": {"value": "GREEN LIFE EQUIPMENT TRADING"},
            }
        }

        result = evaluate_document_acceptance("vat", payload)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 60)
        self.assertEqual(result.missing_fields, [])

    def test_vat_rejects_missing_company_name(self) -> None:
        payload = {"results": {"TaxRegistrationNumber": {"value": "100382292900003"}}}

        result = evaluate_document_acceptance("vat", payload)
        self.assertEqual(result.status, "rejected")
        self.assertIn("company_name", result.missing_fields)

    def test_bank_accepts_company_name(self) -> None:
        payload = {"results": {"AccountName": {"value": "CICON EPOXY AND STEEL CUTTING PLANT LLC SPC"}}}

        result = evaluate_document_acceptance("bank", payload)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 60)
        self.assertEqual(result.missing_fields, [])

    def test_bank_rejects_missing_bank_name(self) -> None:
        payload = {"results": {}}

        result = evaluate_document_acceptance("bank", payload)
        self.assertEqual(result.status, "rejected")
        self.assertIn("bank_name", result.missing_fields)

    def test_response_wrapper_returns_frontend_shape(self) -> None:
        payload = {
            "results": {
                "TaxRegistrationNumber": {"value": "100382292900003"},
                "LegalNameEnglish": {"value": "GREEN LIFE EQUIPMENT TRADING"},
            }
        }

        response = build_document_acceptance_response("vat", payload)
        self.assertEqual(response["status"], "rejected")
        self.assertFalse(response["acceptable"])
        self.assertEqual(response["document_type"], "vat")
        self.assertEqual(response["missing_fields"], [])
        self.assertIsNone(response["expiry_date"])
        self.assertIsNone(response["is_expired"])


if __name__ == "__main__":
    unittest.main()
