# TCG Function App

This Azure Function calls the Foundry workflow and returns a frontend-friendly JSON response.

The code is split into:

- `core/` for shared app and Foundry helpers
- `app/interfaces/http/` for HTTP route registration
- `app/use_cases/` for request handling and use-case orchestration
- `app/infrastructure/` for external services such as Foundry, Blob Storage, and document analysis

## Endpoint

`POST /api/invoke-foundry-workflow`

There is also a General Bot route:

- `POST /api/invoke-general-bot`
- Uses `FOUNDRY_AGENT_NAME`
- Uses `FOUNDRY_PROJECT_ENDPOINT`
- Uses `FOUNDRY_TOKEN_SCOPE`

There is also a scheduled poller:

- `poll_external_items` runs every 5 minutes
- `poll-external-items` lets you trigger the poll manually with `POST`
- Set `ENABLE_EXTERNAL_ITEM_TIMER=true` to turn on the timer in Azure

There is also a separate login-validation route:

- `validate-login` calls the external `ValidateLogin` API

There is also a blob upload route:

- `upload-blob` uploads a file to Azure Blob Storage

There is also a trade-license extraction route:

- `ValidateTradeLicense` uploads a document to Blob Storage and extracts trade license fields with either Azure Document Intelligence or Azure Content Understanding

## Request

Send either:

```json
{ "text": "Hello, please start the approval flow." }
```

For General Bot:

```bash
curl -i -X POST 'http://127.0.0.1:7071/api/invoke-general-bot' \
  -H 'Content-Type: application/json' \
  --data-raw '{"text":"ping"}'
```

Optional fields:

```json
{
  "text": "Hello, please start the approval flow.",
  "conversation_id": "optional-existing-conversation-id",
  "user_id": "optional-user-id"
}
```

## Response

Success:

```json
{
  "ok": true,
  "text": "Hi, enter the vendor ID to start approval?",
  "response_id": "wfresp_...",
  "conversation_id": "conv_...",
  "status": "completed",
  "agent": {
    "name": "TCG-Vendor-Approval-Workflow",
    "version": "124"
  }
}
```

Error:

```json
{
  "ok": false,
  "error": {
    "code": "bad_request",
    "message": "....",
    "type": "invalid_request_error",
    "request_id": "....",
    "status_code": 400
  }
}
```

## Streaming

Send `"stream": true` in the request body to get an SSE response:

```json
{
  "text": "Hello, please start the approval flow.",
  "stream": true
}
```

That returns `Content-Type: text/event-stream` and streams events back to the client as they arrive. Use `fetch()` with a readable stream on web/mobile clients; `EventSource` does not support POST bodies.

## Frontend Example

```javascript
const response = await fetch("/api/invoke-foundry-workflow", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    text: "Hello, please start the approval flow.",
  }),
});

const data = await response.json();

if (data.ok) {
  console.log(data.text);
} else {
  console.error(data.error?.message);
}
```

## Login Validation

`POST /api/validate-login` calls:

`https://api.trojanholding.ae/Api/AI/EC/ValidateLogin`

It uses these app settings:

- `VALIDATE_LOGIN_URL`
- `VALIDATE_LOGIN_API_KEY`
- `VALIDATE_LOGIN_API_KEY_HEADER`
- `VALIDATE_LOGIN_USERNAME`
- `VALIDATE_LOGIN_PASSWORD`
- `VALIDATE_LOGIN_TIMEOUT_SECONDS`
- `VALIDATE_LOGIN_VERIFY_SSL` set to `false` only for temporary dev testing

Example:

```bash
curl -i -X POST 'http://127.0.0.1:7071/api/validate-login' \
  -H 'Content-Type: application/json' \
  --data-raw '{}'
```

Success returns:

```json
{
  "ok": true,
  "data": { "...": "..." },
  "status_code": 200
}
```

## Blob Upload

`POST /api/upload-blob` uploads a file to Azure Blob Storage.

It uses these app settings:

- `AZURE_STORAGE_ACCOUNT_URL`
- `AZURE_STORAGE_CONTAINER`
- `AZURE_STORAGE_PREFIX`
- `AZURE_STORAGE_CONNECTION_STRING` only for local dev or Azurite; leave it empty in Azure to force Managed Identity
- `AZURE_STORAGE_TIMEOUT_SECONDS`

If you use Managed Identity in Azure, grant the Function App identity the **Storage Blob Data Contributor** role on the storage account.

Supported request formats:

Multipart form-data:

```bash
curl -i -X POST 'http://127.0.0.1:7071/api/upload-blob' \
  -F 'file=@./vendor.pdf' \
  -F 'document_type=vat' \
  -F 'blob_name=vendor.pdf'
```

JSON fallback:

```json
{
  "file_name": "vendor.pdf",
  "document_type": "vat",
  "content_base64": "JVBERi0xLjQK..."
}
```

Success returns:

```json
{
  "ok": true,
  "container": "vendor-docs",
  "blob_name": "vendor-docs/vat/vendor.pdf",
  "file_name": "vendor.pdf",
  "document_type": "vat",
  "size": 12345,
  "content_type": "application/pdf",
  "storage_account_url": "https://sttrojanaidevvreg.blob.core.windows.net/",
  "used_connection_string": false
}
```

If you want to test with `curl` and a local connection string, post multipart form-data:

