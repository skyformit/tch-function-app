from app.core.config import settings


def storage_account_url() -> str:
    return settings.azure_storage_account_url


def storage_container() -> str:
    return settings.azure_storage_container


def storage_prefix() -> str:
    return settings.azure_storage_prefix


def storage_connection_string() -> str:
    return settings.azure_storage_connection_string
