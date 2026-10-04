package safeops.authz_test

import rego.v1

import data.safeops.authz

grant := {
	"incident_id": "INC-0042",
	"service": "inventory",
	"namespace": "inventory",
	"writable_paths": ["app/services/inventory/**"],
	"autonomy": "canary",
	"remediation_class": "code_patch",
	"approvals": [],
	"verified": false,
	"artifact": "",
	"status": "ACTIVE",
	"expires_at": 2000,
}

req(tool, request) := {"tool": tool, "grant": grant, "request": request, "now": 1000}

outcome(i) := o if {
	o := authz.decision.outcome with input as i
}

reasons(i) := r if {
	r := authz.decision.reasons with input as i
}

# ------------------------------------------------------------ legitimate work is allowed
test_read_own_logs_allowed if outcome(req("get_logs", {"service": "inventory"})) == "ALLOW"

test_patch_inside_scope_allowed if {
	outcome(req("submit_patch", {"paths": [
		"app/services/inventory/service.py",
		"app/services/inventory/tests/test_inventory.py",
	]})) == "ALLOW"
}

test_inspect_own_pods_allowed if {
	outcome(req("inspect_kubernetes", {"namespace": "inventory", "kind": "pods"})) == "ALLOW"
}

# ------------------------------------------------------------ hard denials
test_secret_read_hard_denied if outcome(req("read_secret", {"name": "db-password"})) == "DENY"

test_cluster_admin_hard_denied if outcome(req("grant_cluster_admin", {})) == "DENY"

test_iam_change_hard_denied if outcome(req("modify_iam", {})) == "DENY"

test_terraform_destroy_hard_denied if outcome(req("terraform_destroy", {})) == "DENY"

test_ai_can_never_promote_production if outcome(req("promote_production", {"service": "inventory"})) == "DENY"

test_unknown_tool_default_deny if outcome(req("run_shell", {"cmd": "rm -rf /"})) == "DENY"

# ------------------------------------------------------------ blast radius
test_cross_service_logs_denied if {
	r := reasons(req("get_logs", {"service": "payments"}))
	contains(r[0], "cross-service access to 'payments' denied")
}

test_cross_service_patch_denied if {
	outcome(req("submit_patch", {"paths": ["app/services/payments/service.py"]})) == "DENY"
}

test_one_bad_path_denies_whole_patch if {
	outcome(req("submit_patch", {"paths": [
		"app/services/inventory/service.py",
		"app/services/orders/service.py",
	]})) == "DENY"
}

test_path_traversal_denied if {
	outcome(req("submit_patch", {"paths": ["app/services/inventory/../payments/service.py"]})) == "DENY"
}

test_absolute_path_denied if outcome(req("submit_patch", {"paths": ["/etc/passwd"]})) == "DENY"

test_ai_cannot_edit_its_own_guardrails if {
	r := reasons(req("submit_patch", {"paths": ["automation/policy-engine/policies/safeops/authz.rego"]}))
	contains(r[0], "never writable by AI")
}

test_ai_cannot_edit_ci_or_dependencies if {
	outcome(req("submit_patch", {"paths": [".github/workflows/ci.yml"]})) == "DENY"
	outcome(req("submit_patch", {"paths": ["requirements.txt"]})) == "DENY"
}

test_other_namespace_denied if {
	outcome(req("inspect_kubernetes", {"namespace": "kube-system", "kind": "pods"})) == "DENY"
}

test_secrets_kind_never_readable if {
	outcome(req("inspect_kubernetes", {"namespace": "inventory", "kind": "secrets"})) == "DENY"
}

test_empty_patch_denied if outcome(req("submit_patch", {"paths": []})) == "DENY"

# ------------------------------------------------------------ autonomy ladder
test_low_autonomy_cannot_patch if {
	low := object.union(grant, {"autonomy": "diagnose"})
	i := object.union(req("submit_patch", {"paths": ["app/services/inventory/service.py"]}), {"grant": low})
	outcome(i) == "DENY"
}

test_restart_needs_low_risk_auto_and_restart_class if {
	outcome(req("restart_workload", {"service": "inventory"})) == "DENY"
	auto := object.union(grant, {"autonomy": "low_risk_auto", "remediation_class": "restart"})
	i := object.union(req("restart_workload", {"service": "inventory"}), {"grant": auto})
	outcome(i) == "ALLOW"
}

# ------------------------------------------------------------ verification, approval, kill switch
test_canary_requires_verification_and_artifact if {
	r := reasons(req("deploy_canary", {"service": "inventory"}))
	"patch has not passed verification" in r
	"no verified build artifact registered for this incident" in r
}

test_verified_canary_still_needs_human_approval if {
	g := object.union(grant, {"verified": true, "artifact": "ghcr.io/x/inventory@sha256:abc"})
	i := object.union(req("deploy_canary", {"service": "inventory"}), {"grant": g})
	outcome(i) == "REVIEW"
}

test_approved_verified_canary_allowed if {
	g := object.union(grant, {"verified": true, "artifact": "ghcr.io/x/inventory@sha256:abc", "approvals": ["deploy_canary"]})
	i := object.union(req("deploy_canary", {"service": "inventory"}), {"grant": g})
	outcome(i) == "ALLOW"
}

test_stopped_grant_denies_everything if {
	i := object.union(req("get_logs", {"service": "inventory"}), {"grant": object.union(grant, {"status": "STOPPED"})})
	outcome(i) == "DENY"
}

test_expired_grant_denies_everything if {
	i := object.union(req("get_logs", {"service": "inventory"}), {"now": 2000})
	outcome(i) == "DENY"
}
