from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.config import renewal_vendor_approval_workflow_url, vendor_approval_workflow_url
from app.use_cases.trade_license_expiry import TradeLicenseExpiryDecision, classify_trade_license_expiry


@dataclass(frozen=True)
class TradeLicenseWorkflowRoute:
    decision: TradeLicenseExpiryDecision
    workflow_name: str
    workflow_url: str
    message: str


def _workflow_name(status: str) -> str:
    return "TCG-Vendor-Approval-Workflow" if status == "expired" else "Renewal-Vendor-Approval-Workflow"


def _workflow_url(status: str) -> str:
    return vendor_approval_workflow_url() if status == "expired" else renewal_vendor_approval_workflow_url()


def _workflow_message(decision: TradeLicenseExpiryDecision) -> str:
    expiry_text = decision.expiry_date.strftime("%d %b %Y")
    if decision.status == "expired":
        return f"Trade license expired on {expiry_text}. Starting TCG-Vendor-Approval-Workflow."
    return f"Trade license expires on {expiry_text} ({decision.days_remaining} days left). Starting Renewal-Vendor-Approval-Workflow."


def classify_trade_license_routing(text: str, warning_days: int = 60) -> Optional[TradeLicenseWorkflowRoute]:
    decision = classify_trade_license_expiry(text, warning_days=warning_days)
    if decision is None or decision.status == "valid":
        return None
    return TradeLicenseWorkflowRoute(decision=decision, workflow_name=_workflow_name(decision.status), workflow_url=_workflow_url(decision.status), message=_workflow_message(decision))
