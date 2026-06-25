from dataclasses import dataclass
import json
import os
from pathlib import Path


def _load_local_settings() -> None:
    local_settings_path = Path(__file__).resolve().parents[2] / "local.settings.json"
    if not local_settings_path.exists():
        return
    try:
        payload = json.loads(local_settings_path.read_text())
    except Exception:
        return
    values = payload.get("Values")
    if not isinstance(values, dict):
        return
    for key, value in values.items():
        if isinstance(key, str) and key and os.getenv(key) is None and value is not None:
            os.environ[key] = str(value)


_load_local_settings()


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_list(name: str, default) -> tuple[str, ...]:
    raw_value = _env(name)
    if not raw_value:
        return tuple(default)
    values = [item.strip().lower() for item in raw_value.split(",")]
    return tuple(item for item in values if item)


@dataclass(frozen=True)
class Settings:
    foundry_project_endpoint: str = _env("FOUNDRY_PROJECT_ENDPOINT")
    foundry_token_scope: str = _env("FOUNDRY_TOKEN_SCOPE", "https://ai.azure.com/.default")
    general_bot_agent_id: str = _env("GENERAL_BOT_AGENT_ID")
    vendor_approval_workflow_url: str = _env("VENDOR_APPROVAL_WORKFLOW_URL")
    renewal_vendor_approval_workflow_url: str = _env("RENEWAL_VENDOR_APPROVAL_WORKFLOW_URL")
    source_api_url: str = _env("SOURCE_API_URL")
    source_api_key: str = _env("SOURCE_API_KEY")
    source_api_key_header: str = _env("SOURCE_API_KEY_HEADER", "X-Api-Key")
    source_since_param: str = _env("SOURCE_SINCE_PARAM", "since")
    source_cursor_param: str = _env("SOURCE_CURSOR_PARAM", "cursor")
    source_state_container: str = _env("SOURCE_STATE_CONTAINER")
    source_state_blob_name: str = _env("SOURCE_STATE_BLOB_NAME")
    source_state_mode: str = _env("SOURCE_STATE_MODE", "memory")
    source_api_timeout_seconds: str = _env("SOURCE_API_TIMEOUT_SECONDS", "5")
    enable_tbms_lookup: str = _env("ENABLE_TBMS_LOOKUP", "false")
    validate_login_url: str = _env("VALIDATE_LOGIN_URL")
    validate_login_api_key: str = _env("VALIDATE_LOGIN_API_KEY")
    validate_login_api_key_header: str = _env("VALIDATE_LOGIN_API_KEY_HEADER", "x-api-key")
    validate_login_username: str = _env("VALIDATE_LOGIN_USERNAME")
    validate_login_password: str = _env("VALIDATE_LOGIN_PASSWORD")
    validate_login_verify_ssl: str = _env("VALIDATE_LOGIN_VERIFY_SSL", "true")
    general_bot_system_prompt: str = _env("GENERAL_BOT_SYSTEM_PROMPT")
    lookup_routing_prompt: str = _env("LOOKUP_ROUTING_PROMPT")
    lookup_classification_prompt: str = _env("LOOKUP_CLASSIFICATION_PROMPT")
    lookup_company_hints: tuple[str, ...] = _env_list(
        "LOOKUP_COMPANY_HINTS",
        ("llc", "l.l.c", "fze", "fzco", "ltd", "company", "co.", "co ", "group", "est", "est.", "branch", "holding"),
    )
    lookup_business_only_hints: tuple[str, ...] = _env_list(
        "LOOKUP_BUSINESS_ONLY_HINTS",
        ("trading", "industries", "industrial", "enterprise", "enterprises"),
    )
    company_name_trailing_suffixes: tuple[str, ...] = _env_list(
        "COMPANY_NAME_TRAILING_SUFFIXES",
        ("trading", "llc", "l.l.c", "co.", "co", "company", "corporation", "corp.", "corp", "branch", "establishment", "sole proprietorship", "limited", "ltd", "fze", "fzc", "pjsc"),
    )
    azure_storage_account_url: str = _env("AZURE_STORAGE_ACCOUNT_URL")
    azure_storage_container: str = _env("AZURE_STORAGE_CONTAINER")
    azure_storage_prefix: str = _env("AZURE_STORAGE_PREFIX")
    azure_storage_connection_string: str = _env("AZURE_STORAGE_CONNECTION_STRING")


settings = Settings()


def foundry_project_endpoint() -> str:
    return settings.foundry_project_endpoint


def foundry_agent_name() -> str:
    return settings.vendor_approval_workflow_url


def foundry_token_scope() -> str:
    return settings.foundry_token_scope


def general_bot_agent_id() -> str:
    return settings.general_bot_agent_id


def vendor_approval_workflow_url() -> str:
    return settings.vendor_approval_workflow_url


def renewal_vendor_approval_workflow_url() -> str:
    return settings.renewal_vendor_approval_workflow_url


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


def enable_tbms_lookup() -> bool:
    return settings.enable_tbms_lookup.lower() in {"1", "true", "yes", "on"}

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


def validate_login_verify_ssl() -> bool:
    return settings.validate_login_verify_ssl.lower() in {"1", "true", "yes", "on"}


def general_bot_system_prompt() -> str:
    return settings.general_bot_system_prompt


def lookup_routing_prompt() -> str:
    return settings.lookup_routing_prompt


def lookup_classification_prompt() -> str:
    return settings.lookup_classification_prompt


def lookup_company_hints() -> tuple[str, ...]:
    return settings.lookup_company_hints


def lookup_business_only_hints() -> tuple[str, ...]:
    return settings.lookup_business_only_hints


def company_name_trailing_suffixes() -> tuple[str, ...]:
    return settings.company_name_trailing_suffixes
