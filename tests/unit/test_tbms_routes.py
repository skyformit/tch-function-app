import unittest
from unittest.mock import patch

from app.use_cases.tbms.routes import register_tbms_routes


class _FakeApp:
    def __init__(self) -> None:
        self.handlers = {}

    def route(self, route: str, methods: list[str]):
        def _decorator(handler):
            self.handlers[(route, tuple(methods))] = handler
            return handler

        return _decorator


class _FakeRequest:
    def __init__(self, body: dict, query_params=None) -> None:
        self._body = body
        self.query_params = query_params or {}

    async def json(self):
        return self._body


class TbmsRoutesTest(unittest.TestCase):
    def test_get_vendor_list_forwards_company_name_in_json_body(self) -> None:
        app = _FakeApp()
        register_tbms_routes(app)
        handler = app.handlers[("tbms-get-vendor-list", ("POST",))]

        captured = {}

        def fake_call(endpoint_path, payload=None, params=None):
            captured["endpoint_path"] = endpoint_path
            captured["payload"] = payload
            captured["params"] = params
            return {"ok": True}

        with patch("app.use_cases.tbms.routes._call_tbms_api", side_effect=fake_call):
            import asyncio

            asyncio.run(
                handler(
                    _FakeRequest(
                        {
                            "vendorName": "Abdul Jaleel Al Saadi Trading LLC",
                            "vendId": -1,
                            "licenseNo": "",
                            "email": "",
                            "statusId": -1,
                        }
                    )
                )
            )

        self.assertEqual(captured["endpoint_path"], "GetVendorList")
        self.assertEqual(captured["payload"]["vendorName"], "Abdul Jaleel Al Saadi Trading LLC")
        self.assertEqual(captured["payload"]["licenseNo"], "")


if __name__ == "__main__":
    unittest.main()
