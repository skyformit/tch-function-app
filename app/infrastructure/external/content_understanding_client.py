import json

from azure.ai.contentunderstanding import ContentUnderstandingClient
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential

from app.core.document_settings import (
    content_understanding_analyzer_id,
    content_understanding_api_version,
    content_understanding_endpoint,
    content_understanding_key,
    content_understanding_timeout_seconds,
)


def analyze_document(file_bytes: bytes, content_type: str) -> tuple[dict, str, str]:
    endpoint = content_understanding_endpoint()
    api_key = content_understanding_key()
    api_version = content_understanding_api_version()
    analyzer_id = content_understanding_analyzer_id()

    if not endpoint:
        raise RuntimeError("Missing env var: CONTENT_UNDERSTANDING_ENDPOINT")
    if not analyzer_id:
        raise RuntimeError("Missing env var: CONTENT_UNDERSTANDING_ANALYZER_ID")

    credential = AzureKeyCredential(api_key) if api_key else DefaultAzureCredential()
    client = ContentUnderstandingClient(endpoint=endpoint, credential=credential, api_version=api_version)
    return _analyze_binary(client, analyzer_id, file_bytes, content_type), analyzer_id, api_version


def _analyze_binary(client: ContentUnderstandingClient, analyzer_id: str, file_bytes: bytes, content_type: str) -> dict:
    poller = client.begin_analyze_binary(analyzer_id=analyzer_id, binary_input=file_bytes, content_type=content_type)
    result = poller.result(timeout=content_understanding_timeout_seconds())
    return result.as_dict() if hasattr(result, "as_dict") else json.loads(json.dumps(result))
