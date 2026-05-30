# MOCKFUNCTION.md

This document describes the local mock Fusion audit API used to test the `fusion_audit` function without calling a real Fusion Cloud environment.

## Purpose

The mock server provides a lightweight stand-in for the Fusion audit history endpoint. It lets you test:

- Fusion REST request formatting
- command-line function execution
- Kafka publishing with synthetic audit records
- OCI custom log publishing with synthetic audit records
- date window and pagination behavior

## Files

- `examples/fusion_audit_records.json`: synthetic Fusion audit record templates
- `tools/mock_fusion_api.py`: Python HTTP server that generates and returns synthetic records

Each server start generates a random sequence of 15 to 50 audit records. The records are dated yesterday, start slightly after midnight, and progress in ascending time order so the audit trail looks natural.

## Flow

```text
┌────────────────────┐   POST    ┌────────────────────┐
│ fusion_audit CLI   │ ────────► │ Mock Fusion API    │
│ or OCI Function    │ ◄──────── │ Python HTTP server │
└─────────┬──────────┘           └────────────────────┘
          │
          ├──► Kafka-compatible stream
          └──► OCI custom log
```

## Start the Mock Server

```bash
python3 tools/mock_fusion_api.py --host 127.0.0.1 --port 8000
```

Control the generated record count or make a run repeatable:

```bash
python3 tools/mock_fusion_api.py \
  --host 127.0.0.1 \
  --port 8000 \
  --min-records 25 \
  --max-records 40 \
  --seed 12345
```

The mock implements the same audit endpoint used by the function:

```text
/fscmRestApi/fndAuditRESTService/audittrail/getaudithistory
```

## Health Check

```bash
curl http://127.0.0.1:8000/health
```

## Manual Audit Request

```bash
curl -X POST http://127.0.0.1:8000/fscmRestApi/fndAuditRESTService/audittrail/getaudithistory \
  -H "Content-Type: application/json" \
  -d '{
    "product": "OPSS",
    "eventType": "all",
    "pageNumber": 1,
    "pageSize": 5
  }'
```

## Optional Basic Auth

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

## Test With the Function CLI

Run the function CLI with the selected target arguments. For Kafka:

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

For OCI custom logs:

```bash
PYTHONPATH=src python3 -m fusion_audit.cli \
  --target oci-log \
  --profile DEFAULT \
  --vault-id ocid1.vault.oc1..example \
  --lookback-hours 4 \
  --fusion-product OPSS \
  --oci-log-id ocid1.log.oc1..example
```

By default, the mock server ignores the date window so generated data is easy to query. Add `--enforce-date-filter` if you want it to filter records by `fromDate` and `toDate`; use a date window that covers yesterday.

If the function is deployed in OCI, `127.0.0.1` points to the function container, not your laptop. Use a network-reachable mock host when testing a deployed function.
