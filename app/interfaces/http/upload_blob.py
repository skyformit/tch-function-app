from azurefunctions.extensions.http.fastapi import Request

from app.use_cases.upload_blob import upload_blob as _upload_blob
from core.app import app


@app.route(route="upload-blob", methods=["POST"])
async def upload_blob(req: Request):
    return await _upload_blob(req)
