import sys

try:
    import app.interfaces.http.tbms_ec_routes  # noqa: F401
except Exception as exc:  # pragma: no cover - startup safety only
    print(f"sitecustomize: failed to load TBMS routes: {exc}", file=sys.stderr)
