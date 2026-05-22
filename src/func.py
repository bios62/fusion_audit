import io
import json
import logging
import os
import sys
from typing import Any, Dict

from fdk import response

sys.path.insert(0, os.path.dirname(__file__))

from fusion_audit.config import ConfigurationError, load_config
from fusion_audit.runtime import run_audit_export

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


def handler(ctx, data: io.BytesIO = None):
    try:
        payload = _read_payload(data)
        function_config = _function_config(ctx)
        config = load_config(payload, function_config)
        result = run_audit_export(config)
        return _json_response(ctx, result, 200)
    except ConfigurationError as exc:
        logger.warning("Invalid function input: %s", exc)
        return _json_response(ctx, {"status": "error", "error": str(exc)}, 400)
    except Exception as exc:
        logger.exception("Fusion audit export failed")
        return _json_response(ctx, {"status": "error", "error": str(exc)}, 500)


def _read_payload(data: io.BytesIO = None) -> Dict[str, Any]:
    if data is None:
        return {}

    raw = data.getvalue()
    if not raw:
        return {}

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Request body is not valid JSON: {exc}") from exc


def _function_config(ctx) -> Dict[str, Any]:
    if ctx is None or not hasattr(ctx, "Config"):
        return {}

    config = ctx.Config() or {}
    if not isinstance(config, dict):
        return {}

    return config


def _json_response(ctx, payload: Dict[str, Any], status_code: int):
    return response.Response(
        ctx,
        response_data=json.dumps(payload, default=str),
        headers={"Content-Type": "application/json"},
        status_code=status_code,
    )


if __name__ == "__main__":
    from fusion_audit.cli import main

    raise SystemExit(main())
