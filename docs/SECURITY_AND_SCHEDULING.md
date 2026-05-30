# Security and Scheduling

This guide covers the OCI CLI schedule, OCI IAM policies, Fusion roles, and Fusion SQL checks needed to run the Fusion audit extractor as a weekly OCI Function.

## Schedule the Function

OCI Functions are scheduled through OCI Resource Scheduler. For functions, Resource Scheduler supports a request body parameter, so the schedule can invoke the function with the same JSON payload used by `fn invoke`.

The helper script in `ops/schedule_function_sunday_night.sh` creates a static schedule for one function OCID and passes `examples/invoke.json` as the function body.

Example Sunday night schedule:

```bash
COMPARTMENT_OCID=ocid1.compartment.oc1..example \
FUNCTION_OCID=ocid1.fnfunc.oc1..example \
TIME_STARTS=2026-05-31T23:00:00Z \
PROFILE=DEFAULT \
bash ops/schedule_function_sunday_night.sh
```

Defaults:

- `RECURRENCE_DETAILS=0 23 * * 7`
- `INVOCATION_PAYLOAD_FILE=examples/invoke.json`
- `SCHEDULE_NAME=fusion-audit-sunday-night`

Resource Scheduler cron expressions use UTC only. `0 23 * * 7` means 23:00 UTC every Sunday. If the intended business time is Europe/Oslo Sunday night, choose the UTC time explicitly and remember that Resource Scheduler does not adjust for daylight saving time.

To use an OCI custom log payload instead of Kafka, point the schedule at an OCI-log invocation JSON:

```bash
INVOCATION_PAYLOAD_FILE=/path/to/oci-log-invoke.json \
COMPARTMENT_OCID=ocid1.compartment.oc1..example \
FUNCTION_OCID=ocid1.fnfunc.oc1..example \
TIME_STARTS=2026-05-31T23:00:00Z \
bash ops/schedule_function_sunday_night.sh
```

## OCI IAM

There are three OCI principals to consider:

- the administrator or deployment group that creates Terraform resources, deploys the function, and creates schedules
- the Resource Scheduler schedule that invokes the function
- the OCI Function resource principal that reads Vault secrets and writes to the selected target

Use compartment-scoped policies where possible. Replace all placeholders before applying.

### Deployer Group

The deployer needs permissions to manage the resources created by this project and the function deployment target.

```text
Allow group <deployer_group> to manage vaults in compartment <artifact_compartment>
Allow group <deployer_group> to manage keys in compartment <artifact_compartment>
Allow group <deployer_group> to manage secret-family in compartment <artifact_compartment>
Allow group <deployer_group> to manage stream-family in compartment <artifact_compartment>
Allow group <deployer_group> to manage logging-family in compartment <artifact_compartment>
Allow group <deployer_group> to manage functions-family in compartment <function_compartment>
Allow group <deployer_group> to use virtual-network-family in compartment <network_compartment>
Allow group <deployer_group> to manage repos in compartment <function_compartment>
Allow group <deployer_group> to manage resource-schedule-family in compartment <schedule_compartment>
```

If the same group must create IAM dynamic groups and policies, those IAM policies are usually created in the tenancy/root compartment and require IAM administration rights:

```text
Allow group <iam_admin_group> to manage dynamic-groups in tenancy
Allow group <iam_admin_group> to manage policies in tenancy
```

### Scheduler Principal

After the Resource Scheduler schedule is created, put that schedule in a dynamic group:

```text
ALL {resource.type='resourceschedule', resource.id='<resource_schedule_ocid>'}
```

Allow the schedule to invoke/start functions:

```text
Allow dynamic-group <scheduler_dynamic_group> to manage functions-family in compartment <function_compartment>
```

The helper script prints these statements after schedule creation. If `CREATE_SCHEDULER_IAM=true`, it can also create the dynamic group and policy using OCI CLI, provided the CLI principal has IAM administration rights.

### Function Resource Principal

Put the deployed function in a dynamic group:

```text
ALL {resource.type='fnfunc', resource.id='<function_ocid>'}
```

The function always needs to read Vault secret bundles:

