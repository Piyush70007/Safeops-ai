# n8n: human-facing incident reports

n8n receives events from the control plane (SAFEOPS_N8N_WEBHOOK_URL) and informs humans.
It never authorizes anything: approvals go to the control plane API with an admin token.

Event payload (one per status change):
```json
{"type": "incident.awaiting_approval", "incident_id": "INC-20261003-EF11",
 "service": "inventory", "status": "AWAITING_APPROVAL", "title": "...",
 "decision": {"autonomy": "canary", "approval": "engineer", "confidence": 0.9},
 "tool_calls": {"ALLOW": 6, "REVIEW": 1, "DENY": 0}, "at": "2026-10-03T12:17:20+00:00"}
```

Workflow (build it in the n8n editor; labels can differ slightly between versions):
1. Webhook trigger, method POST, path `safeops-events`.
2. Switch on `{{ $json.type }}`: awaiting_approval, rejected, stopped, rolled_back, promoted.
3. For each branch a Slack/Teams/E-mail node with a message containing the incident ID,
   service, status and a link to `GET /incidents/<id>/report`.
4. For `awaiting_approval`: the message tells the engineer how to approve with the CLI or
   API. Do not put an approve button that calls the API with a stored admin token in n8n.
