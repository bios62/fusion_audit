/*
  Verify Fusion audit privileges for the integration user used by fusion_audit.

  Run in BI Publisher or another authorized Fusion SQL/reporting tool.

  Bind variable:
    :P_USER_LOGIN  Fusion user login for the integration/service user.

  Required runtime privilege:
    FND_VIEW_AUDIT_HISTORY_PRIV

  Setup/admin privilege, not required for runtime extraction:
    FND_MANAGE_AUDIT_POLICIES_PRIV

  The queries use FUSION.ASE_* security objects documented by Oracle. Access to
  these objects depends on the reporting/security role of the user running the
  query.
*/

/* 1. Direct roles assigned to the Fusion user. */
SELECT
    u.user_login,
    r.code AS role_code,
    r.role_name,
    r.role_type_code,
    urm.effective_start_date,
    urm.effective_end_date
FROM fusion.ase_user_b u
JOIN fusion.ase_user_role_mbr urm
    ON urm.user_id = u.user_id
JOIN fusion.ase_role_vl r
    ON r.role_id = urm.role_id
WHERE UPPER(u.user_login) = UPPER(:P_USER_LOGIN)
  AND TRUNC(SYSDATE) BETWEEN NVL(TRUNC(urm.effective_start_date), DATE '1900-01-01')
                         AND NVL(TRUNC(urm.effective_end_date), DATE '4712-12-31')
ORDER BY
    r.role_type_code,
    r.role_name;

/* 2. Required audit privileges inherited through direct and nested roles. */
WITH
direct_roles AS (
    SELECT
        u.user_login,
        r.role_id AS assigned_role_id,
        r.code AS assigned_role_code,
        r.role_name AS assigned_role_name
    FROM fusion.ase_user_b u
    JOIN fusion.ase_user_role_mbr urm
        ON urm.user_id = u.user_id
    JOIN fusion.ase_role_vl r
        ON r.role_id = urm.role_id
    WHERE UPPER(u.user_login) = UPPER(:P_USER_LOGIN)
      AND TRUNC(SYSDATE) BETWEEN NVL(TRUNC(urm.effective_start_date), DATE '1900-01-01')
                             AND NVL(TRUNC(urm.effective_end_date), DATE '4712-12-31')
),
active_role_edges AS (
    SELECT
        parent_role_id,
        child_role_id
    FROM fusion.ase_role_role_mbr
    WHERE TRUNC(SYSDATE) BETWEEN NVL(TRUNC(effective_start_date), DATE '1900-01-01')
                             AND NVL(TRUNC(effective_end_date), DATE '4712-12-31')
),
role_closure AS (
    SELECT
        CONNECT_BY_ROOT parent_role_id AS assigned_role_id,
        child_role_id AS role_id,
        LEVEL AS role_depth
    FROM active_role_edges
    START WITH parent_role_id IN (
        SELECT assigned_role_id
        FROM direct_roles
    )
    CONNECT BY NOCYCLE PRIOR child_role_id = parent_role_id
),
effective_roles AS (
    SELECT
        dr.user_login,
        dr.assigned_role_id,
        dr.assigned_role_code,
        dr.assigned_role_name,
        dr.assigned_role_id AS role_id,
        dr.assigned_role_code AS role_code,
        dr.assigned_role_name AS role_name,
        0 AS role_depth
    FROM direct_roles dr
    UNION
    SELECT
        dr.user_login,
        dr.assigned_role_id,
        dr.assigned_role_code,
        dr.assigned_role_name,
        rc.role_id,
        r.code AS role_code,
        r.role_name,
        rc.role_depth
    FROM role_closure rc
    JOIN direct_roles dr
        ON dr.assigned_role_id = rc.assigned_role_id
    JOIN fusion.ase_role_vl r
        ON r.role_id = rc.role_id
),
audit_privileges AS (
    SELECT DISTINCT
        er.user_login,
        er.assigned_role_code,
        er.assigned_role_name,
        er.role_code AS effective_role_code,
        er.role_name AS effective_role_name,
        er.role_depth,
        p.code AS privilege_code,
        p.name AS privilege_name
    FROM effective_roles er
    JOIN fusion.ase_priv_role_mbr prm
        ON prm.role_id = er.role_id
    JOIN fusion.ase_privilege_vl p
        ON p.privilege_id = prm.privilege_id
    WHERE p.code IN (
        'FND_VIEW_AUDIT_HISTORY_PRIV',
        'FND_MANAGE_AUDIT_POLICIES_PRIV'
    )
      AND TRUNC(SYSDATE) BETWEEN NVL(TRUNC(prm.effective_start_date), DATE '1900-01-01')
                             AND NVL(TRUNC(prm.effective_end_date), DATE '4712-12-31')
)
SELECT
    user_login,
    privilege_code,
    privilege_name,
    assigned_role_code,
    assigned_role_name,
    effective_role_code,
    effective_role_name,
    role_depth
FROM audit_privileges
ORDER BY
    privilege_code,
    assigned_role_name,
    role_depth,
    effective_role_name;

/* 3. PASS/FAIL summary for the runtime extraction privilege. */
WITH
direct_roles AS (
    SELECT
        u.user_login,
        r.role_id AS assigned_role_id
    FROM fusion.ase_user_b u
    JOIN fusion.ase_user_role_mbr urm
        ON urm.user_id = u.user_id
    JOIN fusion.ase_role_vl r
        ON r.role_id = urm.role_id
    WHERE UPPER(u.user_login) = UPPER(:P_USER_LOGIN)
      AND TRUNC(SYSDATE) BETWEEN NVL(TRUNC(urm.effective_start_date), DATE '1900-01-01')
                             AND NVL(TRUNC(urm.effective_end_date), DATE '4712-12-31')
),
active_role_edges AS (
    SELECT
        parent_role_id,
        child_role_id
    FROM fusion.ase_role_role_mbr
    WHERE TRUNC(SYSDATE) BETWEEN NVL(TRUNC(effective_start_date), DATE '1900-01-01')
                             AND NVL(TRUNC(effective_end_date), DATE '4712-12-31')
),
role_closure AS (
    SELECT
        CONNECT_BY_ROOT parent_role_id AS assigned_role_id,
        child_role_id AS role_id
    FROM active_role_edges
    START WITH parent_role_id IN (
        SELECT assigned_role_id
        FROM direct_roles
    )
    CONNECT BY NOCYCLE PRIOR child_role_id = parent_role_id
),
effective_roles AS (
    SELECT assigned_role_id AS role_id
    FROM direct_roles
    UNION
    SELECT role_id
    FROM role_closure
),
runtime_privilege AS (
    SELECT 1 AS found_flag
    FROM effective_roles er
    JOIN fusion.ase_priv_role_mbr prm
        ON prm.role_id = er.role_id
    JOIN fusion.ase_privilege_vl p
        ON p.privilege_id = prm.privilege_id
    WHERE p.code = 'FND_VIEW_AUDIT_HISTORY_PRIV'
      AND TRUNC(SYSDATE) BETWEEN NVL(TRUNC(prm.effective_start_date), DATE '1900-01-01')
                             AND NVL(TRUNC(prm.effective_end_date), DATE '4712-12-31')
)
SELECT
    :P_USER_LOGIN AS user_login,
    CASE
        WHEN COUNT(*) > 0 THEN 'PASS: user can view Fusion audit history'
        ELSE 'FAIL: user is missing FND_VIEW_AUDIT_HISTORY_PRIV'
    END AS audit_runtime_access
FROM runtime_privilege;