```text
Allow dynamic-group <function_dynamic_group> to read secret-bundles in compartment <vault_compartment>
```

If the selected target is OCI Logging custom logs, the function also needs permission to push log content:

```text
Allow dynamic-group <function_dynamic_group> to use log-content in compartment <log_compartment>
```

If the selected target is Kafka through OCI Streaming Kafka compatibility, this project uses SASL credentials read from Vault. The OCI user whose auth token is stored in Vault must be in a group allowed to produce to the stream:

```text
Allow group <stream_producer_group> to use stream-push in compartment <stream_compartment>
```

To restrict the producer to one stream, use a condition:

```text
Allow group <stream_producer_group> to use stream-push in compartment <stream_compartment> where target.stream.id = '<stream_ocid>'
```

The function also needs network egress to:

- the Fusion ERP REST API endpoint
- the OCI Logging ingestion endpoint when `target` is `oci_log`
- the Kafka bootstrap endpoint when `target` is `kafka`

## Fusion Roles

Create a dedicated Fusion integration user for the function. Store that user's Fusion base URL, username, and password in OCI Vault.

Minimum runtime access:

- a custom job role such as `XX_FUSION_AUDIT_EXTRACT_JOB`
- the `View Audit History` privilege, code `FND_VIEW_AUDIT_HISTORY_PRIV`
- assignment of that custom job role to the integration user

Setup/admin access, not needed by the function at runtime:

- the `Manage Audit Policies` privilege, code `FND_MANAGE_AUDIT_POLICIES_PRIV`

Use the setup/admin privilege only for users who configure what Fusion objects and attributes are audited. Keep the runtime integration user limited to viewing audit history.

## Fusion SQL Verification

Use `sql/verify_fusion_audit_permissions.sql` in BI Publisher or another authorized Fusion reporting SQL tool to verify that the integration user has the required audit privilege.

Set the bind variable:

```text
:P_USER_LOGIN = <fusion_integration_user_login>
```

Expected result:

- `FND_VIEW_AUDIT_HISTORY_PRIV` must return for the integration user.
- `FND_MANAGE_AUDIT_POLICIES_PRIV` should return only for setup/admin users, not for the runtime function user.

Fusion reporting access to the `FUSION.ASE_*` security objects is controlled by Oracle and by your environment's reporting roles. If a query fails because a security table or view is not available to the reporting user, run it with a security/reporting administrator account or use Fusion Security Console role analysis to verify the same privileges.

## References

- [OCI Functions: Scheduling a Function](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/functionsscheduling.htm)
- [OCI Resource Scheduler: Creating a Schedule](https://docs.oracle.com/en-us/iaas/Content/resource-scheduler/tasks/create-manage.htm)
- [OCI Resource Scheduler IAM Policies](https://docs.oracle.com/en-us/iaas/Content/resource-scheduler/references/resource-scheduler-policies.htm)
- [OCI CLI: resource-scheduler schedule create](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/resource-scheduler/schedule/create.html)
- [OCI Functions Resource Principals](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/functionsaccessingociresources.htm)
- [OCI Vault Policy Reference](https://docs.oracle.com/iaas/Content/Identity/policyreference/keypolicyreference.htm)
- [OCI Streaming Policy Reference](https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/streamingpolicyreference.htm)
- [OCI Logging Policy Reference](https://docs.oracle.com/iaas/Content/Identity/policyreference/loggingpolicyreference.htm)
- [Fusion REST API: Get an audit report](https://docs.oracle.com/en/cloud/saas/applications-common/26b/farca/op-fscmrestapi-fndauditrestservice-audittrail-getaudithistory-post.html)
- [Fusion Audit Reports and View Audit History privilege](https://docs.oracle.com/en/cloud/saas/applications-common/26a/oacpr/view-audit-report.html)
- [Fusion Audit Policies and Manage Audit Policies privilege](https://docs.oracle.com/en/cloud/saas/sales/oasal/audit-policies.html)
- [Fusion Applications Security Tables](https://docs.oracle.com/cd/E51367_01/globalop_gs/OEDMH/ASE_tables.htm)
