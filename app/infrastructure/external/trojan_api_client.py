import time
from typing import Any, Optional

import requests


def _post_json_once(
    url: str,
    headers: dict[str, str],
    json_payload: dict[str, Any],
    timeout: float,
    verify: bool,
    params: Optional[dict[str, Any]],
) -> requests.Response:
    return requests.post(url, headers=headers, params=params or None, json=json_payload, timeout=timeout, verify=verify)


def _should_retry_status(status_code: int, attempt: int, retry_attempts: int) -> bool:
    return 429 <= status_code < 600 and attempt < retry_attempts


def _sleep_before_retry(retry_sleep_seconds: float) -> None:
    time.sleep(max(0.0, retry_sleep_seconds))


def _return_last_response_or_raise(
    last_response: Optional[requests.Response],
    last_exception: Optional[Exception],
) -> requests.Response:
    if last_response is not None:
        return last_response
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("Retry helper exited unexpectedly")


def _post_json_with_retry_impl(url: str, headers: dict[str, str], json_payload: dict[str, Any], timeout: float, verify: bool, params: Optional[dict[str, Any]], retry_attempts: int, retry_sleep_seconds: float) -> requests.Response:
    last_exception: Optional[Exception] = None
    last_response: Optional[requests.Response] = None
    for attempt in range(1, max(1, retry_attempts) + 1):
        try:
            response = _post_json_once(url, headers, json_payload, timeout, verify, params)
        except requests.RequestException as exc:
            last_exception = exc
        else:
            if not _should_retry_status(response.status_code, attempt, retry_attempts):
                return response
            last_response = response
        if attempt < retry_attempts:
            _sleep_before_retry(retry_sleep_seconds)
    return _return_last_response_or_raise(last_response, last_exception)


def post_json_with_retry(url: str, *, headers: dict[str, str], json_payload: dict[str, Any], timeout: float, verify: bool, params: Optional[dict[str, Any]] = None, retry_attempts: int = 2, retry_sleep_seconds: float = 1.0) -> requests.Response:
    return _post_json_with_retry_impl(url, headers, json_payload, timeout, verify, params, retry_attempts, retry_sleep_seconds)
