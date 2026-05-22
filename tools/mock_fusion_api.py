#!/usr/bin/env python3
import argparse
import base64
import json
import logging
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse


AUDIT_HISTORY_PATH = "/fscmRestApi/fndAuditRESTService/audittrail/getaudithistory"
DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fusion_audit_records.json"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger(__name__)


class MockFusionAuditHandler(BaseHTTPRequestHandler):
    server_version = "FusionAuditMock/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"status": "ok"})
            return
        self._send_json({"status": "NOT_FOUND", "message": "Use POST " + AUDIT_HISTORY_PATH}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != AUDIT_HISTORY_PATH:
            self._send_json({"status": "NOT_FOUND", "message": "Unknown endpoint."}, HTTPStatus.NOT_FOUND)
            return

        if not self._is_authorized():
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="Fusion Audit Mock"')
            self.end_headers()
            return

        params = self._request_params(parsed.query)
        records = filter_records(self.server.audit_records, params, self.server.enforce_date_filter)
        page_number = positive_int(params.get("pageNumber"), 1)
        page_size = positive_int(params.get("pageSize"), 500)
        start = (page_number - 1) * page_size
        end = start + page_size
        page_records = records[start:end]

        self._send_json(
            {
                "status": "SUCCESS",
                "auditData": page_records,
                "count": len(page_records),
                "totalResults": len(records),
                "pageNumber": page_number,
                "pageSize": page_size,
                "hasMore": end < len(records),
                "mock": True,
            }
        )

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def _request_params(self, query: str) -> Dict[str, Any]:
        params = flatten_query_params(parse_qs(query))
        content_length = int(self.headers.get("Content-Length", "0"))
        if not content_length:
            return params

        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return params

        try:
            body = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}

        if isinstance(body, dict):
            params.update(body)
        return params

    def _is_authorized(self) -> bool:
        username = self.server.username
        password = self.server.password
        if username is None and password is None:
            return True

        header = self.headers.get("Authorization", "")
        expected = "Basic " + base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return header == expected

    def _send_json(self, payload: Dict[str, Any], status_code: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a mock Fusion ERP audit history API.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8000, help="Bind port. Defaults to 8000.")
    parser.add_argument(
        "--fixture",
        default=str(DEFAULT_FIXTURE),
        help="Path to the synthetic audit fixture JSON file.",
    )
    parser.add_argument("--username", default=None, help="Optional Basic Auth username to require.")
    parser.add_argument("--password", default=None, help="Optional Basic Auth password to require.")
    parser.add_argument(
        "--enforce-date-filter",
        action="store_true",
        help="Filter records by fromDate and toDate. By default, date filters are ignored for easier repeatable tests.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Python logging level. Defaults to INFO.",
    )
    args = parser.parse_args()
    if (args.username is None) != (args.password is None):
        parser.error("--username and --password must be provided together.")

    logging.basicConfig(level=args.log_level, format="%(levelname)s %(message)s")

    records = load_audit_records(Path(args.fixture))
    server = ThreadingHTTPServer((args.host, args.port), MockFusionAuditHandler)
    server.audit_records = records
    server.enforce_date_filter = args.enforce_date_filter
    server.username = args.username
    server.password = args.password

    logger.info("Loaded %s synthetic Fusion audit records from %s", len(records), args.fixture)
    logger.info("Mock Fusion API listening on http://%s:%s", args.host, args.port)
    logger.info("Audit endpoint: %s", AUDIT_HISTORY_PATH)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping mock Fusion API")
    finally:
        server.server_close()

    return 0


def load_audit_records(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = payload.get("auditData", [])
    else:
        raise ValueError("Fixture must be either a JSON array or an object with an auditData array.")

    if not isinstance(records, list):
        raise ValueError("Fixture auditData value must be an array.")
    return records


def filter_records(records: List[Dict[str, Any]], params: Dict[str, Any], enforce_date_filter: bool) -> List[Dict[str, Any]]:
    product = normalized(params.get("product"))
    event_type = normalized(params.get("eventType"))
    business_object_type = normalized(params.get("businessObjectType"))
    user = normalized(params.get("user"))
    from_date = parse_fusion_date(params.get("fromDate")) if enforce_date_filter else None
    to_date = parse_fusion_date(params.get("toDate")) if enforce_date_filter else None

    filtered = []
    for record in records:
        if product and normalized(record.get("product")) != product:
            continue
        if event_type and event_type != "all" and normalized(record.get("eventType")) != event_type:
            continue
        if business_object_type and normalized(record.get("businessObjectType")) != business_object_type:
            continue
        if user and normalized(record.get("userInternalName")) != user:
            continue
        if enforce_date_filter and not is_inside_window(record.get("date"), from_date, to_date):
            continue
        filtered.append(record)
    return filtered


def flatten_query_params(query_params: Dict[str, List[str]]) -> Dict[str, Any]:
    return {key: values[-1] for key, values in query_params.items() if values}


def positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def normalized(value: Optional[Any]) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value).strip().lower()


def parse_fusion_date(value: Optional[Any]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value)
    for date_format in (DATE_FORMAT, "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, date_format)
            return parsed.replace(tzinfo=None)
        except ValueError:
            continue
    return None


def is_inside_window(record_date: Optional[Any], from_date: Optional[datetime], to_date: Optional[datetime]) -> bool:
    parsed = parse_fusion_date(record_date)
    if parsed is None:
        return True
    if from_date and parsed < from_date:
        return False
    if to_date and parsed > to_date:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
