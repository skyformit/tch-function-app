import unittest
from unittest.mock import patch

from app.domain.document_analysis.profiles import BANK_PROFILE, VAT_PROFILE
from app.use_cases.document_analysis import (
    AnalysisOutcome,
    _apply_bank_account_name_fallback,
    _apply_vat_analysis_fallback,
    build_document_analysis_response,
    build_trade_license_response,
)


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
        self.assertIn("TaxRegistrationNumber", payload["results"])

    def test_trade_license_response_drops_arabic_name_values(self) -> None:
        outcome = AnalysisOutcome(
            provider="document_intelligence",
            raw_result={
                "contents": [
                    {
                        "fields": {
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

        payload = build_trade_license_response(outcome, ["BusinessName", "TradeNameEnglish"])
        self.assertEqual(payload["status"], "success")
        self.assertNotIn("BusinessName", payload["results"])
        self.assertIn("TradeNameEnglish", payload["results"])

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


if __name__ == "__main__":
    unittest.main()
