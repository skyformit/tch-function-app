from dataclasses import dataclass
import os


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


@dataclass(frozen=True)
class Settings:
    foundry_project_endpoint: str = _env("FOUNDRY_PROJECT_ENDPOINT")
    foundry_agent_name: str = _env("FOUNDRY_AGENT_NAME")
    foundry_token_scope: str = _env("FOUNDRY_TOKEN_SCOPE", "https://ai.azure.com/.default")
    source_api_url: str = _env("SOURCE_API_URL")
    source_api_key: str = _env("SOURCE_API_KEY")
    source_api_key_header: str = _env("SOURCE_API_KEY_HEADER", "X-Api-Key")
    source_since_param: str = _env("SOURCE_SINCE_PARAM", "since")
    source_cursor_param: str = _env("SOURCE_CURSOR_PARAM", "cursor")
    source_state_container: str = _env("SOURCE_STATE_CONTAINER")
    source_state_blob_name: str = _env("SOURCE_STATE_BLOB_NAME")
    source_state_mode: str = _env("SOURCE_STATE_MODE", "memory")
    source_api_timeout_seconds: str = _env("SOURCE_API_TIMEOUT_SECONDS", "5")
    validate_login_url: str = _env("VALIDATE_LOGIN_URL")
    validate_login_api_key: str = _env("VALIDATE_LOGIN_API_KEY")
    validate_login_api_key_header: str = _env("VALIDATE_LOGIN_API_KEY_HEADER", "x-api-key")
    validate_login_username: str = _env("VALIDATE_LOGIN_USERNAME")
    validate_login_password: str = _env("VALIDATE_LOGIN_PASSWORD")
    validate_login_timeout_seconds: str = _env("VALIDATE_LOGIN_TIMEOUT_SECONDS", "30")
    validate_login_verify_ssl: str = _env("VALIDATE_LOGIN_VERIFY_SSL", "true")
    azure_storage_account_url: str = _env("AZURE_STORAGE_ACCOUNT_URL")
    azure_storage_container: str = _env("AZURE_STORAGE_CONTAINER")
    azure_storage_prefix: str = _env("AZURE_STORAGE_PREFIX")
    azure_storage_connection_string: str = _env("AZURE_STORAGE_CONNECTION_STRING")
    azure_storage_timeout_seconds: str = _env("AZURE_STORAGE_TIMEOUT_SECONDS", "60")
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


settings = Settings()


def source_api_url() -> str:
    return settings.source_api_url


def source_api_key() -> str:
    return settings.source_api_key


def source_api_key_header() -> str:
    return settings.source_api_key_header


def source_since_param() -> str:
    return settings.source_since_param


def source_cursor_param() -> str:
    return settings.source_cursor_param


def source_state_container() -> str:
    return settings.source_state_container


def source_state_blob_name() -> str:
    return settings.source_state_blob_name


def source_state_mode() -> str:
    return settings.source_state_mode


def source_api_timeout_seconds() -> float:
    try:
        return max(1.0, float(settings.source_api_timeout_seconds))
    except ValueError:
        return 5.0


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


def validate_login_url() -> str:
    return settings.validate_login_url


def validate_login_api_key() -> str:
    return settings.validate_login_api_key


def validate_login_api_key_header() -> str:
    return settings.validate_login_api_key_header


def validate_login_username() -> str:
    return settings.validate_login_username


def validate_login_password() -> str:
    return settings.validate_login_password


def validate_login_timeout_seconds() -> int:
    try:
        return max(1, int(settings.validate_login_timeout_seconds))
    except ValueError:
        return 30


def validate_login_verify_ssl() -> bool:
    return settings.validate_login_verify_ssl.lower() in {"1", "true", "yes", "on"}
