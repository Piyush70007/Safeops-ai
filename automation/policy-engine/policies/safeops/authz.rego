# SafeOps AI - authorization policy for every tool call an AI worker requests.
#
# The model can ASK for anything. This policy decides, independently of the model,
# of JEV's confidence and of the worker's own instructions. Outcomes:
#   ALLOW  - the gateway executes the tool
#   REVIEW - a human must approve first (the gateway parks the request)
#   DENY   - never executed; recorded as a security event
package safeops.authz

import rego.v1

levels := data.catalog.autonomy_levels

tool := data.catalog.tools[input.tool]

# ---------------------------------------------------------------- hard denials
deny contains "tool is permanently prohibited for AI workers" if {
	input.tool in data.catalog.hard_denied_tools
}

deny contains "unknown tool (default deny)" if {
	not input.tool in data.catalog.hard_denied_tools
	not data.catalog.tools[input.tool]
}

deny contains "grant is not active" if input.grant.status != "ACTIVE"

deny contains "grant has expired" if input.now >= input.grant.expires_at

deny contains msg if {
	levels[input.grant.autonomy] < levels[tool.min_autonomy]
	msg := sprintf("autonomy '%s' is below the '%s' required by %s", [input.grant.autonomy, tool.min_autonomy, input.tool])
}

# ---------------------------------------------------------------- blast radius
deny contains msg if {
	requested := object.get(input.request, "service", input.grant.service)
	requested != input.grant.service
	msg := sprintf("cross-service access to '%s' denied: this incident is scoped to '%s'", [requested, input.grant.service])
}

deny contains msg if {
	requested := object.get(input.request, "namespace", input.grant.namespace)
	requested != input.grant.namespace
	msg := sprintf("namespace '%s' is outside the granted namespace '%s'", [requested, input.grant.namespace])
}

deny contains msg if {
	input.tool == "inspect_kubernetes"
	not input.request.kind in data.catalog.readable_kinds
	msg := sprintf("kind '%s' is not readable (secrets and config values are never exposed)", [input.request.kind])
}

deny contains msg if {
	some path in object.get(input.request, "paths", [])
	unsafe_path(path)
	msg := sprintf("path '%s' is not a clean relative path", [path])
}

deny contains msg if {
	some path in object.get(input.request, "paths", [])
	not unsafe_path(path)
	protected(path)
	msg := sprintf("path '%s' belongs to the platform or its guardrails and is never writable by AI", [path])
}

deny contains msg if {
	some path in object.get(input.request, "paths", [])
	not unsafe_path(path)
	not protected(path)
	not writable(path)
	msg := sprintf("path '%s' is outside the writable scope %v", [path, input.grant.writable_paths])
}

deny contains "submit_patch needs at least one changed path" if {
	input.tool == "submit_patch"
	count(object.get(input.request, "paths", [])) == 0
}

deny contains "patch has not passed verification" if {
	tool.requires_verified
	not input.grant.verified
}

deny contains "no verified build artifact registered for this incident" if {
	tool.requires_artifact
	object.get(input.grant, "artifact", "") == "" # an empty string is "defined" in Rego
}

deny contains msg if {
	tool.remediation_class
	input.grant.remediation_class != tool.remediation_class
	msg := sprintf("%s is only allowed for remediation class '%s'", [input.tool, tool.remediation_class])
}

unsafe_path(path) if contains(path, "..")

unsafe_path(path) if startswith(path, "/")

unsafe_path(path) if contains(path, "\\")

protected(path) if {
	some pattern in data.catalog.never_writable
	glob.match(pattern, ["/"], path)
}

writable(path) if {
	some pattern in input.grant.writable_paths
	glob.match(pattern, ["/"], path)
}

# ---------------------------------------------------------------- human approval
review contains msg if {
	tool.approval
	not input.tool in object.get(input.grant, "approvals", [])
	msg := sprintf("%s requires approval by: %s", [input.tool, tool.approval])
}

# ---------------------------------------------------------------- final decision
decision := {"outcome": "DENY", "reasons": sort([r | some r in deny])} if {
	count(deny) > 0
} else := {"outcome": "REVIEW", "reasons": sort([r | some r in review])} if {
	count(review) > 0
} else := {"outcome": "ALLOW", "reasons": []}
