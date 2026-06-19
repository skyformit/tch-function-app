import io
import json
from typing import List, Optional

from azure.ai.documentintelligence.models import DocumentAnalysisFeature
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential

try:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
except ImportError:  # pragma: no cover - handled at runtime when provider is selected
    DocumentIntelligenceClient = None

from app.core.config import (
    document_intelligence_api_version,
    document_intelligence_endpoint,
    document_intelligence_key,
    document_intelligence_model_id,
    document_intelligence_poll_interval_seconds,
    document_intelligence_timeout_seconds,
)


def _document_analysis_context(model_id_override: Optional[str]) -> tuple[DocumentIntelligenceClient, str, str]:
    endpoint = document_intelligence_endpoint()
    api_key = document_intelligence_key()
    api_version = document_intelligence_api_version()
    model_id = (model_id_override or document_intelligence_model_id()).strip()
    if not endpoint:
        raise RuntimeError("Missing env var: DOCUMENT_INTELLIGENCE_ENDPOINT")
    if not model_id:
        raise RuntimeError("Missing env var: DOCUMENT_INTELLIGENCE_MODEL_ID")
    if DocumentIntelligenceClient is None:
        raise RuntimeError("azure-ai-documentintelligence is not installed")
    credential = AzureKeyCredential(api_key) if api_key else DefaultAzureCredential()
    client = DocumentIntelligenceClient(endpoint=endpoint, credential=credential, api_version=api_version, polling_interval=document_intelligence_poll_interval_seconds())
    return client, model_id, api_version


def analyze_document(file_bytes: bytes, content_type: str, query_fields: Optional[List[str]] = None, model_id_override: Optional[str] = None) -> tuple[dict, str, str]:
    client, model_id, api_version = _document_analysis_context(model_id_override)
    return _analyze_document(client, model_id, file_bytes, query_fields), model_id, api_version


def _analyze_document(client: DocumentIntelligenceClient, model_id: str, file_bytes: bytes, query_fields: Optional[List[str]]) -> dict:
    if model_id == "prebuilt-read":
        poller = client.begin_analyze_document(model_id, io.BytesIO(file_bytes))
    else:
        poller = client.begin_analyze_document(
            model_id,
            io.BytesIO(file_bytes),
            features=[DocumentAnalysisFeature.QUERY_FIELDS] if (query_fields or []) else [],
            query_fields=(query_fields or [])[:20],
        )
    result = poller.result(timeout=document_intelligence_timeout_seconds())
    return result.as_dict() if hasattr(result, "as_dict") else json.loads(json.dumps(result))
