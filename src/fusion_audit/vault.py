import base64
import logging
from typing import Dict, Mapping, Optional

import oci

from fusion_audit.config import SecretReference

logger = logging.getLogger(__name__)


class VaultSecretProvider:
    def __init__(
        self,
        profile: Optional[str] = None,
        config_file: Optional[str] = None,
        use_resource_principal: bool = True,
    ):
        self._client = self._build_client(profile, config_file, use_resource_principal)

    def get_many(self, secret_references: Mapping[str, SecretReference]) -> Dict[str, str]:
        return {name: self.get(reference) for name, reference in secret_references.items()}

    def get(self, reference: SecretReference) -> str:
        if reference.secret_id:
            return self.get_by_id(reference.secret_id)
        if reference.vault_id and reference.secret_name:
            return self.get_by_name(reference.vault_id, reference.secret_name)
        raise RuntimeError("Secret reference must include either secret_id or vault_id and secret_name.")

    def get_by_id(self, secret_id: str) -> str:
        logger.info("Retrieving secret bundle for %s", _redact_ocid(secret_id))
        secret_bundle = self._client.get_secret_bundle(secret_id).data
        return _decode_secret_bundle(secret_bundle)

    def get_by_name(self, vault_id: str, secret_name: str) -> str:
        logger.info("Retrieving secret bundle named %s from vault %s", secret_name, _redact_ocid(vault_id))
        secret_bundle = self._client.get_secret_bundle_by_name(secret_name, vault_id).data
        return _decode_secret_bundle(secret_bundle)

    @staticmethod
    def _build_client(
        profile: Optional[str],
        config_file: Optional[str],
        use_resource_principal: bool,
    ):
        if use_resource_principal:
            try:
                signer = oci.auth.signers.get_resource_principals_signer()
                return oci.secrets.SecretsClient(config={}, signer=signer)
            except EnvironmentError:
                logger.info("Resource principal signer unavailable; falling back to local OCI config.")

        config_kwargs = {}
        if config_file:
            config_kwargs["file_location"] = config_file
        if profile:
            config_kwargs["profile_name"] = profile

        config = oci.config.from_file(**config_kwargs)
        return oci.secrets.SecretsClient(config)


def _decode_secret_bundle(secret_bundle) -> str:
    content_details = secret_bundle.secret_bundle_content
    content = getattr(content_details, "content", None)
    if not content:
        raise RuntimeError("Secret bundle has no retrievable content.")

    return base64.b64decode(content.encode("utf-8")).decode("utf-8")


def _redact_ocid(ocid: str) -> str:
    if len(ocid) <= 16:
        return "***"
    return f"{ocid[:12]}...{ocid[-6:]}"
