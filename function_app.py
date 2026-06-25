import importlib

from azurefunctions.extensions.http.fastapi import JSONResponse, Request, StreamingResponse
from core.app import app

for module_name in (
    "app.interfaces.http.additional_document_routes",
    "app.interfaces.http.external_source_poller",
    "app.interfaces.http.foundry_workflow",
    "app.interfaces.http.general_bot",
    "app.interfaces.http.tbms_ec_routes",
    "app.interfaces.http.upload_blob",
    "app.interfaces.http.validate_login",
    "app.interfaces.http.validate_trade_license",
):
    importlib.import_module(module_name)
