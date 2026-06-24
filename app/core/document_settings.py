from dataclasses import dataclass
import os

from app.core.config import source_api_timeout_seconds


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


@dataclass(frozen=True)
class DocumentSettings:
    document_analysis_provider: str = _env("DOCUMENT_ANALYSIS_PROVIDER", "document_intelligence")
    document_analysis_allow_analyze_without_upload: str = _env("DOCUMENT_ANALYSIS_ALLOW_ANALYZE_WITHOUT_UPLOAD", "false")
    document_analysis_debug_raw_keys: str = _env("DOCUMENT_ANALYSIS_DEBUG_RAW_KEYS", "false")
    document_intelligence_endpoint: str = _env("DOCUMENT_INTELLIGENCE_ENDPOINT")
    document_intelligence_key: str = _env("DOCUMENT_INTELLIGENCE_KEY")
    document_intelligence_api_version: str = _env("DOCUMENT_INTELLIGENCE_API_VERSION", "2025-11-01")
    document_intelligence_model_id: str = _env("DOCUMENT_INTELLIGENCE_MODEL_ID", "prebuilt-layout")
    document_intelligence_poll_interval_seconds: str = _env("DOCUMENT_INTELLIGENCE_POLL_INTERVAL_SECONDS", "2")
    content_understanding_endpoint: str = _env("CONTENT_UNDERSTANDING_ENDPOINT")
    content_understanding_key: str = _env("CONTENT_UNDERSTANDING_KEY")
    content_understanding_api_version: str = _env("CONTENT_UNDERSTANDING_API_VERSION", "2025-11-01")
    content_understanding_analyzer_id: str = _env("CONTENT_UNDERSTANDING_ANALYZER_ID", "prebuilt-documentFields")
    document_review_openai_endpoint: str = _env("DOCUMENT_REVIEW_OPENAI_ENDPOINT")
    document_review_openai_api_key: str = _env("DOCUMENT_REVIEW_OPENAI_API_KEY")
    document_review_openai_api_version: str = _env("DOCUMENT_REVIEW_OPENAI_API_VERSION", "2025-04-01-preview")
    document_review_openai_deployment_name: str = _env("DOCUMENT_REVIEW_OPENAI_DEPLOYMENT_NAME")
    document_review_openai_call_order: str = _env("DOCUMENT_REVIEW_OPENAI_CALL_ORDER", "review_first")
    document_review_openai_inter_call_delay_seconds: str = _env("DOCUMENT_REVIEW_OPENAI_INTER_CALL_DELAY_SECONDS", "0")
    document_review_openai_min_tokens: str = _env("DOCUMENT_REVIEW_OPENAI_MIN_TOKENS", "0")
    document_review_openai_max_tokens: str = _env("DOCUMENT_REVIEW_OPENAI_MAX_TOKENS", "4000")
    document_review_openai_system_prompt: str = _env(
        "DOCUMENT_REVIEW_OPENAI_SYSTEM_PROMPT",
        (
            "You are a document consistency and fraud-risk reviewer.\n\n"
            "You will receive extracted fields from a document such as a trade license, VAT certificate, or bank letter. "
            "Your task is to assess internal consistency and document plausibility from the fields provided.\n\n"
            "Do NOT use external knowledge or guess authenticity from memory. "
            "Do NOT penalize the document for being bilingual, having multiple official identifiers, or using different field names "
            "for the same concept unless the values clearly conflict.\n\n"
            "Review for:\n"
            "- missing mandatory fields\n"
            "- conflicting values across fields\n"
            "- impossible or logically inconsistent dates\n"
            "- placeholder/test data\n"
            "- obvious formatting corruption\n"
            "- duplicate fields with contradictory values\n"
            "- OCR or extraction noise that changes the meaning\n"
            "- suspicious, fake, templated, forged, or tampered-looking content\n"
            "- implausible combinations that reduce document trustworthiness\n\n"
            "Scoring rules:\n"
            "- 0.90 to 1.00 = highly consistent, no meaningful issues, no fraud suspicion\n"
            "- 0.70 to 0.89 = mostly consistent, minor extraction noise only\n"
            "- 0.40 to 0.69 = some inconsistencies or unclear fields, but still plausibly valid\n"
            "- 0.00 to 0.39 = major conflicts, implausible values, or strong signs of tampering/fraud\n\n"
            "Important:\n"
            "- A low-confidence field is NOT automatically suspicious.\n"
            "- Multiple identifiers can be valid if they are standard official numbers.\n"
            "- A future expiry date is valid if it is after the issue date and within a reasonable range.\n"
            "- If the document contains Arabic and English text, do not treat that as an anomaly by itself.\n"
            "- If the same concept appears in multiple fields, only flag it if the values conflict.\n\n"
            "- If a standard official issuing authority is present and plausible for the document type, treat it as supporting evidence, not as a suspicious anomaly.\n"
            "- Do not mark a document suspicious solely because one field looks imperfect, truncated, or OCR-corrupted (for example a broken email domain or a partially recognized authority name).\n"
            "- Examples of plausible authorities include a trade license authority such as a Department of Economy and Tourism / Department of Economic Development, a VAT authority such as the Federal Tax Authority, or a bank name / branch for bank documents.\n"
            "- Only lower plausibility sharply when multiple signals agree that the document is fake, tampered, template-like, or internally contradictory.\n"
            "- If fraud or tampering is suspected, explain it directly in anomalies and reasoning.\n\n"
            "Respond with ONLY a JSON object, no markdown fences, no preamble, in this exact shape:\n"
            '{"is_consistent": true|false, "anomalies": ["..."], "plausibility_score": 0.0-1.0, "reasoning": "short explanation"}'
        ),
    )


