import unittest
from unittest.mock import patch

from app.domain.document_analysis.profiles import BANK_PROFILE, VAT_PROFILE
from app.infrastructure.document_qr_extraction import _extract_urls_from_text
from app.use_cases.document_analysis_extras import build_trade_license_extras, extract_qr_codes
from app.use_cases.document_analysis import (
    AnalysisOutcome,
    _apply_bank_account_name_fallback,
    _apply_vat_analysis_fallback,
    build_document_analysis_response,
    build_trade_license_response,
)
from app.use_cases.upload_blob import _with_success_metadata


class DocumentAnalysisContractsTest(unittest.TestCase):
    def test_bank_query_fields_are_capped_at_20(self) -> None:
        self.assertLessEqual(len(BANK_PROFILE.query_fields), 20)

    def test_vat_response_keeps_existing_tax_registration_number(self) -> None:
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={
                "contents": [
                    {
                        "fields": {
                            "TaxRegistrationNumber": {
                                "type": "string",
                                "valueString": "100382292900003",
                                "confidence": 0.82,
                            },
                            "LegalNameEnglish": {
                                "type": "string",
                                "valueString": "GREEN LIFE EQUIPMENT TRADING",
                                "confidence": 0.785,
                            },
                        }
                    }
                ]
            },
            model_id="prebuilt-layout",
            api_version="2025-11-01",
            file_name="vat.pdf",
            container="bronze",
            blob_name="vat.pdf",
            upload_skipped=True,
        )

        payload = build_document_analysis_response(outcome, VAT_PROFILE)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["source"], "document_intelligence")
        self.assertEqual(payload["origin"], "document_intelligence")
        self.assertEqual(payload["source_type"], "document_intelligence")
        self.assertIn("TaxRegistrationNumber", payload["results"])

    def test_trade_license_response_drops_arabic_name_values(self) -> None:
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={
                "contents": [
                    {
                        "fields": {
                            "CompanyName": {
                                "type": "string",
                                "valueString": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)",
                                "confidence": 0.89,
                            },
                            "BusinessName": {
                                "type": "string",
                                "valueString": "شركة مركز المعدات الإنشائية (ذ.م.م)",
                                "confidence": 0.91,
                            },
                            "TradeNameEnglish": {
                                "type": "string",
                                "valueString": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)",
                                "confidence": 0.88,
                            },
                        }
                    }
                ]
            },
            model_id="prebuilt-layout",
            api_version="2025-11-01",
            file_name="trade.pdf",
            container="bronze",
            blob_name="trade.pdf",
            upload_skipped=True,
        )

        payload = build_trade_license_response(outcome, ["CompanyName", "BusinessName", "TradeNameEnglish"])
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["source"], "document_intelligence")
        self.assertEqual(payload["origin"], "document_intelligence")
        self.assertEqual(payload["source_type"], "document_intelligence")
        self.assertIn("CompanyName", payload["results"])
        self.assertNotIn("BusinessName", payload["results"])
        self.assertIn("TradeNameEnglish", payload["results"])

    def test_trade_license_response_drops_location_only_business_name(self) -> None:
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={
                "contents": [
                    {
                        "fields": {
                            "TradeName": {
                                "type": "string",
                                "valueString": "GREEN LIFE EQUIPMENT TRADING",
                                "confidence": 0.95,
                            },
                            "BusinessName": {
                                "type": "string",
                                "valueString": "Abu Dhabi",
                                "confidence": 0.91,
                            },
                            "TradeNameEnglish": {
                                "type": "string",
                                "valueString": "L.L.C.",
                                "confidence": 0.88,
                            },
                        }
                    }
                ]
            },
            model_id="prebuilt-layout",
            api_version="2025-11-01",
            file_name="trade.pdf",
            container="bronze",
            blob_name="trade.pdf",
            upload_skipped=True,
        )

        payload = build_trade_license_response(outcome, ["TradeName", "BusinessName", "TradeNameEnglish"])
        self.assertEqual(payload["status"], "success")
        self.assertIn("TradeName", payload["results"])
        self.assertNotIn("BusinessName", payload["results"])
        self.assertNotIn("TradeNameEnglish", payload["results"])

    def test_trade_license_response_strips_legal_suffix_from_trade_name(self) -> None:
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={
                "contents": [
                    {
                        "fields": {
                            "TradeName": {
                                "type": "string",
                                "valueString": "GREEN LIFE EQUIPMENT TRADING - SOLE PROPRIETORSHIP L.L.C.",
                                "confidence": 0.96,
                            }
                        }
                    }
                ]
            },
            model_id="prebuilt-layout",
            api_version="2025-11-01",
            file_name="trade.pdf",
            container="bronze",
            blob_name="trade.pdf",
            upload_skipped=True,
        )

        payload = build_trade_license_response(outcome, ["TradeName"])
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["results"]["TradeName"]["value"], "GREEN LIFE EQUIPMENT TRADING")

    def test_trade_license_response_strips_additional_legal_suffix_terms(self) -> None:
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={
                "contents": [
                    {
                        "fields": {
                            "TradeName": {
                                "type": "string",
                                "valueString": "GREEN LIFE EQUIPMENT TRADING - SOLE PROPRIETORSHIP",
                                "confidence": 0.96,
                            }
                        }
                    }
                ]
            },
            model_id="prebuilt-layout",
            api_version="2025-11-01",
            file_name="trade.pdf",
            container="bronze",
            blob_name="trade.pdf",
            upload_skipped=True,
        )

        payload = build_trade_license_response(outcome, ["TradeName"])
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["results"]["TradeName"]["value"], "GREEN LIFE EQUIPMENT TRADING")

    def test_trade_license_response_splits_merged_unified_numbers(self) -> None:
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={
                "contents": [
                    {
                        "fields": {
                            "LicenceNumber": {
                                "type": "string",
                                "valueString": "101-2021-100011570 501-2010-100077987",
                                "confidence": 0.31,
                            }
                        }
                    }
                ]
            },
            model_id="prebuilt-layout",
            api_version="2025-11-01",
            file_name="trade.pdf",
            container="bronze",
            blob_name="trade.pdf",
            upload_skipped=True,
        )

        payload = build_trade_license_response(outcome, ["LicenceNumber", "UnifiedRegistrationNo", "UnifiedLicenceNo"])
        self.assertEqual(payload["status"], "success")
        self.assertNotIn("LicenceNumber", payload["results"])
        self.assertEqual(payload["results"]["UnifiedRegistrationNo"]["value"], "101-2021-100011570")
        self.assertEqual(payload["results"]["UnifiedLicenceNo"]["value"], "501-2010-100077987")

    def test_vat_fallback_adds_tax_registration_number(self) -> None:
        payload = {
            "status": "success",
            "score": 0.785,
            "results": {
                "LegalNameEnglish": {"value": "GREEN LIFE EQUIPMENT TRADING", "confidence": 0.785}
            },
        }
        with patch("app.use_cases.document_analysis_fallbacks.extract_tax_registration_number_from_pdf", return_value="100382292900003"):
            result = _apply_vat_analysis_fallback(payload, b"pdf-bytes", "application/pdf")
        self.assertEqual(result["results"]["TaxRegistrationNumber"]["value"], "100382292900003")

    def test_bank_fallback_adds_account_name(self) -> None:
        payload = {
            "status": "success",
            "score": 0.915,
            "results": {
                "BankName": {"value": "ARABBANK", "confidence": 0.92},
                "IBAN": {"value": "AB240090004001561093500", "confidence": 0.91},
            },
        }
        with patch("app.use_cases.document_analysis_fallbacks.extract_bank_account_name_from_pdf", return_value="CICON EPOXY AND STEEL CUTTING PLANT LLC SPC"):
            result = _apply_bank_account_name_fallback(payload, b"pdf-bytes")
        self.assertEqual(result["results"]["AccountName"]["value"], "CICON EPOXY AND STEEL CUTTING PLANT LLC SPC")

    def test_qr_code_extraction_finds_nested_barcodes(self) -> None:
        raw_result = {
            "contents": [
                {
                    "barcodes": [
                        {"kind": "qrCode", "value": "https://example.com/qr-1"},
                        {"kind": "code128", "value": "ignore-me"},
                    ]
                }
            ]
        }
        self.assertEqual(extract_qr_codes(raw_result), ["https://example.com/qr-1"])

    def test_trade_license_extras_include_qr_codes(self) -> None:
        extras = build_trade_license_extras(
            {"contents": [{"barcodes": [{"kind": "qr", "value": "https://example.com"}]}]},
            {"TradeNameEnglish": {"value": "ABC", "confidence": 0.9}},
        )
        self.assertEqual(extras["qr_codes"]["value"], ["https://example.com"])
        self.assertEqual(extras["verification_urls"]["value"], ["https://example.com"])
        self.assertNotIn("gpt_review", extras)

    def test_qr_url_fallback_normalizes_www_links(self) -> None:
        text = "To verify the license visit www.adra.gov.ae for details."
        self.assertEqual(_extract_urls_from_text(text), ["https://www.adra.gov.ae"])

    @patch("app.use_cases.document_analysis_extras.extract_verification_urls_from_pdf", return_value=["https://www.adra.gov.ae"])
    def test_trade_license_extras_include_verification_urls(self, mock_urls) -> None:
        extras = build_trade_license_extras({}, {"TradeNameEnglish": {"value": "ABC", "confidence": 0.9}}, file_bytes=b"pdf-bytes")
        self.assertEqual(extras["verification_urls"]["value"], ["https://www.adra.gov.ae"])
        self.assertEqual(extras["verification_urls"]["confidence"], 0.95)
        mock_urls.assert_called_once_with(b"pdf-bytes")

    @patch("app.use_cases.document_analysis_extras.extract_qr_codes_from_pdf", return_value=["https://example.com/qr-from-pdf"])
    def test_trade_license_extras_fallback_to_pdf_bytes_for_qr(self, mock_qr_from_pdf) -> None:
        extras = build_trade_license_extras({}, {"TradeNameEnglish": {"value": "ABC", "confidence": 0.9}}, file_bytes=b"pdf-bytes")
        self.assertEqual(extras["qr_codes"]["value"], ["https://example.com/qr-from-pdf"])
        self.assertEqual(extras["qr_codes"]["confidence"], 0.95)
        mock_qr_from_pdf.assert_called_once_with(b"pdf-bytes")

    @patch("app.use_cases.document_analysis_extras.document_review_openai_endpoint", return_value="https://example.openai.azure.com/")
    @patch("app.use_cases.document_analysis_extras.document_review_openai_api_key", return_value="secret-key")
    @patch("app.use_cases.document_analysis_extras.document_review_openai_api_version", return_value="2025-04-01-preview")
    @patch("app.use_cases.document_analysis_extras.document_review_openai_deployment_name", return_value="gpt-4o-mini")
    @patch("app.use_cases.document_analysis_extras.AzureOpenAI")
    def test_trade_license_extras_include_gpt_review_when_openai_is_available(self, mock_azure_openai, *_patches) -> None:
        client = mock_azure_openai.return_value
        client.chat.completions.create.return_value.choices = [
            type(
                "Choice",
                (),
                {"message": type("Message", (), {"content": '{"is_consistent": true, "anomalies": [], "plausibility_score": 0.98, "reasoning": "Looks consistent."}'})()},
            )
        ]

        extras = build_trade_license_extras(
            {"contents": [{"barcodes": [{"kind": "qr", "value": "https://example.com"}]}]},
            {"TradeNameEnglish": {"value": "ABC", "confidence": 0.9}},
        )

        self.assertEqual(extras["qr_codes"]["value"], ["https://example.com"])
        self.assertEqual(extras["gpt_review"]["is_consistent"], True)
        self.assertEqual(extras["gpt_review"]["plausibility_score"], 0.98)

    def test_upload_blob_response_includes_storage_source(self) -> None:
        payload = _with_success_metadata({"container": "vendor-docs"}, "sample.pdf", "trade")
        self.assertEqual(payload["source"], "storage")
        self.assertEqual(payload["origin"], "storage")
        self.assertEqual(payload["source_type"], "storage")
        self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
