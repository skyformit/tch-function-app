from dataclasses import dataclass
import os


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
    document_intelligence_timeout_seconds: str = _env("DOCUMENT_INTELLIGENCE_TIMEOUT_SECONDS", "60")
    document_intelligence_poll_interval_seconds: str = _env("DOCUMENT_INTELLIGENCE_POLL_INTERVAL_SECONDS", "2")
    content_understanding_endpoint: str = _env("CONTENT_UNDERSTANDING_ENDPOINT")
    content_understanding_key: str = _env("CONTENT_UNDERSTANDING_KEY")
    content_understanding_api_version: str = _env("CONTENT_UNDERSTANDING_API_VERSION", "2025-11-01")
    content_understanding_analyzer_id: str = _env("CONTENT_UNDERSTANDING_ANALYZER_ID", "prebuilt-documentFields")
    content_understanding_timeout_seconds: str = _env("CONTENT_UNDERSTANDING_TIMEOUT_SECONDS", "60")
    document_review_openai_endpoint: str = _env("DOCUMENT_REVIEW_OPENAI_ENDPOINT")
    document_review_openai_api_key: str = _env("DOCUMENT_REVIEW_OPENAI_API_KEY")
    document_review_openai_api_version: str = _env("DOCUMENT_REVIEW_OPENAI_API_VERSION", "2025-04-01-preview")
    document_review_openai_deployment_name: str = _env("DOCUMENT_REVIEW_OPENAI_DEPLOYMENT_NAME")


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
    try:
        return max(1, int(settings.document_intelligence_timeout_seconds))
    except ValueError:
        return 60


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
    try:
        return max(1, int(settings.content_understanding_timeout_seconds))
    except ValueError:
        return 60


def document_review_openai_endpoint() -> str:
    return settings.document_review_openai_endpoint


def document_review_openai_api_key() -> str:
    return settings.document_review_openai_api_key


def document_review_openai_api_version() -> str:
    return settings.document_review_openai_api_version


def document_review_openai_deployment_name() -> str:
    return settings.document_review_openai_deployment_name
