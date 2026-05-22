# fusion_audit

OCI Function project for extracting audit trail data from Fusion ERP and publishing it to a Kafka stream.

Author: Inge Os, 2026

## Purpose

This project will contain:

- Python source code for the OCI Function in `src/`
- Terraform infrastructure code in `tf/`
- Local scratch files in `temp/`

The `temp/` directory is intentionally ignored by Git.

## Project Structure

```text
fusion_audit/
  README.md
  FUNCTION.md
  .gitignore
  src/
  tf/
  temp/
```

## Initial Scope

The first implementation target is a function that can:

1. Connect to Fusion ERP audit trail APIs or exports.
2. Extract audit trail records.
3. Transform records into Kafka-ready messages.
4. Publish messages to a Kafka stream.

## Terraform

Terraform code lives in `tf/` and currently creates:

- OCI Vault for Fusion API secrets
- KMS key for encrypting those secrets, with `SOFTWARE` protection mode by default
- OCI Vault secrets from the `fusion_api_secrets` map
- OCI Streaming stream pool with Kafka compatibility settings
- OCI Streaming stream used as the Kafka topic for Fusion audit trail events
- OCI Streaming Kafka Connect configuration

The provider and resource inputs are driven by Terraform variables. Put real values in:

```text
tf/terraform.tfvars
```

That file is ignored by Git. Use `tf/terraform.tfvars.example` as the template.

Important: Terraform will store managed secret values in Terraform state. Before adding real Fusion credentials, use a secured remote backend or another protected state storage pattern.

From the `tf/` directory:

```bash
terraform init
terraform plan
terraform apply
```

Kafka-compatible producers and connectors should use the `kafka_bootstrap_servers` output and the `stream_name` output as the Kafka topic name.

## OCI Function

The Python OCI Function lives in `src/` and is described by `func.yaml`. It does the following:

For a step-by-step walkthrough of how the function is built, see [FUNCTION.md](FUNCTION.md).

1. Reads invocation parameters from the request payload or `FUSION_AUDIT_CONFIG_JSON`.
2. Uses the OCI Python SDK resource principal signer to read Fusion and optional Kafka secrets from OCI Vault.
3. Calls Fusion ERP audit history for the last `lookback_hours`.
4. Publishes each audit record as one Kafka message.

The function expects this high-level payload shape:

```json
{
  "lookback_hours": 4,
  "dry_run": false,
  "vault": {
    "fusion_base_url_secret_id": "ocid1.vaultsecret.oc1..",
    "fusion_username_secret_id": "ocid1.vaultsecret.oc1..",
    "fusion_password_secret_id": "ocid1.vaultsecret.oc1..",
    "kafka_password_secret_id": "ocid1.vaultsecret.oc1.."
  },
  "fusion": {
    "product": "OPSS",
    "event_type": "all",
    "request_mode": "body",
    "page_size": 500,
    "max_pages": 100
  },
  "kafka": {
    "bootstrap_servers": "streaming.eu-frankfurt-1.oci.oraclecloud.com:9092",
    "topic": "fusion-audit-trail",
    "security_protocol": "SASL_SSL",
    "sasl_mechanism": "PLAIN",
    "username": "tenancyName/domain/username/streamPoolId"
  }
}
```

See `examples/invoke.json` for a fuller invocation example.

For OCI Streaming Kafka compatibility:

- Use the Terraform `kafka_bootstrap_servers` output as `kafka.bootstrap_servers`.
- Use the Terraform `stream_name` output as `kafka.topic`.
- Use `SASL_SSL` with `PLAIN`.
- Use the username format `tenancyName/domain/username/streamPoolId`.
- Store the OCI user auth token in Vault and pass its secret OCID as `vault.kafka_password_secret_id`.

The function publishes messages with this structure:

```json
{
  "source": "fusion_erp_audit",
  "extracted_at": "2026-05-20T10:00:00+00:00",
  "window": {
    "from": "2026-05-20T06:00:00+00:00",
    "to": "2026-05-20T10:00:00+00:00",
    "lookback_hours": 4
  },
  "fusion": {
    "product": "OPSS",
    "business_object_type": null,
    "event_type": "all"
  },
  "audit_record": {}
}
```

The function needs an OCI dynamic group and a policy that lets it read the Vault secret bundles:

```text
Allow dynamic-group <dynamic-group-name> to read secret-bundles in compartment <compartment-name>
```

It also needs network egress to the Fusion environment and to the Kafka bootstrap endpoint. Set `dry_run` to `true` to test Vault and Fusion access without publishing to Kafka.

## Run From Command Line

The same function logic can be tested locally from the command line. The CLI entrypoint uses `argparse` and is available through `src/func.py` or the `fusion_audit.cli` module.

Install the Python dependencies first:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Run the command with an OCI profile, the Vault OCID that contains the Fusion credential secrets, and the required Kafka stream settings:

```bash
PYTHONPATH=src python3 -m fusion_audit.cli \
  --profile DEFAULT \
  --vault-id ocid1.vault.oc1..example \
  --lookback-hours 4 \
  --fusion-product OPSS \
  --kafka-bootstrap-servers streaming.eu-frankfurt-1.oci.oraclecloud.com:9092 \
  --kafka-topic fusion-audit-trail \
  --kafka-username "tenancyName/domain/username/ocid1.streampool.oc1..example" \
  --kafka-password-secret-name fusion-audit-kafka-auth-token
```

The command reads OCI credentials from `~/.oci/config` using `--profile`. Use `--config-file` if the config file is somewhere else.

