import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin

import requests

from fusion_audit.config import FusionAuditConfig

logger = logging.getLogger(__name__)

AUDIT_HISTORY_PATH = "/fscmRestApi/fndAuditRESTService/audittrail/getaudithistory"


@dataclass(frozen=True)
class FusionCredentials:
    base_url: str
    username: str
    password: str


@dataclass(frozen=True)
class AuditPage:
    page_number: int
    records: List[Dict]
    raw_response: Dict


class FusionAuditClient:
    def __init__(self, credentials: FusionCredentials, config: FusionAuditConfig):
        self._credentials = credentials
        self._config = config
        self._session = requests.Session()
        self._session.auth = (credentials.username, credentials.password)
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "fusion-audit-oci-function/0.1",
            }
        )

    def iter_audit_pages(self, from_dt: datetime, to_dt: datetime) -> Iterable[AuditPage]:
        for page_number in range(1, self._config.max_pages + 1):
            body = self._build_request_body(from_dt, to_dt, page_number)
            logger.info("Fetching Fusion audit page %s", page_number)
            response = self._post_audit_request(body)
            response.raise_for_status()
            payload = response.json()
            status = str(payload.get("status", "")).upper()
            if status and status != "SUCCESS":
                raise RuntimeError(f"Fusion audit request failed with status {status}: {payload}")

            records = payload.get("auditData") or []
            if not isinstance(records, list):
                raise RuntimeError("Fusion audit response field auditData is not an array.")

            yield AuditPage(page_number=page_number, records=records, raw_response=payload)

            if len(records) < self._config.page_size:
                break
        else:
            raise RuntimeError(
                f"Fusion audit pagination reached max_pages={self._config.max_pages}; rerun with a smaller lookback window or larger max_pages."
            )

    def _audit_url(self) -> str:
        return urljoin(self._credentials.base_url.rstrip("/") + "/", AUDIT_HISTORY_PATH.lstrip("/"))

    def _post_audit_request(self, body: Dict) -> requests.Response:
        kwargs = {
            "timeout": (
                self._config.connect_timeout_seconds,
                self._config.read_timeout_seconds,
            )
        }
        if self._config.request_mode == "query":
            kwargs["params"] = body
        else:
            kwargs["json"] = body

        return self._session.post(self._audit_url(), **kwargs)

    def _build_request_body(self, from_dt: datetime, to_dt: datetime, page_number: int) -> Dict:
        body = {
            "fromDate": _format_fusion_datetime(from_dt),
            "toDate": _format_fusion_datetime(to_dt),
            "product": self._config.product,
            "eventType": self._config.event_type,
            "pageNumber": page_number,
            "pageSize": self._config.page_size,
            "timeZone": self._config.time_zone,
            "attributeDetailMode": self._config.attribute_detail_mode,
            "includeAttributes": self._config.include_attributes,
            "includeChildObjects": self._config.include_child_objects,
            "includeExtendedObjectIdentiferColumns": self._config.include_extended_object_identifier_columns,
            "includeImpersonator": self._config.include_impersonator,
        }
        _add_optional(body, "businessObjectType", self._config.business_object_type)
        _add_optional(body, "user", self._config.user)
        return body


def _format_fusion_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _add_optional(body: Dict, key: str, value: Optional[str]) -> None:
    if value:
        body[key] = value
