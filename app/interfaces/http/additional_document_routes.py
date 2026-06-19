from azurefunctions.extensions.http.fastapi import Request

from app.domain.document_analysis.profiles import AFFECTION_PLAN_PROFILE, BANK_PROFILE, VAT_PROFILE
from app.use_cases.document_analysis import run_document_analysis_route
from core.app import app


@app.route(route="ValidateVAT", methods=["POST"])
async def ValidateVAT(req: Request):
    return await run_document_analysis_route(req, VAT_PROFILE)


@app.route(route="ValidateBankDocument", methods=["POST"])
async def ValidateBankDocument(req: Request):
    return await run_document_analysis_route(req, BANK_PROFILE)


@app.route(route="ValidateAffectionPlan", methods=["POST"])
async def ValidateAffectionPlan(req: Request):
    return await run_document_analysis_route(req, AFFECTION_PLAN_PROFILE)