By default, the CLI expects these Vault secret names:

- `fusion-audit-api-base-url`
- `fusion-audit-api-username`
- `fusion-audit-api-password`

Override them when needed:

```bash
--fusion-base-url-secret-name <secret-name>
--fusion-username-secret-name <secret-name>
--fusion-password-secret-name <secret-name>
```

Kafka requires:

- `--kafka-bootstrap-servers`
- `--kafka-topic`
- `--kafka-username`
- either `--kafka-password` or `--kafka-password-secret-name`

Prefer `--kafka-password-secret-name` so the Kafka password or OCI auth token is read from Vault instead of being written into shell history.

To see all options:

```bash
PYTHONPATH=src python3 -m fusion_audit.cli --help
```

You can also call the function file directly:

```bash
python3 src/func.py --help
```

## Mock Fusion API

For local and integration testing, this project includes a mock Fusion audit API server and a synthetic audit fixture.

Files:

- `examples/fusion_audit_records.json`: 20 synthetic Fusion audit records
- `tools/mock_fusion_api.py`: small Python HTTP server that returns the synthetic records

Start the mock server:

```bash
python3 tools/mock_fusion_api.py --host 127.0.0.1 --port 8000
```

The mock implements the same audit endpoint used by the function:

```text
/fscmRestApi/fndAuditRESTService/audittrail/getaudithistory
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Manual audit request:

```bash
curl -X POST http://127.0.0.1:8000/fscmRestApi/fndAuditRESTService/audittrail/getaudithistory \
  -H "Content-Type: application/json" \
  -d '{
    "fromDate": "2026-05-21 00:00:00",
    "toDate": "2026-05-21 23:59:59",
    "product": "OPSS",
    "eventType": "all",
    "pageNumber": 1,
    "pageSize": 5
  }'
```

To require Basic Auth on the mock server:

```bash
python3 tools/mock_fusion_api.py \
  --host 127.0.0.1 \
  --port 8000 \
  --username fusion_user \
  --password fusion_password
```

For command-line function testing, store these values in the Vault used by `--vault-id`:

- `fusion-audit-api-base-url`: `http://127.0.0.1:8000`
- `fusion-audit-api-username`: the mock username, or any value if auth is not enabled
- `fusion-audit-api-password`: the mock password, or any value if auth is not enabled

Then run the CLI with the same Kafka arguments as normal:

```bash
PYTHONPATH=src python3 -m fusion_audit.cli \
  --profile DEFAULT \
  --vault-id ocid1.vault.oc1..example \
  --lookback-hours 4 \
  --fusion-product OPSS \
  --kafka-bootstrap-servers streaming.eu-frankfurt-1.oci.oraclecloud.com:9092 \
  --kafka-topic fusion-audit-trail \
  --kafka-username "tenancyName/domain/username/ocid1.streampool.oc1..example" \
  --kafka-password-secret-name fusion-audit-kafka-auth-token
```

By default, the mock server ignores the date window so the fixture is repeatable. Add `--enforce-date-filter` if you want it to filter records by `fromDate` and `toDate`.

If the function is deployed in OCI, `127.0.0.1` points to the function container, not your laptop. Use a network-reachable mock host when testing a deployed function.


## License

Copyright (c) 2026 Inge Os

Licensed under the Oracle Universal Permissive License v1.0.

SPDX-License-Identifier: UPL-1.0

Full license text: [Oracle Universal Permissive License v1.0](https://www.oracle.com/downloads/licenses/upl-license.html)

## OCI Documentation References

- [Configuring the OCI Terraform provider](https://docs.oracle.com/en-us/iaas/Content/dev/terraform/configuring.htm)
- [OCI Terraform resource: `oci_kms_vault`](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/docs/r/kms_vault.html)
- [OCI Terraform resource: `oci_kms_key`](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/docs/r/kms_key.html)
- [OCI Terraform resource: `oci_vault_secret`](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/docs/r/vault_secret.html)
- [OCI Streaming overview](https://docs.oracle.com/en-us/iaas/Content/Streaming/Concepts/streamingoverview.htm)
- [Creating an OCI stream pool](https://docs.oracle.com/en-us/iaas/Content/Streaming/Tasks/creating-stream-pools.htm)
- [OCI Terraform resource: `oci_streaming_stream_pool`](https://registry.terraform.io/providers/oracle/oci/latest/docs/resources/streaming_stream_pool)
- [OCI Terraform resource: `oci_streaming_stream`](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/docs/r/streaming_stream.html)
- [Using OCI Streaming with Apache Kafka](https://docs.oracle.com/en-us/iaas/Content/Streaming/Tasks/kafkacompatibility.htm)
- [Kafka Python Client and Streaming Quickstart](https://docs.oracle.com/en-us/iaas/Content/Streaming/Tasks/streaming-kafka-python-client-quickstart.htm)
- [OCI Functions resource principals](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/functionsaccessingociresources.htm)
- [OCI Functions supported language versions](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/languagessupportedbyfunctions.htm)
- [Getting an OCI Vault secret's contents](https://docs.oracle.com/en-us/iaas/Content/secret-management/Tasks/get-secrets-contents.htm)
- [Fusion Applications audit report REST endpoint](https://docs.oracle.com/en/cloud/saas/applications-common/26b/farca/op-fscmrestapi-fndauditrestservice-audittrail-getaudithistory-post.html)
- [OCI Terraform resource: `oci_streaming_connect_harness`](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/6.14.0/docs/r/streaming_connect_harness.html)
