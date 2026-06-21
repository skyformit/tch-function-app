import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.domain.document_analysis.profiles import BANK_PROFILE, VAT_PROFILE
from app.infrastructure.document_qr_extraction import _extract_urls_from_text
from app.use_cases.document_analysis_extras import build_trade_license_extras, extract_qr_codes, _raw_result_content_only, project_llm_extraction_fields
from app.use_cases.document_analysis import (
    AnalysisOutcome,
    _apply_bank_account_name_fallback,
    _apply_vat_analysis_fallback,
    build_document_analysis_response,
    build_trade_license_response,
)
from app.use_cases.document_analysis_routes import _route_payload
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

    def test_raw_result_content_only_returns_content_field(self) -> None:
        raw_result = {
            "content": "Company Name: ABC Trading LLC",
            "contents": [{"fields": {"TradeName": {"valueString": "ABC Trading LLC"}}}],
            "documents": [{"fields": {"TradeName": {"valueString": "ABC Trading LLC"}}}],
        }
        self.assertEqual(_raw_result_content_only(raw_result), "Company Name: ABC Trading LLC")

    def test_raw_result_content_only_returns_empty_string_when_missing(self) -> None:
        self.assertEqual(_raw_result_content_only({"documents": []}), "")
        self.assertEqual(_raw_result_content_only("plain text"), "")

    def test_project_llm_extraction_fields_maps_vat_and_bank(self) -> None:
        vat_projection = project_llm_extraction_fields(
            {
                "document_type": "vat",
                "vat_number": {"value": "100042630200003", "confidence": 0.99},
                "company_name": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C)", "confidence": 0.99},
            }
        )
        bank_projection = project_llm_extraction_fields(
            {
                "document_type": "bank",
                "bank_name": {"value": "Commercial Bank of Dubai", "confidence": 0.99},
                "account_number": {"value": "1000078384", "confidence": 0.99},
                "iban": {"value": "AE030230000001000078384", "confidence": 0.99},
            }
        )
        self.assertEqual(vat_projection["TaxRegistrationNumber"]["value"], "100042630200003")
        self.assertEqual(vat_projection["LegalNameEnglish"]["value"], "CONSTRUCTION MACHINERY CENTER CO.(L.L.C)")
        self.assertEqual(bank_projection["BankName"]["value"], "Commercial Bank of Dubai")
        self.assertEqual(bank_projection["AccountNumber"]["value"], "1000078384")
        self.assertEqual(bank_projection["IBAN"]["value"], "AE030230000001000078384")

    @patch(
        "app.use_cases.document_analysis_extras.review_and_extract_with_azure_openai",
        return_value={
            "gpt_review": {"is_consistent": True, "anomalies": [], "plausibility_score": 1.0, "reasoning": "Looks consistent."},
            "llm_extraction": {"document_type": "unknown"},
        },
    )
    def test_trade_license_extras_include_qr_codes(self, mock_combined) -> None:
        extras = build_trade_license_extras(
            {"contents": [{"barcodes": [{"kind": "qr", "value": "https://example.com"}]}]},
            {"TradeNameEnglish": {"value": "ABC", "confidence": 0.9}},
        )
        self.assertEqual(extras["qr_codes"]["value"], ["https://example.com"])
        self.assertEqual(extras["verification_urls"]["value"], ["https://example.com"])
        self.assertIn("gpt_review", extras)
        self.assertEqual(extras["gpt_review"]["is_consistent"], True)
        self.assertIn("llm_extraction", extras)
        self.assertEqual(extras["llm_extraction"]["document_type"], "unknown")
        mock_combined.assert_called_once()

    def test_qr_url_fallback_normalizes_www_links(self) -> None:
        text = "To verify the license visit www.adra.gov.ae for details."
        self.assertEqual(_extract_urls_from_text(text), ["https://www.adra.gov.ae"])

    @patch(
        "app.use_cases.document_analysis_extras.review_and_extract_with_azure_openai",
        return_value={
            "gpt_review": {"is_consistent": True, "anomalies": [], "plausibility_score": 1.0, "reasoning": "Looks consistent."},
            "llm_extraction": {"document_type": "unknown"},
        },
    )
    @patch("app.use_cases.document_analysis_extras.extract_verification_urls_from_pdf", return_value=["https://www.adra.gov.ae"])
    def test_trade_license_extras_include_verification_urls(self, mock_urls, mock_combined) -> None:
        extras = build_trade_license_extras({}, {"TradeNameEnglish": {"value": "ABC", "confidence": 0.9}}, file_bytes=b"pdf-bytes")
        self.assertEqual(extras["verification_urls"]["value"], ["https://www.adra.gov.ae"])
        self.assertEqual(extras["verification_urls"]["confidence"], 0.95)
        mock_urls.assert_called_once_with(b"pdf-bytes")
        mock_combined.assert_called_once()

    @patch(
        "app.use_cases.document_analysis_extras.review_and_extract_with_azure_openai",
        return_value={
            "gpt_review": {"is_consistent": True, "anomalies": [], "plausibility_score": 1.0, "reasoning": "Looks consistent."},
            "llm_extraction": {"document_type": "unknown"},
        },
    )
    @patch("app.use_cases.document_analysis_extras.extract_qr_codes_from_pdf", return_value=["https://example.com/qr-from-pdf"])
    def test_trade_license_extras_fallback_to_pdf_bytes_for_qr(self, mock_qr_from_pdf, mock_combined) -> None:
        extras = build_trade_license_extras({}, {"TradeNameEnglish": {"value": "ABC", "confidence": 0.9}}, file_bytes=b"pdf-bytes")
        self.assertEqual(extras["qr_codes"]["value"], ["https://example.com/qr-from-pdf"])
        self.assertEqual(extras["qr_codes"]["confidence"], 0.95)
        mock_qr_from_pdf.assert_called_once_with(b"pdf-bytes")
        mock_combined.assert_called_once()

    @patch(
        "app.use_cases.document_analysis_extras.review_and_extract_with_azure_openai",
        return_value={
            "gpt_review": {"is_consistent": True, "anomalies": [], "plausibility_score": 0.98, "reasoning": "Looks consistent."},
            "llm_extraction": {"document_type": "trade", "trade_license_number": {"value": "CN-1067688", "confidence": 0.95}},
        },
    )
    def test_trade_license_extras_include_llm_extraction_when_openai_is_available(self, mock_combined) -> None:
        extras = build_trade_license_extras(
            {"contents": [{"barcodes": [{"kind": "qr", "value": "https://example.com"}]}]},
            {"TradeNameEnglish": {"value": "ABC", "confidence": 0.9}},
        )

        self.assertEqual(extras["qr_codes"]["value"], ["https://example.com"])
        self.assertEqual(extras["gpt_review"]["is_consistent"], True)
        self.assertEqual(extras["gpt_review"]["plausibility_score"], 0.98)
        self.assertEqual(extras["llm_extraction"]["document_type"], "trade")
        self.assertEqual(extras["llm_extraction"]["trade_license_number"]["value"], "CN-1067688")
        mock_combined.assert_called_once()

    @patch("app.use_cases.document_analysis_routes.review_with_azure_openai", return_value={"is_consistent": True, "anomalies": [], "plausibility_score": 1.0, "reasoning": "Looks consistent."})
    @patch("app.use_cases.document_analysis_routes.build_trade_license_response")
    @patch("app.use_cases.document_analysis_routes.build_trade_license_extras")
    @patch("app.use_cases.document_acceptance.extract_logo_presence_from_pdf", return_value=True)
    def test_trade_route_payload_includes_document_acceptance(self, mock_logo, mock_extras, mock_trade_response, mock_gpt_review) -> None:
        mock_trade_response.return_value = {
            "status": "success",
            "score": 0.9,
            "results": {
                "TradeName": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)", "confidence": 0.95},
                "LicenseNo": {"value": "206558", "confidence": 0.95},
                "ExpiryDate": {"value": "06/04/2027", "confidence": 0.95},
                "LicenceActivities": {"value": "Construction Equipment Trading", "confidence": 0.95},
            },
            "source": "document_intelligence",
            "origin": "document_intelligence",
            "source_type": "document_intelligence",
        }
        mock_extras.return_value = {
            "qr_codes": {"value": ["https://example.com/qr"], "confidence": 0.95},
            "verification_urls": {"value": ["https://example.com/verify"], "confidence": 0.95},
            "gpt_review": {"is_consistent": True, "anomalies": [], "plausibility_score": 1.0, "reasoning": "Looks consistent."},
            "llm_extraction": {"document_type": "trade", "company_name": {"value": "CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)", "confidence": 0.95}},
        }
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={"content": "Company Name: CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)", "contents": [{"fields": {}}]},
            model_id="prebuilt-layout",
            api_version="2025-11-01",
            file_name="trade.pdf",
            container="bronze",
            blob_name="trade.pdf",
            upload_skipped=True,
        )
        payload = _route_payload(
            profile=None,
            is_trade=True,
            outcome=outcome,
            file_bytes=b"%PDF-1.4",
            content_type="application/pdf",
            target_fields=["TradeName", "LicenseNo", "ExpiryDate", "LicenceActivities"],
        )
        self.assertIn("document_acceptance", payload)
        self.assertEqual(payload["document_acceptance"]["status"], "approved")
        self.assertEqual(payload["document_acceptance"]["score"], 100)
        self.assertEqual(payload["document_acceptance"]["acceptable"], True)
        self.assertEqual(payload["raw_results"], "Company Name: CONSTRUCTION MACHINERY CENTER CO.(L.L.C.)")
        self.assertIn("gpt_review", payload)
        self.assertEqual(payload["gpt_review"]["is_consistent"], True)
        mock_extras.assert_called_once()
        mock_logo.assert_called_once()
        mock_gpt_review.assert_called_once()

    @patch("app.use_cases.document_analysis_routes.review_with_azure_openai", return_value={"is_consistent": True, "anomalies": [], "plausibility_score": 0.95, "reasoning": "Looks consistent."})
    @patch("app.use_cases.document_analysis_routes.extract_document_fields_with_azure_openai", return_value={"document_type": "vat", "vat_number": {"value": "100382292900003", "confidence": 0.99}})
    @patch("app.use_cases.document_analysis_routes.build_document_analysis_response")
    @patch("app.use_cases.document_analysis_routes._apply_vat_analysis_fallback", side_effect=lambda payload, *_args: payload)
    def test_vat_route_payload_includes_llm_extraction(self, mock_fallback, mock_build_response, mock_llm_extraction, mock_gpt_review) -> None:
        mock_build_response.return_value = {"status": "success", "score": 0.91, "results": {"TaxRegistrationNumber": {"value": "100382292900003"}}, "source": "document_intelligence", "origin": "document_intelligence", "source_type": "document_intelligence"}
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={"contents": [{"fields": {}}]},
            model_id="prebuilt-layout",
            api_version="2025-11-01",
            file_name="vat.pdf",
            container="bronze",
            blob_name="vat.pdf",
            upload_skipped=True,
        )
        profile = SimpleNamespace(route_name="ValidateVAT")
        payload = _route_payload(profile, False, outcome, b"%PDF-1.4", "application/pdf", ["TaxRegistrationNumber", "LegalNameEnglish"])
        self.assertIn("llm_extraction", payload)
        self.assertEqual(payload["llm_extraction"]["document_type"], "vat")
        self.assertIn("gpt_review", payload)
        self.assertEqual(payload["gpt_review"]["is_consistent"], True)
        mock_llm_extraction.assert_called_once()
        mock_build_response.assert_called_once()
        mock_fallback.assert_called_once()
        mock_gpt_review.assert_called_once()

    @patch("app.use_cases.document_analysis_routes.review_with_azure_openai", return_value={"is_consistent": True, "anomalies": [], "plausibility_score": 0.95, "reasoning": "Looks consistent."})
    @patch("app.use_cases.document_analysis_routes.extract_document_fields_with_azure_openai", return_value={"document_type": "bank", "bank_name": {"value": "ARABBANK", "confidence": 0.99}})
    @patch("app.use_cases.document_analysis_routes.build_document_analysis_response")
    @patch("app.use_cases.document_analysis_routes._apply_bank_account_name_fallback", side_effect=lambda payload, *_args: payload)
    def test_bank_route_payload_includes_llm_extraction(self, mock_fallback, mock_build_response, mock_llm_extraction, mock_gpt_review) -> None:
        mock_build_response.return_value = {"status": "success", "score": 0.93, "results": {"AccountName": {"value": "CICON EPOXY AND STEEL CUTTING PLANT LLC SPC"}}, "source": "document_intelligence", "origin": "document_intelligence", "source_type": "document_intelligence"}
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={"contents": [{"fields": {}}]},
            model_id="prebuilt-layout",
            api_version="2025-11-01",
            file_name="bank.pdf",
            container="bronze",
            blob_name="bank.pdf",
            upload_skipped=True,
        )
        profile = SimpleNamespace(route_name="ValidateBankDocument")
        payload = _route_payload(profile, False, outcome, b"%PDF-1.4", "application/pdf", ["BankName", "AccountName"])
        self.assertIn("llm_extraction", payload)
        self.assertEqual(payload["llm_extraction"]["document_type"], "bank")
        self.assertIn("gpt_review", payload)
        self.assertEqual(payload["gpt_review"]["is_consistent"], True)
        mock_llm_extraction.assert_called_once()
        mock_build_response.assert_called_once()
        mock_fallback.assert_called_once()
        mock_gpt_review.assert_called_once()

    @patch("app.use_cases.document_analysis_routes.review_with_azure_openai", return_value={"is_consistent": True, "anomalies": [], "plausibility_score": 0.95, "reasoning": "Looks consistent."})
    @patch("app.use_cases.document_analysis_routes.extract_document_fields_with_azure_openai", return_value={"document_type": "vat", "vat_number": {"value": "100382292900003", "confidence": 0.99}})
    @patch("app.use_cases.document_analysis_routes.build_document_analysis_response")
    @patch("app.use_cases.document_analysis_routes._apply_vat_analysis_fallback", side_effect=lambda payload, *_args: payload)
    def test_vat_route_payload_includes_document_acceptance(self, mock_fallback, mock_build_response, mock_llm_extraction, mock_gpt_review) -> None:
        mock_build_response.return_value = {
            "status": "success",
            "score": 0.91,
            "results": {
                "TaxRegistrationNumber": {"value": "100382292900003"},
                "LegalNameEnglish": {"value": "GREEN LIFE EQUIPMENT TRADING"},
            },
            "source": "document_intelligence",
            "origin": "document_intelligence",
            "source_type": "document_intelligence",
        }
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={"contents": [{"fields": {}}]},
            model_id="prebuilt-layout",
            api_version="2025-11-01",
            file_name="vat.pdf",
            container="bronze",
            blob_name="vat.pdf",
            upload_skipped=True,
        )
        profile = SimpleNamespace(route_name="ValidateVAT")
        payload = _route_payload(profile, False, outcome, b"%PDF-1.4", "application/pdf", ["TaxRegistrationNumber", "LegalNameEnglish"])
        self.assertIn("document_acceptance", payload)
        self.assertEqual(payload["document_acceptance"]["status"], "approved")
        self.assertTrue(payload["document_acceptance"]["acceptable"])
        mock_llm_extraction.assert_called_once()
        mock_build_response.assert_called_once()
        mock_fallback.assert_called_once()
        mock_gpt_review.assert_called_once()

    @patch("app.use_cases.document_analysis_routes.review_with_azure_openai", return_value={"is_consistent": True, "anomalies": [], "plausibility_score": 0.95, "reasoning": "Looks consistent."})
    @patch("app.use_cases.document_analysis_routes.extract_document_fields_with_azure_openai", return_value={"document_type": "bank", "bank_name": {"value": "ARABBANK", "confidence": 0.99}})
    @patch("app.use_cases.document_analysis_routes.build_document_analysis_response")
    @patch("app.use_cases.document_analysis_routes._apply_bank_account_name_fallback", side_effect=lambda payload, *_args: payload)
    def test_bank_route_payload_includes_document_acceptance(self, mock_fallback, mock_build_response, mock_llm_extraction, mock_gpt_review) -> None:
        mock_build_response.return_value = {"status": "success", "score": 0.93, "results": {"AccountName": {"value": "CICON EPOXY AND STEEL CUTTING PLANT LLC SPC"}}, "source": "document_intelligence", "origin": "document_intelligence", "source_type": "document_intelligence"}
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={"contents": [{"fields": {}}]},
            model_id="prebuilt-layout",
            api_version="2025-11-01",
            file_name="bank.pdf",
            container="bronze",
            blob_name="bank.pdf",
            upload_skipped=True,
        )
        profile = SimpleNamespace(route_name="ValidateBankDocument")
        payload = _route_payload(profile, False, outcome, b"%PDF-1.4", "application/pdf", ["BankName", "AccountName"])
        self.assertIn("document_acceptance", payload)
        self.assertEqual(payload["document_acceptance"]["status"], "approved")
        self.assertTrue(payload["document_acceptance"]["acceptable"])
        mock_llm_extraction.assert_called_once()
        mock_build_response.assert_called_once()
        mock_fallback.assert_called_once()
        mock_gpt_review.assert_called_once()

    def test_upload_blob_response_includes_storage_source(self) -> None:
        payload = _with_success_metadata({"container": "vendor-docs"}, "sample.pdf", "trade")
        self.assertEqual(payload["source"], "storage")
        self.assertEqual(payload["origin"], "storage")
        self.assertEqual(payload["source_type"], "storage")
        self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
