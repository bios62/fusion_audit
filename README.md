# fusion_audit

OCI Function project for extracting audit trail data from Fusion ERP and publishing it to either a Kafka stream or an OCI Logging custom log.

Author: Inge Os, 2026

## Purpose

`fusion_audit` is an OCI Function project for collecting audit trail records from Fusion Cloud ERP and publishing normalized audit events to downstream OCI targets.

The function calls the Fusion `fndAuditRESTService` audit history endpoint for a configurable lookback window, wraps each returned audit record in a consistent JSON envelope, and sends the result to one selected target: OCI Streaming through Kafka compatibility or OCI Logging custom logs. Fusion credentials are stored in OCI Vault so they are not embedded in source code or invocation payloads.

```text
┌───────────────┐   POST    ┌─────────────────────┐
│ OCI Function  │ ────────► │ Fusion Cloud        │
│ (Python 3.11) │ ◄──────── │ fndAuditRESTService │
└──────┬────────┘           └─────────────────────┘
       │
       ├──► OCI Streaming (Kafka-compatible audit events)
       ├──► OCI Logging (custom audit log)
       └──► OCI Vault (Fusion credentials)
```

```text
┌────────────────────┐
│ Resource Scheduler │
└─────────┬──────────┘
          │ invokes with JSON payload
          ▼
┌────────────────────┐
│ fusion_audit       │
│ OCI Function       │
└─────────┬──────────┘
          │
          ├──► Kafka target when target = "kafka"
          └──► OCI log target when target = "oci_log"
```

## Project Structure

```text
fusion_audit/
  README.md
  FUNCTION.md
  .gitignore
  docs/
  examples/
  ops/
  sql/
  src/
  tf/
  temp/
```

The repository contains:

- Python source code for the OCI Function in `src/`
- Terraform infrastructure code in `tf/`
- example invocation payloads in `examples/`
- operational scripts in `ops/`
- setup, security, and verification notes in `docs/` and `sql/`
- local scratch files in `temp/`

The `temp/` directory is intentionally ignored by Git.

## Terraform

Terraform code lives in `tf/` and currently creates:

- OCI Vault for Fusion API secrets
- KMS key for encrypting those secrets, with `SOFTWARE` protection mode by default
- OCI Vault secrets from the `fusion_api_secrets` map
- OCI Streaming stream pool with Kafka compatibility settings
- OCI Streaming stream used as the Kafka topic for Fusion audit trail events
- OCI Streaming Kafka Connect configuration
- OCI Logging log group and custom log for Fusion audit events

The provider and resource inputs are driven by Terraform variables. Put real values in:

```text
tf/terraform.tfvars
```

That file is ignored by Git. Use `tf/terraform.tfvars.example` as the template.

Important: Terraform will store managed secret values in Terraform state. Before adding real Fusion credentials, use a secured remote backend or another protected state storage pattern.

Kafka-compatible producers and connectors should use the `kafka_bootstrap_servers` output and the `stream_name` output as the Kafka topic name. When `target` is `oci_log`, use the `custom_log_id` output as the custom log OCID.

## OCI Function

The Python OCI Function lives in `src/` and is described by `func.yaml`. It does the following:

For a step-by-step walkthrough of how the function is built, see [FUNCTION.md](FUNCTION.md).

1. Reads invocation parameters from the request payload or `FUSION_AUDIT_CONFIG_JSON`.
2. Uses the OCI Python SDK resource principal signer to read Fusion and optional Kafka secrets from OCI Vault.
3. Calls Fusion ERP audit history for the last `lookback_hours`.
4. Publishes each audit record to the selected target: Kafka or OCI Logging custom logs.

The function expects one JSON payload with a top-level `target` parameter. Set `target` to `kafka` or `oci_log`; only the selected target block is required.

Kafka target example:

