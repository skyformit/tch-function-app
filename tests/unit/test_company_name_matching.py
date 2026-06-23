import unittest

from app.use_cases.company_name_matching import compare_company_names, normalize_company_name


class CompanyNameMatchingTest(unittest.TestCase):
    def test_normalize_company_name_strips_common_suffixes(self) -> None:
        self.assertEqual(normalize_company_name("MODEC BUILDING MATERIALS TRADING (L.L.C.)"), "MODEC BUILDING MATERIALS")
        self.assertEqual(normalize_company_name("GALADARI TRUCKS & HEAVY EQUIPMENT COMPANY LIMITED"), "GALADARI TRUCKS & HEAVY EQUIPMENT")

    def test_compare_company_names_returns_normalized_match(self) -> None:
        result = compare_company_names("MODEC BUILDING MATERIALS TRADING", "MODEC BUILDING MATERIALS TRADING (L.L.C.)")
        self.assertTrue(result.exact_match)
        self.assertEqual(result.similarity_percent, 100.0)
        self.assertEqual(result.normalized1, "MODEC BUILDING MATERIALS")
        self.assertEqual(result.normalized2, "MODEC BUILDING MATERIALS")

    def test_compare_company_names_reports_similarity(self) -> None:
        result = compare_company_names(
            "GALADARI TRUCKS & HEAVY EQUIPMENT",
            "GALADARI TRUCKS & HEAVY EQUIPMENT COMPANY LIMITED",
        )
        self.assertTrue(result.exact_match)
        self.assertEqual(result.similarity_percent, 100.0)

    def test_compare_company_names_keeps_raw_values(self) -> None:
        result = compare_company_names("ABC TRADING", "ABC TRADING LLC")
        self.assertEqual(result.string1, "ABC TRADING")
        self.assertEqual(result.string2, "ABC TRADING LLC")


if __name__ == "__main__":
    unittest.main()