```bash
curl -i -X POST 'http://127.0.0.1:7071/api/upload-blob' \
  -F 'file=@./vendor.pdf' \
  -F 'document_type=vat' \
-F 'blob_name=vendor.pdf'
```

## Trade License Extraction

`POST /api/ValidateTradeLicense` uploads the file and runs the selected document analysis provider against it.

It uses these app settings:

- `AZURE_STORAGE_ACCOUNT_URL`
- `AZURE_STORAGE_CONTAINER`
- `AZURE_STORAGE_PREFIX`
- `AZURE_STORAGE_CONNECTION_STRING`
- `DOCUMENT_ANALYSIS_PROVIDER` set to `document_intelligence` or `content_understanding`
- `DOCUMENT_ANALYSIS_ALLOW_ANALYZE_WITHOUT_UPLOAD`

Document Intelligence settings:

- `DOCUMENT_INTELLIGENCE_ENDPOINT`
- `DOCUMENT_INTELLIGENCE_KEY`
- `DOCUMENT_INTELLIGENCE_API_VERSION`
- `DOCUMENT_INTELLIGENCE_MODEL_ID`
- `DOCUMENT_INTELLIGENCE_TIMEOUT_SECONDS`
- `DOCUMENT_INTELLIGENCE_POLL_INTERVAL_SECONDS`

Content Understanding settings:

- `CONTENT_UNDERSTANDING_ENDPOINT`
- `CONTENT_UNDERSTANDING_KEY`
- `CONTENT_UNDERSTANDING_API_VERSION`
- `CONTENT_UNDERSTANDING_ANALYZER_ID`
- `CONTENT_UNDERSTANDING_TIMEOUT_SECONDS`

Set `DOCUMENT_ANALYSIS_ALLOW_ANALYZE_WITHOUT_UPLOAD=true` to run local analysis without blob upload.
Document Intelligence uses `QUERY_FIELDS` with the target field names, so it can extend a prebuilt model like `prebuilt-layout` without a custom-trained model.
Use `DOCUMENT_ANALYSIS_PROVIDER=content_understanding` when you want the same route to call Content Understanding instead of Document Intelligence.

Example:

```bash
curl -i -X POST 'http://127.0.0.1:7071/api/ValidateTradeLicense' \
  -F 'file=@./trade-license.pdf'
```

Success returns a `status` of `success` plus the extracted `results` and `score`.

## Local Configuration

Set these app settings:

- `FOUNDRY_PROJECT_ENDPOINT`
- `FOUNDRY_AGENT_NAME`
- `FOUNDRY_TOKEN_SCOPE`
- `SOURCE_API_URL`
- `SOURCE_API_KEY`
- `SOURCE_API_KEY_HEADER`
- `SOURCE_SINCE_PARAM`
- `SOURCE_CURSOR_PARAM`
- `SOURCE_STATE_CONTAINER`
- `SOURCE_STATE_BLOB_NAME`
- `SOURCE_STATE_MODE`
- `SOURCE_API_TIMEOUT_SECONDS`
- `ENABLE_EXTERNAL_ITEM_TIMER`
- `PYTHON_ENABLE_INIT_INDEXING`
- `VALIDATE_LOGIN_URL`
- `VALIDATE_LOGIN_API_KEY`
- `VALIDATE_LOGIN_API_KEY_HEADER`
- `VALIDATE_LOGIN_USERNAME`
- `VALIDATE_LOGIN_PASSWORD`
- `VALIDATE_LOGIN_TIMEOUT_SECONDS`
- `AZURE_STORAGE_ACCOUNT_URL`
- `AZURE_STORAGE_CONTAINER`
- `AZURE_STORAGE_PREFIX`
- `AZURE_STORAGE_CONNECTION_STRING` blank in Azure; use only for local dev or Azurite
- `AZURE_STORAGE_TIMEOUT_SECONDS`
- `DOCUMENT_ANALYSIS_PROVIDER`
- `DOCUMENT_ANALYSIS_ALLOW_ANALYZE_WITHOUT_UPLOAD`
- `DOCUMENT_INTELLIGENCE_ENDPOINT`
- `DOCUMENT_INTELLIGENCE_KEY`
- `DOCUMENT_INTELLIGENCE_API_VERSION`
- `DOCUMENT_INTELLIGENCE_MODEL_ID`
- `DOCUMENT_INTELLIGENCE_TIMEOUT_SECONDS`
- `DOCUMENT_INTELLIGENCE_POLL_INTERVAL_SECONDS`
- `CONTENT_UNDERSTANDING_ENDPOINT`
- `CONTENT_UNDERSTANDING_KEY`
- `CONTENT_UNDERSTANDING_API_VERSION`
- `CONTENT_UNDERSTANDING_ANALYZER_ID`
- `CONTENT_UNDERSTANDING_TIMEOUT_SECONDS`

The local test configuration lives in `local.settings.json`.

## Source API Contract

The poller expects the external API to return either:

```json
[
  { "id": "123", "created_at": "2026-06-04T08:00:00Z", "text": "New record" }
]
```

or:

```json
{
  "items": [
    { "id": "123", "created_at": "2026-06-04T08:00:00Z", "text": "New record" }
  ],
  "next_cursor": "abc123"
}
```

The poller sends `X-Api-Key: {YourAssignedAPIKey}` and forwards `since` / `cursor` query parameters when watermark data exists.

Use `SOURCE_STATE_MODE=memory` for local development and `SOURCE_STATE_MODE=blob` in Azure so the watermark survives restarts.
