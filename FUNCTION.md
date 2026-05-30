# FUNCTION.md

This document describes, step by step, how the Fusion audit OCI Function is created in this project.

## 1. Create the OCI Function Metadata

The OCI Function is declared in `func.yaml`.

This file defines:

- Function name: `fusion_audit`
- Runtime: Python
- Python build and run images
- Entrypoint: `/python/bin/fdk /function/src/func.py handler`
- Memory and timeout settings

The function runtime starts in `src/func.py` and calls the `handler` function.

Sample `func.yaml`:

```yaml
schema_version: 20180708
name: fusion_audit
version: 0.0.1
runtime: python
build_image: fnproject/python:3.11-dev
run_image: fnproject/python:3.11
entrypoint: /python/bin/fdk /function/src/func.py handler
memory: 512
timeout: 300
```

## 2. Add Python Dependencies

Runtime dependencies are listed in `requirements.txt`.

The current function needs:

- `fdk` for the OCI Functions Python runtime handler
- `oci` for reading secrets from OCI Vault
- `requests` for calling the Fusion ERP REST API
- `confluent-kafka` for publishing to the Kafka-compatible stream
- `certifi` for CA certificates used by Kafka over TLS

OCI Functions installs these dependencies during the function build.

## 3. Create the Function Handler

The entrypoint is `src/func.py`.

The handler does four things:

1. Reads the invocation JSON payload.
2. Loads and validates configuration.
3. Runs the audit export.
4. Returns a JSON response with success or error details.

The handler accepts configuration either directly in the invocation payload or through the `FUSION_AUDIT_CONFIG_JSON` function configuration value.

## 4. Define Input Configuration

Input validation lives in `src/fusion_audit/config.py`.

The function expects these main input sections:

- `target`: `kafka` or `oci_log`, selecting the single publish destination for this invocation
- `lookback_hours`: how many hours of Fusion audit history to extract
- `vault`: OCI Vault secret OCIDs for Fusion and optional Kafka credentials
- `fusion`: Fusion audit API query options
- `kafka`: Kafka-compatible stream connection settings, required only when `target` is `kafka`
- `oci_log`: OCI custom log ingestion settings, required only when `target` is `oci_log`
- `dry_run`: optional flag to test Vault and Fusion access without publishing to Kafka or OCI Logging

The function enforces a positive lookback window and caps `lookback_hours` at 744 hours, which is about one month.

## 5. Read Secrets from OCI Vault

Secret retrieval is implemented in `src/fusion_audit/vault.py`.

The function uses the OCI Python SDK to read Vault secret bundles. In OCI Functions, it uses the resource principal signer:

```python
oci.auth.signers.get_resource_principals_signer()
```

For local development, it falls back to the local OCI CLI config.

The expected Fusion secrets are:

- Fusion API base URL
- Fusion API username
- Fusion API password

When `target` is `kafka`, the optional Kafka secret is:

- Kafka password, usually an OCI auth token for OCI Streaming Kafka compatibility

The function requires an OCI dynamic group policy similar to:

```text
Allow dynamic-group <dynamic-group-name> to read secret-bundles in compartment <compartment-name>
```

## 6. Build the Fusion Audit Client

Fusion API access is implemented in `src/fusion_audit/fusion.py`.

The function calls the Fusion audit history endpoint:

```text
/fscmRestApi/fndAuditRESTService/audittrail/getaudithistory
```

The function sends:

- `fromDate`
- `toDate`
- `product`
- `eventType`
- `pageNumber`
- `pageSize`
- optional business object and user filters

The default `request_mode` is `body`, which sends the audit parameters as a JSON request body. If a Fusion environment expects query parameters, set:

```json
{
  "fusion": {
    "request_mode": "query"
  }
}
```

Pagination is controlled with `page_size` and `max_pages`.

## 7. Create Audit Messages

Message creation happens in `src/fusion_audit/runtime.py`.

Each Fusion audit record becomes one publishable message with this shape:

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

The message key is a SHA-256 hash derived from stable fields in the Fusion audit record.

## 8. Publish to Kafka

Kafka publishing is implemented in `src/fusion_audit/kafka_publisher.py`.

When `target` is `kafka`, the function uses `confluent-kafka` and expects Kafka-compatible settings:

- `bootstrap_servers`
- `topic`
- `security_protocol`
- `sasl_mechanism`
- `username`
- `password`

For OCI Streaming Kafka compatibility, use:

- `security_protocol`: `SASL_SSL`
- `sasl_mechanism`: `PLAIN`
- `username`: `tenancyName/domain/username/streamPoolId`
- `password`: OCI auth token, preferably read from Vault

