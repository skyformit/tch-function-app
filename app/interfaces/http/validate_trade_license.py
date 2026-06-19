from azurefunctions.extensions.http.fastapi import Request

from app.domain.document_analysis.profiles import TRADE_LICENSE_PROFILE
from app.use_cases.document_analysis import run_trade_license_route
from core.app import app


@app.route(route="ValidateTradeLicense", methods=["POST"])
async def ValidateTradeLicense(req: Request):
    return await run_trade_license_route(req, TRADE_LICENSE_PROFILE.response_fields)
