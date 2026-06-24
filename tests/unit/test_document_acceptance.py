import unittest
from datetime import date
from unittest.mock import patch

from app.infrastructure.document_logo_extraction import extract_logo_presence_from_pdf
from app.use_cases.document_acceptance import build_document_acceptance_response, evaluate_document_acceptance


class DocumentAcceptanceTest(unittest.TestCase):
    def test_trade_license_accepts_complete_active_document(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
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
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
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
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
            },
            "qr_codes": {"value": ["https://example.com/qr"]},
            "verification_urls": {"value": ["https://example.com/verify"]},
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "review")
        self.assertEqual(result.score, 90)
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
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
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
        self.assertIn("Expert review contribution: +4.", result.reasons)
        self.assertEqual(result.score, 74)
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)

    def test_trade_license_reports_unavailable_gpt_review(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
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
        self.assertEqual(result.score, 70)
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=True)
    def test_trade_license_scores_logo_presence(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21), file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "rejected")
        self.assertIn("Logo present.", result.reasons)
        self.assertEqual(result.score, 75)
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
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
            },
            "gpt_review": {
                "is_consistent": True,
                "anomalies": [],
                "plausibility_score": 1.0,
                "reasoning": "Looks consistent.",
            },
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21), file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "rejected")
        self.assertIn("Logo present.", result.reasons)
        self.assertIn("Expert review contribution: +5.", result.reasons)
        self.assertEqual(result.score, 80)
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)
        mock_logo.assert_called_once()

    def test_trade_license_scores_issuing_authority_bonus(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
            },
            "qr_codes": {"value": ["https://example.com/qr"]},
            "verification_urls": {"value": ["https://example.com/verify"]},
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "review")
        self.assertEqual(result.score, 90)
        self.assertTrue(any("Issuing authority present" in reason for reason in result.reasons))

    def test_trade_license_scores_common_free_zone_authority_bonus(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
                "IssuingAuthority": {"value": "JAFZA"},
            },
            "qr_codes": {"value": ["https://example.com/qr"]},
            "verification_urls": {"value": ["https://example.com/verify"]},
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "review")
        self.assertEqual(result.score, 90)
        self.assertTrue(any("Issuing authority present" in reason for reason in result.reasons))

    def test_trade_license_rejects_when_gpt_review_flags_fraud_risk(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
            },
            "gpt_review": {
                "is_consistent": False,
                "anomalies": ["Document looks tampered or template-like."],
                "plausibility_score": 0.92,
                "reasoning": "Suspicious document.",
            },
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21))
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 0)
        self.assertIn("document_authenticity", result.missing_fields)
        self.assertTrue(any("fraud risk" in reason.lower() for reason in result.reasons))

    def test_trade_license_rejects_when_requested_company_does_not_match(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
            },
            "qr_codes": {"value": ["https://example.com/qr"]},
            "verification_urls": {"value": ["https://example.com/verify"]},
            "gpt_review": {
                "is_consistent": True,
                "anomalies": [],
                "plausibility_score": 1.0,
                "reasoning": "Looks consistent.",
            },
        }

        result = evaluate_document_acceptance(
            "trade",
            payload,
            today=date(2026, 6, 21),
            file_bytes=b"%PDF-1.4",
            requested_company_name="Eurocon Building Industries FZE",
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 0)
        self.assertIn("company_name_mismatch", result.missing_fields)
        self.assertTrue(any("does not match uploaded trade license company name" in reason for reason in result.reasons))

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=True)
    def test_trade_license_accepts_when_requested_company_matches_canonically(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "Eurocon Building Industries FZE"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
            },
            "qr_codes": {"value": ["https://example.com/qr"]},
            "verification_urls": {"value": ["https://example.com/verify"]},
            "gpt_review": {
                "is_consistent": True,
                "anomalies": [],
                "plausibility_score": 1.0,
                "reasoning": "Looks consistent.",
            },
        }

        result = evaluate_document_acceptance(
            "trade",
            payload,
            today=date(2026, 6, 21),
            file_bytes=b"%PDF-1.4",
            requested_company_name="Eurocon Building Industries",
        )
        self.assertEqual(result.status, "approved")
        self.assertEqual(result.score, 100)
        self.assertNotIn("company_name_mismatch", result.missing_fields)
        mock_logo.assert_called_once()

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=True)
    def test_bank_document_scores_logo_only_to_review(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "AccountName": {"value": "CONSTRUCTION MACHINERY CENTER CO. LLC"},
                "BankName": {"value": "Commercial Bank of Dubai"},
                "AccountNumber": {"value": "1000078384"},
                "IBAN": {"value": "AE030230000001000078384"},
                "IssuingAuthority": {"value": "Commercial Bank of Dubai"},
            }
        }

        result = evaluate_document_acceptance("bank", payload, file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "review")
        self.assertEqual(result.score, 85)
        self.assertIn("Logo present.", result.reasons)
        self.assertNotIn("Expert review contribution:", " ".join(result.reasons))
        mock_logo.assert_called_once()

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=True)
    def test_bank_document_scores_logo_and_gpt_review_to_approved(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "AccountName": {"value": "CONSTRUCTION MACHINERY CENTER CO. LLC"},
                "BankName": {"value": "Commercial Bank of Dubai"},
                "AccountNumber": {"value": "1000078384"},
                "IBAN": {"value": "AE030230000001000078384"},
                "IssuingAuthority": {"value": "Commercial Bank of Dubai"},
            },
            "gpt_review": {
                "is_consistent": True,
                "anomalies": [],
                "plausibility_score": 1.0,
                "reasoning": "Looks consistent.",
            },
        }

        result = evaluate_document_acceptance("bank", payload, file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "approved")
        self.assertEqual(result.score, 100)
        self.assertIn("Logo present.", result.reasons)
        self.assertIn("Expert review contribution: +15.", result.reasons)
        mock_logo.assert_called_once()

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=False)
    def test_trade_license_reports_logo_absence(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2027"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
            }
        }

        result = evaluate_document_acceptance("trade", payload, today=date(2026, 6, 21), file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "rejected")
        self.assertIn("Logo not found.", result.reasons)
        self.assertEqual(result.score, 70)
        self.assertEqual(result.expiry_date, "2027-04-06")
        self.assertFalse(result.is_expired)
        mock_logo.assert_called_once()

    @patch("app.infrastructure.document_logo_extraction.fitz.open")
    def test_logo_detector_scans_all_pages(self, mock_open: object) -> None:
        first_page = unittest.mock.MagicMock()
        first_page.rect.height = 100.0
        first_page.get_images.return_value = []
        first_page.get_image_rects.return_value = []

        second_page = unittest.mock.MagicMock()
        second_page.rect.height = 100.0
        second_page.get_images.return_value = [(1,)]
        second_page.get_image_rects.return_value = []

        mock_open.return_value = [first_page, second_page]
        self.assertTrue(extract_logo_presence_from_pdf(b"%PDF-1.4"))

    def test_trade_license_rejects_expired_document(self) -> None:
        payload = {
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)"},
                "ExpiryDate": {"value": "06/04/2026"},
                "LicenceActivities": {"value": "Construction Equipment Trading"},
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
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
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
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
                        "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
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
                "IssuingAuthority": {"value": "Department of Economy and Tourism, Dubai"},
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
                "IssuingAuthority": {"value": "Federal Tax Authority"},
            }
        }

        result = evaluate_document_acceptance("vat", payload)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 70)
        self.assertEqual(result.missing_fields, [])

    def test_vat_rejects_missing_company_name(self) -> None:
        payload = {"results": {"TaxRegistrationNumber": {"value": "100382292900003"}}}

        result = evaluate_document_acceptance("vat", payload)
        self.assertEqual(result.status, "rejected")
        self.assertIn("company_name", result.missing_fields)

    def test_vat_rejects_when_requested_company_does_not_match(self) -> None:
        payload = {
            "results": {
                "TaxRegistrationNumber": {"value": "100382292900003"},
                "LegalNameEnglish": {"value": "GREEN LIFE EQUIPMENT TRADING"},
                "IssuingAuthority": {"value": "Federal Tax Authority"},
            }
        }

        result = evaluate_document_acceptance(
            "vat",
            payload,
            requested_company_name="FISCHER FIXING",
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 0)
        self.assertIn("company_name_mismatch", result.missing_fields)
        self.assertTrue(any("does not match uploaded VAT company name" in reason for reason in result.reasons))

    def test_vat_accepts_when_requested_company_matches_canonically(self) -> None:
        payload = {
            "results": {
                "TaxRegistrationNumber": {"value": "100382292900003"},
                "LegalNameEnglish": {"value": "Eurocon Building Industries FZE"},
                "IssuingAuthority": {"value": "Federal Tax Authority"},
            }
        }

        result = evaluate_document_acceptance(
            "vat",
            payload,
            requested_company_name="Eurocon Building Industries",
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 70)
        self.assertNotIn("company_name_mismatch", result.missing_fields)

    def test_vat_rejects_when_gpt_review_flags_fraud_risk(self) -> None:
        payload = {
            "results": {
                "TaxRegistrationNumber": {"value": "100382292900003"},
                "LegalNameEnglish": {"value": "GREEN LIFE EQUIPMENT TRADING"},
                "IssuingAuthority": {"value": "Federal Tax Authority"},
            },
            "gpt_review": {
                "is_consistent": False,
                "anomalies": ["Template-like layout and suspicious alterations."],
                "plausibility_score": 0.95,
                "reasoning": "Suspicious document.",
            },
        }

        result = evaluate_document_acceptance("vat", payload)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 0)
        self.assertIn("document_authenticity", result.missing_fields)
        self.assertTrue(any("fraud risk" in reason.lower() for reason in result.reasons))

    def test_bank_accepts_company_name(self) -> None:
        payload = {"results": {"AccountName": {"value": "CICON EPOXY AND STEEL CUTTING PLANT LLC SPC"}, "BankName": {"value": "Commercial Bank of Dubai"}}}

        result = evaluate_document_acceptance("bank", payload)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 75)
        self.assertEqual(result.missing_fields, [])

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=True)
    def test_bank_scores_logo_without_qr_or_verification_rules(self, mock_logo: object) -> None:
        payload = {"results": {"AccountName": {"value": "CICON EPOXY AND STEEL CUTTING PLANT LLC SPC"}, "BankName": {"value": "Commercial Bank of Dubai"}}}

        result = evaluate_document_acceptance("bank", payload, file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "review")
        self.assertEqual(result.score, 85)
        self.assertEqual(result.missing_fields, [])
        self.assertEqual(result.reasons, ["Logo present."])
        mock_logo.assert_called_once()

    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=False)
    def test_bank_ignores_qr_and_verification_signals(self, mock_logo: object) -> None:
        payload = {
            "results": {
                "AccountName": {"value": "CICON EPOXY AND STEEL CUTTING PLANT LLC SPC"},
                "BankName": {"value": "Commercial Bank of Dubai"},
            },
            "qr_codes": {"value": ["https://example.com/qr"]},
            "verification_urls": {"value": ["https://example.com/verify"]},
        }

        result = evaluate_document_acceptance("bank", payload, file_bytes=b"%PDF-1.4")
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 75)
        self.assertEqual(result.reasons, ["Logo not found."])
        mock_logo.assert_called_once()

    def test_bank_rejects_missing_bank_name(self) -> None:
        payload = {"results": {}}

        result = evaluate_document_acceptance("bank", payload)
        self.assertEqual(result.status, "rejected")
        self.assertIn("bank_name", result.missing_fields)

    def test_bank_rejects_when_requested_company_does_not_match(self) -> None:
        payload = {
            "results": {
                "AccountName": {"value": "Eurocon Building Industries FZE"},
                "BankName": {"value": "Commercial Bank of Dubai"},
                "AccountNumber": {"value": "1000078384"},
                "IBAN": {"value": "AE030230000001000078384"},
                "IssuingAuthority": {"value": "Commercial Bank of Dubai"},
            }
        }

        result = evaluate_document_acceptance(
            "bank",
            payload,
            requested_company_name="FISCHER FIXING",
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 0)
        self.assertIn("company_name_mismatch", result.missing_fields)
        self.assertTrue(any("does not match uploaded bank document company name" in reason for reason in result.reasons))

    def test_bank_accepts_when_requested_company_matches_canonically(self) -> None:
        payload = {
            "results": {
                "AccountName": {"value": "Eurocon Building Industries FZE"},
                "BankName": {"value": "Commercial Bank of Dubai"},
                "AccountNumber": {"value": "1000078384"},
                "IBAN": {"value": "AE030230000001000078384"},
                "IssuingAuthority": {"value": "Commercial Bank of Dubai"},
            }
        }

        result = evaluate_document_acceptance(
            "bank",
            payload,
            requested_company_name="Eurocon Building Industries",
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 75)
        self.assertNotIn("company_name_mismatch", result.missing_fields)

    def test_vat_scores_issuing_authority_bonus(self) -> None:
        payload = {
            "results": {
                "TaxRegistrationNumber": {"value": "100382292900003"},
                "LegalNameEnglish": {"value": "GREEN LIFE EQUIPMENT TRADING"},
                "IssuingAuthority": {"value": "Federal Tax Authority"},
            }
        }

        result = evaluate_document_acceptance("vat", payload)
        self.assertEqual(result.status, "rejected")
        self.assertGreaterEqual(result.score, 70)
        self.assertTrue(any("Issuing authority present" in reason for reason in result.reasons))

    def test_bank_scores_issuing_authority_bonus(self) -> None:
        payload = {
            "results": {
                "AccountName": {"value": "Eurocon Building Industries FZE"},
                "BankName": {"value": "Commercial Bank of Dubai"},
                "AccountNumber": {"value": "1000078384"},
                "IBAN": {"value": "AE030230000001000078384"},
                "IssuingAuthority": {"value": "Commercial Bank of Dubai"},
            }
        }

        result = evaluate_document_acceptance("bank", payload)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 75)
        self.assertEqual(result.reasons, [])

    def test_bank_rejects_when_gpt_review_flags_fraud_risk(self) -> None:
        payload = {
            "results": {
                "AccountName": {"value": "Eurocon Building Industries FZE"},
                "BankName": {"value": "Commercial Bank of Dubai"},
                "AccountNumber": {"value": "1000078384"},
                "IBAN": {"value": "AE030230000001000078384"},
                "IssuingAuthority": {"value": "Commercial Bank of Dubai"},
            },
            "gpt_review": {
                "is_consistent": False,
                "anomalies": ["Fake-looking bank letter and inconsistent issuer details."],
                "plausibility_score": 0.99,
                "reasoning": "Suspicious document.",
            },
        }

        result = evaluate_document_acceptance("bank", payload)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 0)
        self.assertIn("document_authenticity", result.missing_fields)
        self.assertTrue(any("fraud risk" in reason.lower() for reason in result.reasons))

    def test_response_wrapper_returns_frontend_shape(self) -> None:
        payload = {
            "results": {
                "TaxRegistrationNumber": {"value": "100382292900003"},
                "LegalNameEnglish": {"value": "GREEN LIFE EQUIPMENT TRADING"},
                "IssuingAuthority": {"value": "Federal Tax Authority"},
            }
        }

        response = build_document_acceptance_response("vat", payload)
        self.assertEqual(response["status"], "rejected")
        self.assertFalse(response["acceptable"])
        self.assertEqual(response["document_type"], "vat")
        self.assertEqual(response["missing_fields"], [])
        self.assertIsNone(response["expiry_date"])
        self.assertIsNone(response["is_expired"])

    def test_acceptance_prefers_llm_document_type_over_route(self) -> None:
        payload = {
            "results": {
                "TaxRegistrationNumber": {"value": "100382292900003"},
                "LegalNameEnglish": {"value": "GREEN LIFE EQUIPMENT TRADING"},
                "IssuingAuthority": {"value": "Federal Tax Authority"},
            },
            "llm_extraction": {"document_type": "vat"},
        }

        result = evaluate_document_acceptance("trade", payload)
        self.assertEqual(result.document_type, "vat")
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.score, 70)


if __name__ == "__main__":
    unittest.main()
