import asyncio
import json
from functools import partial
import re
from typing import Optional, Tuple

from azurefunctions.extensions.http.fastapi import Request

from app.core.config import foundry_project_endpoint, foundry_token_scope, general_bot_agent_id
from app.infrastructure.external.foundry.activity_workflow import invoke_activity_workflow
from app.infrastructure.external.foundry.common import _with_response_metadata
from app.infrastructure.external.foundry_client import _json_response, invoke_foundry_from_text
from app.use_cases.foundry_workflow import _body_text, _conversation_id, _json_body
from app.use_cases.lookup_classifier import classify_lookup_input
from app.use_cases.tbms.transport import _call_tbms_api
from app.use_cases.trade_license_routing import classify_trade_license_routing

_GREETINGS = (
    "hi",
    "hi there",
    "hey",
    "hey there",
    "hello",
    "hello there",
    "good day",
    "good morning",
    "good morning team",
    "good morning everyone",
    "good afternoon",
    "good afternoon team",
    "good afternoon everyone",
    "good evening",
    "good evening team",
    "good evening everyone",
    "morning",
    "afternoon",
    "evening",
)

_STATUS_PHI = (
    "how are you",
    "how are you today",
    "how do you do",
)

_IDENTITY_PHRASES = (
    "who are you",
    "what are you",
    "what is your name",
    "tell me about yourself",
    "tell me who you are",
    "are you a bot",
    "are you human",
)

_CAPABILITY_PHRASES = (
    "what can you do",
    "what do you do",
    "how can you help",
    "how can you help me",
    "can you help me",
    "help",
    "i need help",
    "need help",
    "what services do you offer",
    "what services can you offer",
)

_THANKS_PHRASES = (
    "thanks",
    "thank you",
    "thank you so much",
    "much appreciated",
)

_FAREWELL_PHRASES = (
    "bye",
    "goodbye",
    "see you",
    "see you later",
    "see you soon",
)

_AFFIRMATION_PHRASES = (
    "ok",
    "okay",
    "sure",
)


def _build_phrase_response_map() -> dict[str, str]:
    responses: dict[str, str] = {}
    greetings = "Hello, how can I help you with vendor lookup, trade license, VAT, or document upload?"
    status = "I’m here to help with vendor lookup, trade license, VAT, and document workflows."
    identity = "I’m your UAE Business Compliance Assistant for vendor lookup, trade license, VAT, and document workflows."
    capabilities = "I can help with vendor lookup, trade license checks, VAT, document uploads, and workflow routing."
    thanks = "You’re welcome. How can I help further?"
    farewell = "Goodbye. Reach out anytime you need help with compliance or vendor workflows."

    for phrase in _GREETINGS:
        responses[phrase] = greetings
    for phrase in _STATUS_PHI:
        responses[phrase] = status
    for phrase in _IDENTITY_PHRASES:
        responses[phrase] = identity
    for phrase in _CAPABILITY_PHRASES:
        responses[phrase] = capabilities
    for phrase in _THANKS_PHRASES:
        responses[phrase] = thanks
    for phrase in _FAREWELL_PHRASES:
        responses[phrase] = farewell
    for phrase in _AFFIRMATION_PHRASES:
        responses[phrase] = greetings
    return responses


SMALL_TALK_RESPONSES = _build_phrase_response_map()


def _missing_configuration_response(name: str):
    return _json_response({"ok": False, "error": {"code": "missing_configuration", "message": f"Missing env var: {name}"}}, status_code=500)


def _validate_body(body: dict):
    activity = body.get("activity")
    if activity is not None and not isinstance(activity, dict):
        return "bad_request", "'activity' must be a JSON object"
    input_text = _body_text(body)
    if activity is None and not input_text:
        return "bad_request", "Provide JSON with 'input', 'text', or 'activity'"
    return "", ""


def _normalize_small_talk_text(text: str) -> str:
    normalized_text = (text or "").strip().lower()
    normalized_text = re.sub(r"[^\w\u0600-\u06FF\s]+", " ", normalized_text)
    return " ".join(normalized_text.split())