settings = DocumentSettings()


def document_analysis_provider() -> str:
    return settings.document_analysis_provider


def document_analysis_allow_analyze_without_upload() -> bool:
    return settings.document_analysis_allow_analyze_without_upload.lower() == "true"


def document_analysis_debug_raw_keys() -> bool:
    return settings.document_analysis_debug_raw_keys.lower() == "true"


def document_intelligence_endpoint() -> str:
    return settings.document_intelligence_endpoint


def document_intelligence_key() -> str:
    return settings.document_intelligence_key


def document_intelligence_api_version() -> str:
    return settings.document_intelligence_api_version


def document_intelligence_model_id() -> str:
    return settings.document_intelligence_model_id


def document_intelligence_timeout_seconds() -> int:
    return max(1, int(source_api_timeout_seconds()))


def document_intelligence_poll_interval_seconds() -> int:
    try:
        return max(1, int(settings.document_intelligence_poll_interval_seconds))
    except ValueError:
        return 2


def content_understanding_endpoint() -> str:
    return settings.content_understanding_endpoint


def content_understanding_key() -> str:
    return settings.content_understanding_key


def content_understanding_api_version() -> str:
    return settings.content_understanding_api_version


def content_understanding_analyzer_id() -> str:
    return settings.content_understanding_analyzer_id


def content_understanding_timeout_seconds() -> int:
    return max(1, int(source_api_timeout_seconds()))


def document_review_openai_endpoint() -> str:
    return settings.document_review_openai_endpoint


def document_review_openai_api_key() -> str:
    return settings.document_review_openai_api_key


def document_review_openai_api_version() -> str:
    return settings.document_review_openai_api_version


def document_review_openai_deployment_name() -> str:
    return settings.document_review_openai_deployment_name


def document_review_openai_call_order() -> str:
    return settings.document_review_openai_call_order


def document_review_openai_inter_call_delay_seconds() -> int:
    try:
        return max(0, int(settings.document_review_openai_inter_call_delay_seconds))
    except ValueError:
        return 0


def document_review_openai_min_tokens() -> int:
    try:
        return max(0, int(settings.document_review_openai_min_tokens))
    except ValueError:
        return 0


def document_review_openai_max_tokens() -> int:
    try:
        return max(1, int(settings.document_review_openai_max_tokens))
    except ValueError:
        return 4000


def document_review_openai_system_prompt() -> str:
    return settings.document_review_openai_system_prompt
