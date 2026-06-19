from azurefunctions.extensions.http.fastapi import Request

from app.use_cases.login import validate_login as _validate_login
from core.app import app


@app.route(route="validate-login", methods=["POST"])
async def validate_login(req: Request):
    return _validate_login()