def _has_business_intent(text: str) -> bool:
    normalized_text = _normalize_small_talk_text(text)
    if not normalized_text:
        return False
    keywords = (
        "vendor",
        "vendor name",
        "company",
        "company name",
        "business",
        "business name",
        "trade name",
        "license",
        "licence",
        "trade",
        "trading",
        "llc",
        "fze",
        "fzco",
        "ltd",
        "vat",
        "tax",
        "trn",
        "lookup",
        "search",
        "status",
        "renewal",
        "renew",
        "approval",
        "document",
        "upload",
        "bank",
        "workflow",
        "workflow",
        "tbms",
    )
    return any(keyword in normalized_text for keyword in keywords)


def _small_talk_response(text: str, body: dict):
    normalized_text = _normalize_small_talk_text(text)
    if _has_business_intent(text):
        return None
    message = SMALL_TALK_RESPONSES.get(normalized_text)
    if message is None:
        return None
    return _json_response(
        _with_response_metadata(
            {
                "ok": True,
                "status": "completed",
                "response_type": "small_talk",
                "text": message,
                "conversation_id": _conversation_id(body),
            },
            "backend",
        ),
        status_code=200,
    )


def _lookup_request_payload(classification: dict, text: str) -> Optional[dict]:
    label = (classification.get("label") or "").strip()
    if label == "company_name":
        return {"vendorName": text.strip(), "vendId": -1, "licenseNo": "", "email": "", "statusId": -1}
    if label == "trade_license_number":
        return {"vendorName": "", "vendId": -1, "licenseNo": text.strip(), "email": "", "statusId": -1}
    return None


def _strip_leading_greeting(text: str) -> str:
    original_text = (text or "").strip()
    normalized_text = _normalize_small_talk_text(original_text)
    greeting_prefixes = (
        "hello there",
        "good morning everyone",
        "good morning team",
        "good morning",
        "good afternoon everyone",
        "good afternoon team",
        "good afternoon",
        "good evening everyone",
        "good evening team",
        "good evening",
        "good day",
        "hi there",
        "hey there",
        "hello",
        "hey",
        "morning",
        "afternoon",
        "evening",
        "hi",
        "ok",
        "okay",
        "sure",
        "thanks",
        "thank you so much",
        "thank you",
    )
    for prefix in greeting_prefixes:
        if normalized_text == prefix:
            return ""
        pattern = rf"^\s*{re.escape(prefix)}[\s,!.;:-]*"
        if re.match(pattern, original_text, flags=re.IGNORECASE):
            return re.sub(pattern, "", original_text, count=1, flags=re.IGNORECASE).strip()
    return original_text