The Terraform output `kafka_bootstrap_servers` provides the bootstrap server value, and `stream_name` is the Kafka topic name.

## 9. Publish to OCI Custom Log

OCI custom log publishing is implemented in `src/fusion_audit/oci_log_publisher.py`.

When `target` is `oci_log`, the runtime sends audit messages to OCI Logging Ingestion. The publisher uses:

- the custom log OCID from `oci_log.log_id`
- `source`, `type`, and `subject` metadata for the custom log batch
- deterministic UUIDs for each OCI log entry
- UTC timestamps derived from the audit extraction time

The deployed function needs a dynamic group policy similar to:

```text
Allow dynamic-group <dynamic-group-name> to use log-content in compartment <compartment-name>
```

The Terraform output `custom_log_id` provides the custom log OCID.

## 10. Add Invocation Examples

The sample invocation payload is stored in `examples/invoke.json`.

Use it as the starting point for real Kafka function calls. Replace all placeholder OCIDs, Fusion values, Kafka values, and auth values before running the function.

Kafka target shape:

```json
{
  "target": "kafka",
  "lookback_hours": 4,
  "vault": {},
  "fusion": {},
  "kafka": {}
}
```

OCI custom log target shape:

```json
{
  "target": "oci_log",
  "lookback_hours": 4,
  "vault": {},
  "fusion": {},
  "oci_log": {}
}
```

To test without sending Kafka or OCI Logging messages, set:

```json
{
  "dry_run": true
}
```

## 11. Build and Deploy the Function

From the project root:

```bash
fn build
fn deploy --app <oci-functions-application-name>
```

Invoke with the sample payload:

```bash
fn invoke <oci-functions-application-name> fusion_audit < examples/invoke.json
```

## 12. Schedule the Function

OCI Resource Scheduler can invoke the deployed function on a weekly schedule and pass the same JSON payload used by `fn invoke`.

Create a Sunday night schedule:

```bash
COMPARTMENT_OCID=ocid1.compartment.oc1..example \
FUNCTION_OCID=ocid1.fnfunc.oc1..example \
TIME_STARTS=2026-05-31T23:00:00Z \
PROFILE=DEFAULT \
bash ops/schedule_function_sunday_night.sh
```

The helper uses:

- `examples/invoke.json` as the function body by default
- `0 23 * * 7` as the UTC cron expression by default
- OCI Resource Scheduler action `START_RESOURCE`
- Resource Scheduler `BODY` parameter for the function invocation JSON

For the IAM policies, Fusion roles, and Fusion SQL verification queries, see [docs/SECURITY_AND_SCHEDULING.md](docs/SECURITY_AND_SCHEDULING.md).

## 13. Verify Locally

Before deploying, run a syntax check:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/fusion_audit_pycache python3 -m compileall src
```

Validate the example payload can be parsed:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/fusion_audit_pycache PYTHONPATH=src python3 -c 'import json; from fusion_audit.config import load_config; cfg = load_config(json.load(open("examples/invoke.json")), {}); print(cfg.target, cfg.lookback_hours, cfg.fusion.product)'
```

## 14. Test From Command Line

The function can also be tested from the command line through `src/func.py` or `fusion_audit.cli`.

The CLI uses `argparse` and accepts:

- `--profile` for the OCI profile in `~/.oci/config`
- `--vault-id` for the OCI Vault that contains the Fusion credential secrets
- `--target kafka` with Kafka parameters such as bootstrap servers, topic, username, and password or password secret name
- `--target oci-log` with `--oci-log-id` and optional OCI custom log metadata arguments

Kafka example:

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

OCI custom log example:

```bash
PYTHONPATH=src python3 -m fusion_audit.cli \
  --target oci-log \
  --profile DEFAULT \
  --vault-id ocid1.vault.oc1..example \
  --lookback-hours 4 \
  --fusion-product OPSS \
  --oci-log-id ocid1.log.oc1..example
```

## 15. Test With the Mock Fusion API

The project includes a synthetic Fusion audit fixture and a mock Fusion API server for local and integration testing. See [MOCKFUNCTION.md](MOCKFUNCTION.md) for the full mock server setup and CLI test flow.

## 16. Runtime Requirements

The deployed function needs:

- OCI resource principal permissions to read Vault secret bundles
- OCI resource principal permissions to use log content when `target` is `oci_log`
- Network egress to the Fusion ERP environment
- Network egress to the selected target endpoint
- Valid Fusion audit API credentials
- Valid Kafka credentials and an existing Kafka topic or OCI Streaming stream when `target` is `kafka`
- An existing OCI custom log when `target` is `oci_log`

The Terraform code in `tf/` creates the Vault, secrets, stream pool, stream, connect harness, log group, and custom log used by this function.
