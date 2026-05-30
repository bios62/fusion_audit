#!/usr/bin/env bash
set -euo pipefail

# Creates an OCI Resource Scheduler schedule that invokes the fusion_audit
# function every Sunday night. The invocation body is read from JSON so the
# schedule uses the same payload shape as fn invoke.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="${PROJECT_ROOT}/temp/scheduler"

SCHEDULE_NAME="${SCHEDULE_NAME:-fusion-audit-sunday-night}"
DESCRIPTION="${DESCRIPTION:-Invoke fusion_audit every Sunday night}"
RECURRENCE_DETAILS="${RECURRENCE_DETAILS:-0 23 * * 7}"
INVOCATION_PAYLOAD_FILE="${INVOCATION_PAYLOAD_FILE:-${PROJECT_ROOT}/examples/invoke.json}"
OCI_CLI="${OCI_CLI:-oci}"
CREATE_SCHEDULER_IAM="${CREATE_SCHEDULER_IAM:-false}"
DYNAMIC_GROUP_NAME="${DYNAMIC_GROUP_NAME:-fusion-audit-resource-scheduler}"
SCHEDULER_POLICY_NAME="${SCHEDULER_POLICY_NAME:-fusion-audit-resource-scheduler-policy}"

usage() {
  cat <<'USAGE'
Create an OCI Resource Scheduler schedule for the fusion_audit function.

Required environment variables:
  COMPARTMENT_OCID          Compartment where the Resource Scheduler schedule is created.
  FUNCTION_OCID             OCID of the deployed OCI Function.
  TIME_STARTS               RFC3339 schedule start time, for example 2026-05-31T23:00:00Z.

Optional environment variables:
  PROFILE                   OCI CLI profile name.
  CONFIG_FILE               OCI CLI config file path.
  REGION                    OCI CLI region override.
  SCHEDULE_NAME             Display name. Default: fusion-audit-sunday-night.
  DESCRIPTION               Schedule description.
  RECURRENCE_DETAILS        Five-field UTC cron expression. Default: 0 23 * * 7.
  INVOCATION_PAYLOAD_FILE   Function payload JSON. Default: examples/invoke.json.
  TIME_ENDS                 Optional RFC3339 schedule end time.

Optional IAM creation:
  CREATE_SCHEDULER_IAM=true
  TENANCY_OCID              Tenancy OCID where IAM dynamic group and policy are created.
  DYNAMIC_GROUP_NAME        Default: fusion-audit-resource-scheduler.
  SCHEDULER_POLICY_NAME     Default: fusion-audit-resource-scheduler-policy.

Example:
  COMPARTMENT_OCID=ocid1.compartment.oc1..example \
  FUNCTION_OCID=ocid1.fnfunc.oc1..example \
  TIME_STARTS=2026-05-31T23:00:00Z \
  PROFILE=DEFAULT \
  bash ops/schedule_function_sunday_night.sh
USAGE
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: ${name}" >&2
    usage >&2
    exit 2
  fi
}

json_escape() {
  python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"
}

require_env COMPARTMENT_OCID
require_env FUNCTION_OCID
require_env TIME_STARTS

if [[ ! -f "${INVOCATION_PAYLOAD_FILE}" ]]; then
  echo "Invocation payload file not found: ${INVOCATION_PAYLOAD_FILE}" >&2
  exit 2
fi

mkdir -p "${TMP_DIR}"
RESOURCES_JSON="$(mktemp "${TMP_DIR}/resources.XXXXXX.json")"

python3 - "${FUNCTION_OCID}" "${INVOCATION_PAYLOAD_FILE}" "${RESOURCES_JSON}" <<'PY'
import json
import sys
from pathlib import Path

function_ocid, payload_file, resources_file = sys.argv[1:4]
payload = json.loads(Path(payload_file).read_text(encoding="utf-8"))
resources = [
    {
        "id": function_ocid,
        "parameters": [
            {
                "parameterType": "BODY",
                "value": payload,
            }
        ],
    }
]
Path(resources_file).write_text(json.dumps(resources, indent=2), encoding="utf-8")
PY

profile_args=()
if [[ -n "${PROFILE:-}" ]]; then
  profile_args+=(--profile "${PROFILE}")
fi
if [[ -n "${CONFIG_FILE:-}" ]]; then
  profile_args+=(--config-file "${CONFIG_FILE}")
fi
if [[ -n "${REGION:-}" ]]; then
  profile_args+=(--region "${REGION}")
fi

time_end_args=()
if [[ -n "${TIME_ENDS:-}" ]]; then
  time_end_args+=(--time-ends "${TIME_ENDS}")
fi

echo "Creating Resource Scheduler schedule '${SCHEDULE_NAME}'..."
schedule_json="$(
  "${OCI_CLI}" resource-scheduler schedule create \
    "${profile_args[@]}" \
    --action START_RESOURCE \
    --compartment-id "${COMPARTMENT_OCID}" \
    --display-name "${SCHEDULE_NAME}" \
    --description "${DESCRIPTION}" \
    --recurrence-type CRON \
    --recurrence-details "${RECURRENCE_DETAILS}" \
    --time-starts "${TIME_STARTS}" \
    "${time_end_args[@]}" \
    --resources "file://${RESOURCES_JSON}"
)"

schedule_ocid="$(
  python3 -c 'import json, sys; print(json.load(sys.stdin).get("data", {}).get("id", ""))' \
    <<< "${schedule_json}"
)"

if [[ -z "${schedule_ocid}" ]]; then
  echo "Schedule created, but the OCI CLI response did not include data.id." >&2
  echo "${schedule_json}"
  exit 0
fi

echo "Created schedule: ${schedule_ocid}"
echo "Generated resource payload: ${RESOURCES_JSON}"

if [[ "${CREATE_SCHEDULER_IAM}" != "true" ]]; then
  cat <<EOF

Next IAM step:
  Create a dynamic group with this rule:
    ALL {resource.type='resourceschedule', resource.id='${schedule_ocid}'}

  Then create this policy:
    Allow dynamic-group ${DYNAMIC_GROUP_NAME} to manage functions-family in compartment id ${COMPARTMENT_OCID}

Set CREATE_SCHEDULER_IAM=true to let this script create those IAM artifacts.
EOF
  exit 0
fi

require_env TENANCY_OCID

matching_rule="ALL {resource.type='resourceschedule', resource.id='${schedule_ocid}'}"
policy_statement="Allow dynamic-group ${DYNAMIC_GROUP_NAME} to manage functions-family in compartment id ${COMPARTMENT_OCID}"
policy_statements_json="[$(json_escape "${policy_statement}")]"

echo "Creating scheduler dynamic group '${DYNAMIC_GROUP_NAME}'..."
"${OCI_CLI}" iam dynamic-group create \
  "${profile_args[@]}" \
  --compartment-id "${TENANCY_OCID}" \
  --name "${DYNAMIC_GROUP_NAME}" \
  --description "Resource Scheduler principal for fusion_audit function invocation" \
  --matching-rule "${matching_rule}"

echo "Creating scheduler policy '${SCHEDULER_POLICY_NAME}'..."
"${OCI_CLI}" iam policy create \
  "${profile_args[@]}" \
  --compartment-id "${TENANCY_OCID}" \
  --name "${SCHEDULER_POLICY_NAME}" \
  --description "Allow Resource Scheduler to invoke the fusion_audit function" \
  --statements "${policy_statements_json}"

echo "Scheduler IAM artifacts created."