```json
{
  "target": "kafka",
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

OCI custom log target example:

```json
{
  "target": "oci_log",
  "lookback_hours": 4,
  "dry_run": false,
  "vault": {
    "fusion_base_url_secret_id": "ocid1.vaultsecret.oc1..",
    "fusion_username_secret_id": "ocid1.vaultsecret.oc1..",
    "fusion_password_secret_id": "ocid1.vaultsecret.oc1.."
  },
  "fusion": {
    "product": "OPSS",
    "event_type": "all",
    "request_mode": "body",
    "page_size": 500,
    "max_pages": 100
  },
  "oci_log": {
    "log_id": "ocid1.log.oc1..",
    "source": "fusion_audit_function",
    "type": "fusion.audit",
    "subject": "fusion_erp_audit",
    "batch_size": 100
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

When `target` is `oci_log`, the JSON message is pushed into the configured OCI custom log using the Logging Ingestion API. Kafka settings are not required for that target.

The function needs an OCI dynamic group and a policy that lets it read the Vault secret bundles:

```text
Allow dynamic-group <dynamic-group-name> to read secret-bundles in compartment <compartment-name>
```

If `target` is `oci_log`, it also needs permission to use log content:

```text
Allow dynamic-group <dynamic-group-name> to use log-content in compartment <compartment-name>
```

It also needs network egress to the Fusion environment and to the selected target endpoint. Set `dry_run` to `true` to test Vault and Fusion access without publishing to Kafka or OCI Logging.

## Scheduling And Security

The project includes operational files for scheduling and access verification:

- [docs/SECURITY_AND_SCHEDULING.md](docs/SECURITY_AND_SCHEDULING.md): OCI Resource Scheduler setup, OCI IAM policies, Fusion roles, and verification guidance
- [ops/schedule_function_sunday_night.sh](ops/schedule_function_sunday_night.sh): OCI CLI helper that schedules the deployed function every Sunday night
- [sql/verify_fusion_audit_permissions.sql](sql/verify_fusion_audit_permissions.sql): Fusion SQL checks for direct roles and audit privileges

Create a Sunday night Resource Scheduler schedule with:

```bash
COMPARTMENT_OCID=ocid1.compartment.oc1..example \
FUNCTION_OCID=ocid1.fnfunc.oc1..example \
TIME_STARTS=2026-05-31T23:00:00Z \
PROFILE=DEFAULT \
bash ops/schedule_function_sunday_night.sh
```

By default, the script uses `examples/invoke.json` as the function body and `0 23 * * 7` as the UTC cron expression. Resource Scheduler uses UTC time only, so adjust the cron expression when you need a specific local Sunday night time.

Minimum Fusion runtime access is a custom job role assigned to the integration user with the `View Audit History` privilege:

```text
FND_VIEW_AUDIT_HISTORY_PRIV
```

The `Manage Audit Policies` privilege is only needed by setup/admin users who configure what Fusion objects are audited:

```text
FND_MANAGE_AUDIT_POLICIES_PRIV
```

## Run From Command Line

The same function logic can be tested locally from the command line. The CLI entrypoint uses `argparse` and is available through `src/func.py` or the `fusion_audit.cli` module.

Install the Python dependencies first:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Run with `--target kafka` to publish to Kafka or OCI Streaming Kafka compatibility:

```bash
PYTHONPATH=src python3 -m fusion_audit.cli \
  --target kafka \
  --profile DEFAULT \
  --vault-id ocid1.vault.oc1..example \
  --lookback-hours 4 \
  --fusion-product OPSS \
  --kafka-bootstrap-servers streaming.eu-frankfurt-1.oci.oraclecloud.com:9092 \
  --kafka-topic fusion-audit-trail \
  --kafka-username "tenancyName/domain/username/ocid1.streampool.oc1..example" \
  --kafka-password-secret-name fusion-audit-kafka-auth-token
```

Run with `--target oci-log` to publish to OCI Logging custom logs:

```bash
PYTHONPATH=src python3 -m fusion_audit.cli \
  --target oci-log \
  --profile DEFAULT \
  --vault-id ocid1.vault.oc1..example \
  --lookback-hours 4 \
  --fusion-product OPSS \
  --oci-log-id ocid1.log.oc1..example
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

Kafka target arguments:

- `--kafka-bootstrap-servers`
- `--kafka-topic`
- `--kafka-username`
- either `--kafka-password` or `--kafka-password-secret-name`

Prefer `--kafka-password-secret-name` so the Kafka password or OCI auth token is read from Vault instead of being written into shell history.

OCI custom log target arguments:

- `--oci-log-id`
- optional `--oci-log-source`
- optional `--oci-log-type`
- optional `--oci-log-subject`
- optional `--oci-log-batch-size`

To see all options:

```bash
PYTHONPATH=src python3 -m fusion_audit.cli --help
```

You can also call the function file directly:

```bash
python3 src/func.py --help
```

## Fusion API Simulator

To assist development and debug, a fusion API simulator has been created at:
[Fusion API Simulator](https://github.com/bios62/fusion_apisimulator)

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
- [OCI Terraform resource: `oci_logging_log_group`](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/docs/r/logging_log_group.html)
- [OCI Terraform resource: `oci_logging_log`](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/docs/r/logging_log.html)
- [OCI Functions resource principals](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/functionsaccessingociresources.htm)
- [OCI Functions: Scheduling a Function](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/functionsscheduling.htm)
- [OCI Resource Scheduler: Creating a Schedule](https://docs.oracle.com/en-us/iaas/Content/resource-scheduler/tasks/create-manage.htm)
- [OCI Resource Scheduler IAM Policies](https://docs.oracle.com/en-us/iaas/Content/resource-scheduler/references/resource-scheduler-policies.htm)
- [OCI CLI: `resource-scheduler schedule create`](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/resource-scheduler/schedule/create.html)
- [OCI Vault policy reference](https://docs.oracle.com/iaas/Content/Identity/policyreference/keypolicyreference.htm)
- [OCI Streaming policy reference](https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/streamingpolicyreference.htm)
- [OCI Logging policy reference](https://docs.oracle.com/iaas/Content/Identity/policyreference/loggingpolicyreference.htm)
- [OCI Functions supported language versions](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/languagessupportedbyfunctions.htm)
- [Getting an OCI Vault secret's contents](https://docs.oracle.com/en-us/iaas/Content/secret-management/Tasks/get-secrets-contents.htm)
- [Fusion Applications audit report REST endpoint](https://docs.oracle.com/en/cloud/saas/applications-common/26b/farca/op-fscmrestapi-fndauditrestservice-audittrail-getaudithistory-post.html)
- [Fusion Audit Reports and View Audit History privilege](https://docs.oracle.com/en/cloud/saas/applications-common/26a/oacpr/view-audit-report.html)
- [Fusion Audit Policies and Manage Audit Policies privilege](https://docs.oracle.com/en/cloud/saas/sales/oasal/audit-policies.html)
- [Fusion Applications Security tables](https://docs.oracle.com/cd/E51367_01/globalop_gs/OEDMH/ASE_tables.htm)
- [OCI Terraform resource: `oci_streaming_connect_harness`](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/6.14.0/docs/r/streaming_connect_harness.html)
- [OCI Logging custom logs](https://docs.oracle.com/en-us/iaas/Content/Logging/Concepts/custom_logs.htm)
- [Ingesting OCI custom logs with PutLogs](https://docs.oracle.com/en-us/iaas/Content/Logging/Concepts/using_the_api_customlogs.htm)
- [OCI Python SDK Logging Ingestion client](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/loggingingestion/client/oci.loggingingestion.LoggingClient.html)