def _extract_license_number(text: str) -> Optional[str]:
    patterns = [
        r"\b(?:trade\s*)?(?:licen[cs]e|licence)(?:\s*(?:no\.?|number))?\s*[:\-]?\s*([A-Z]{1,5}-\d{3,}(?:\s+\d{3,})*)\b",
        r"\b(?:trade\s*)?(?:licen[cs]e|licence)(?:\s*(?:no\.?|number))?\s*[:\-]?\s*(\d{3,}(?:\s+\d{3,})+)\b",
        r"\b(?:trade\s*)?(?:licen[cs]e|licence)(?:\s*(?:no\.?|number))?\s*[:\-]?\s*(\d{4,})\b",
        r"\b([A-Z]{1,5}-\d{3,}(?:\s+\d{3,})*)\b",
        r"\b(\d{3,}(?:\s+\d{3,})+)\b",
        r"\b(\d{5,})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _remove_license_from_text(text: str, license_number: str) -> str:
    cleaned_text = (text or "").strip()
    if not license_number:
        return cleaned_text
    pattern = re.escape(license_number)
    cleaned_text = re.sub(pattern, " ", cleaned_text, count=1, flags=re.IGNORECASE)
    return " ".join(cleaned_text.split())


def _extract_company_from_text(text: str) -> Optional[str]:
    normalized_text = " ".join((text or "").strip().split())
    if not normalized_text:
        return None
    patterns = (
        r"\b(?:vendor\s*name|company\s*name|company|vendor)\b\s*[:\-]?\s*(.+)$",
        r"\b(?:business\s*name|trade\s*name|legal\s*name)\b\s*[:\-]?\s*(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized_text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            candidate = re.split(r"\b(?:license|licen[cs]e|licence|trade\s*license|trn)\b", candidate, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,;:-")
            if candidate:
                return " ".join(candidate.split())
    return None


def _strip_license_labels(text: str) -> str:
    cleaned_text = re.sub(
        r"\b(?:trade\s*)?(?:licen[cs]e|licence)(?:\s*(?:no\.?|number))?\b",
        " ",
        text or "",
        flags=re.IGNORECASE,
    )
    return " ".join(cleaned_text.split())


def _split_lookup_text(text: str) -> Tuple[str, Optional[str]]:
    without_greeting = _strip_leading_greeting(text)
    license_number = _extract_license_number(without_greeting)
    company_text = _extract_company_from_text(without_greeting)
    if not company_text:
        company_text = _remove_license_from_text(without_greeting, license_number) if license_number else without_greeting
        company_text = _strip_license_labels(company_text)
        if not company_text or not re.search(r"[A-Za-z]", company_text) or not _has_business_intent(company_text):
            company_text = ""
    return company_text.strip(), license_number


def _tbms_response_has_results(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("ok") is False:
        return False
    data = payload.get("data")
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return len(results) > 0
        if isinstance(results, dict):
            return bool(results)
        return bool(data)
    if isinstance(data, list):
        return len(data) > 0
    return bool(data)


def _lookup_clarification_response() -> dict:
    return _json_response(
        _with_response_metadata(
            {
                "ok": True,
                "status": "needs_clarification",
                "response_type": "lookup_clarification",
                "text": "Please provide the company/vendor name or trade license number.",
            },
            "backend",
        ),
        status_code=200,
    )


def _tbms_http_response_to_payload(response) -> dict:
    body = None
    body_type = None
    try:
        if hasattr(response, "get_body"):
            body = response.get_body()
        elif hasattr(response, "body"):
            body = response.body
        elif hasattr(response, "text"):
            body = response.text
        body_type = type(body).__name__ if body is not None else None
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        if isinstance(body, str) and body.strip():
            return json.loads(body)
        if isinstance(body, dict):
            return body
    except Exception:
        pass
    return {
        "ok": False,
        "error": {
            "code": "response_parse_error",
            "message": "Failed to parse TBMS response",
            "body_type": body_type,
            "raw_body": body if isinstance(body, str) else None,
            "status_code": getattr(response, "status_code", None),
        },
    }


def _annotate_source(payload: dict, source: str) -> dict:
    return _with_response_metadata(payload, source)


async def _lookup_response(text: str):
    classification = classify_lookup_input(text)
    label = classification.get("label")
    if label == "person_name":
        return _lookup_clarification_response()
    company_text, license_number = _split_lookup_text(text)
    payloads = _lookup_payloads(label, company_text, license_number)
    if not payloads:
        return None
    last_payload = None
    last_response = None
    for payload in payloads:
        last_payload = payload
        tbms_response = await asyncio.to_thread(_call_tbms_api, "GetVendorList", payload, None)
        last_response = tbms_response
        response_payload = _tbms_http_response_to_payload(tbms_response)
        if tbms_response.status_code < 400 and _tbms_response_has_results(response_payload):
            return _json_response(_annotate_source(response_payload, "tbms"), status_code=tbms_response.status_code)
    if last_response is None:
        return None
    fallback_payload = _tbms_http_response_to_payload(last_response)
    if isinstance(fallback_payload, dict):
        fallback_payload.setdefault("lookup_attempt", last_payload)
    return _json_response(_annotate_source(fallback_payload, "tbms"), status_code=last_response.status_code)


def _lookup_payloads(label: str, company_text: str, license_number: Optional[str]) -> list[dict]:
    payloads: list[dict] = []
    if label in {"company_name", "trade_license_number"} and license_number and company_text:
        payloads.append({"vendorName": company_text, "vendId": -1, "licenseNo": license_number, "email": "", "statusId": -1})
        payloads.append({"vendorName": "", "vendId": -1, "licenseNo": license_number, "email": "", "statusId": -1})
        payloads.append({"vendorName": company_text, "vendId": -1, "licenseNo": "", "email": "", "statusId": -1})
        return payloads
    if label == "trade_license_number":
        payloads.append({"vendorName": "", "vendId": -1, "licenseNo": license_number or company_text, "email": "", "statusId": -1})
        return payloads
    if label == "company_name":
        payloads.append({"vendorName": company_text, "vendId": -1, "licenseNo": "", "email": "", "statusId": -1})
    return payloads


def _resolve_config():
    project_endpoint = foundry_project_endpoint()
    agent_id = general_bot_agent_id()
    token_scope = foundry_token_scope()
    if not project_endpoint:
        return None, _missing_configuration_response("FOUNDRY_PROJECT_ENDPOINT")
    if not agent_id:
        return None, _missing_configuration_response("GENERAL_BOT_AGENT_ID")
    return {"project_endpoint": project_endpoint, "agent_id": agent_id, "token_scope": token_scope}, None


def _invoke_general_bot_workflow(body: dict, config: dict):
    return asyncio.to_thread(
        partial(
            invoke_foundry_from_text,
            input_text=_body_text(body),
            conversation_id=_conversation_id(body),
            include=body.get("include") if isinstance(body.get("include"), list) else None,
            previous_response_id=body.get("previous_response_id") if isinstance(body.get("previous_response_id"), str) and body.get("previous_response_id").strip() else None,
            stream=None,
            project_endpoint=config["project_endpoint"],
            agent_id=config["agent_id"],
            token_scope=config["token_scope"],
        )
    )


def _user_id(body: dict) -> str:
    if isinstance(body.get("user_id"), str) and body["user_id"].strip():
        return body["user_id"].strip()
    activity = body.get("activity")
    if isinstance(activity, dict):
        sender = activity.get("from")
        if isinstance(sender, dict) and isinstance(sender.get("id"), str):
            return sender["id"].strip()
    return "web-user"


def _workflow_result(workflow_url: str, body: dict) -> tuple[int, dict]:
    return invoke_activity_workflow(workflow_url, _body_text(body), _conversation_id(body), _user_id(body))


def _route_trade_license(payload: dict, body: dict) -> tuple[int, dict]:
    route = classify_trade_license_routing(payload.get("text") or "")
    return (200, payload) if route is None else _route_trade_license_payload(payload, body, route)


def _route_trade_license_payload(payload: dict, body: dict, route) -> tuple[int, dict]:
    workflow_status, workflow_payload = _workflow_result(route.workflow_url, body)
    return 200, _trade_license_payload(payload, route, workflow_status, workflow_payload)


def _trade_license_payload(payload: dict, route, workflow_status: int, workflow_payload: dict) -> dict:
    combined = dict(payload)
    combined["routing"] = _trade_license_routing(route)
    combined["workflow_started"] = workflow_status < 400
    combined["workflow_response"] = workflow_payload
    combined["text"] = route.message
    return _trade_license_outcome(_with_response_metadata(combined, "workflow"), route)


def _trade_license_routing(route) -> dict:
    return {
        "expiry_date": route.decision.expiry_date.isoformat(),
        "days_remaining": route.decision.days_remaining,
        "status": route.decision.status,
        "workflow_name": route.workflow_name,
    }


def _trade_license_outcome(combined: dict, route) -> dict:
    if route.decision.status == "expired":
        combined["ok"] = False
        combined["status"] = "expired"
        combined["error"] = {"code": "trade_license_expired", "message": route.message}
        return combined
    combined["status"] = "renewal_due"
    combined["warning"] = {"code": "trade_license_renewal_due", "message": route.message}
    return combined


async def invoke_general_bot(req: Request):
    body = await _json_body(req)
    error_code, error_message = _validate_body(body)
    if error_code:
        return _json_response({"ok": False, "error": {"code": error_code, "message": error_message}}, status_code=400)
    small_talk_response = _small_talk_response(_body_text(body), body)
    if small_talk_response is not None:
        return small_talk_response
    lookup_response = await _lookup_response(_body_text(body))
    if lookup_response is not None:
        return lookup_response
    config, config_error = _resolve_config()
    if config_error is not None:
        return config_error
    status_code, payload = await _invoke_general_bot_workflow(body, config)
    payload = _annotate_source(payload, "llm")
    status_code, payload = _route_trade_license(payload, body)
    if isinstance(payload, dict) and "source" not in payload:
        payload["source"] = "llm"
    return _json_response(payload, status_code=status_code)


def register_general_bot_routes(app) -> None:
    app.route(route="invoke-general-bot", methods=["POST"])(invoke_general_bot)
