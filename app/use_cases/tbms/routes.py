from __future__ import annotations

import asyncio
from dataclasses import dataclass

from azurefunctions.extensions.http.fastapi import Request

from app.use_cases.tbms.common import request_json, request_query_params
from app.use_cases.tbms.transport import _call_tbms_api


@dataclass(frozen=True)
class RouteSpec:
    route_name: str
    endpoint_path: str
    defaults: dict | None = None


ROUTES = (
    RouteSpec("tbms-get-vendor-list", "GetVendorList", {"pageSize": 10, "currentPage": 1, "sortBy": "vendName", "sortOrder": "asc", "commonSearchString": "t"}),
    RouteSpec("tbms-vendor-status-update", "VendorUpdate"),
    RouteSpec("tbms-get-pending-vendor-list", "GetPendingVendorList", {"pageSize": 10, "currentPage": 1, "sortBy": "vendName", "sortOrder": "asc", "commonSearchString": "t"}),
    RouteSpec("tbms-vendor-basicinfo-insert", "Vendor/basicinfo-insert"),
    RouteSpec("tbms-vendor-basicinfo-update", "Vendor/basicinfo-update"),
    RouteSpec("tbms-vendor-tradelicense-update", "Vendor/tradelicense-update"),
    RouteSpec("tbms-vendor-vatinfo-update", "Vendor/vatinfo-update"),
    RouteSpec("tbms-vendor-bankaccount-update", "Vendor/bankaccount-update"),
    RouteSpec("tbms-vendor-contact-insert", "Vendor/contact-insert"),
    RouteSpec("tbms-vendor-contact-update", "Vendor/contact-update"),
    RouteSpec("tbms-vendor-ownerdetails-insert", "Vendor/ownerdetails-insert"),
    RouteSpec("tbms-vendor-ownerdetails-update", "Vendor/ownerdetails-Update"),
    RouteSpec("tbms-vendor-ownercompanydetails-insert", "Vendor/ownercompanydetails-insert"),
    RouteSpec("tbms-vendor-ownercompanydetails-update", "Vendor/ownercompanydetails-update"),
)


def _merge_defaults(query_params: dict, defaults: dict | None) -> dict:
    merged = dict(defaults or {})
    merged.update({key: value for key, value in query_params.items() if value not in (None, "")})
    return merged


def _body_overrides(query_params: dict, body: dict) -> dict:
    for key, value in body.items():
        if value in (None, ""):
            continue
        if key in query_params:
            query_params[key] = value
    return query_params


def _register_post_json_route(app, route_name: str, endpoint_path: str):
    async def _handler(req: Request):
        return await asyncio.to_thread(_call_tbms_api, endpoint_path, await request_json(req), None)
    _handler.__name__ = f"tbms_{route_name.lower().replace('-', '_')}"
    app.route(route=route_name, methods=["POST"])(_handler)


def _register_post_query_route(app, route_name: str, endpoint_path: str, defaults: dict):
    async def _handler(req: Request):
        body = await request_json(req)
        query_params = _body_overrides(_merge_defaults(request_query_params(req), defaults), body)
        return await asyncio.to_thread(_call_tbms_api, endpoint_path, body, query_params)
    _handler.__name__ = f"tbms_{route_name.lower().replace('-', '_')}"
    app.route(route=route_name, methods=["POST"])(_handler)


def register_tbms_routes(app) -> None:
    for spec in ROUTES:
        if spec.defaults is None:
            _register_post_json_route(app, spec.route_name, spec.endpoint_path)
        else:
            _register_post_query_route(app, spec.route_name, spec.endpoint_path, spec.defaults)
