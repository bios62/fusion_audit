import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import oci
import oci.loggingingestion
import oci.loggingingestion.models

from fusion_audit.config import OciLogConfig

logger = logging.getLogger(__name__)


class OciLogPublisher:
    def __init__(
        self,
        config: OciLogConfig,
        profile: Optional[str] = None,
        config_file: Optional[str] = None,
        use_resource_principal: bool = True,
    ):
        if not config.log_id:
            raise ValueError("OCI log publisher requires a custom log OCID.")
        self._config = config
        self._client = self._build_client(profile, config_file, use_resource_principal)

    def publish(self, messages: Iterable[Tuple[str, Dict]]) -> int:
        delivered = 0
        for batch in _chunks(list(messages), self._config.batch_size):
            if not batch:
                continue
            entries = [
                oci.loggingingestion.models.LogEntry(
                    data=json.dumps(message, default=str, separators=(",", ":")),
                    id=_log_entry_id(key),
                    time=_log_time(message),
                )
                for key, message in batch
            ]
            details = oci.loggingingestion.models.PutLogsDetails(
                specversion="1.0",
                log_entry_batches=[
                    oci.loggingingestion.models.LogEntryBatch(
                        entries=entries,
                        source=self._config.source,
                        type=self._config.log_type,
                        subject=self._config.subject,
                        defaultlogentrytime=_now_utc(),
                    )
                ],
            )
            self._client.put_logs(log_id=self._config.log_id, put_logs_details=details)
            delivered += len(entries)

        logger.info("Published %s messages to OCI custom log %s", delivered, _redact_ocid(self._config.log_id))
        return delivered

    @staticmethod
    def _build_client(
        profile: Optional[str],
        config_file: Optional[str],
        use_resource_principal: bool,
    ):
        if use_resource_principal:
            try:
                signer = oci.auth.signers.get_resource_principals_signer()
                return oci.loggingingestion.LoggingClient(config={}, signer=signer)
            except EnvironmentError:
                logger.info("Resource principal signer unavailable; falling back to local OCI config.")

        config_kwargs = {}
        if config_file:
            config_kwargs["file_location"] = config_file
        if profile:
            config_kwargs["profile_name"] = profile

        config = oci.config.from_file(**config_kwargs)
        return oci.loggingingestion.LoggingClient(config)


def _chunks(messages: List[Tuple[str, Dict]], size: int) -> Iterable[List[Tuple[str, Dict]]]:
    for index in range(0, len(messages), size):
        yield messages[index : index + size]


def _log_entry_id(key: str) -> str:
    try:
        return str(uuid.UUID(str(key)))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, str(key)))


def _log_time(message: Dict) -> datetime:
    extracted_at = message.get("extracted_at")
    if extracted_at:
        try:
            parsed = datetime.fromisoformat(str(extracted_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            logger.debug("Could not parse extracted_at as a timestamp: %s", extracted_at)
    return _now_utc()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _redact_ocid(ocid: str) -> str:
    if len(ocid) <= 16:
        return "***"
    return f"{ocid[:12]}...{ocid[-6:]}"
