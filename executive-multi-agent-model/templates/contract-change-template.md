<!-- Conforms to schemas/contract.schema.yaml + schemas/message.schema.yaml (type:
     contract_change). Provenance: Partially extracted — contract-first coordination between
     frontend/backend (co-owned contract, generated typed client, "breaking change = new
     version") is real source behavior (evidence-digest §1, §2 stage 13); the 8-step procedure
     below formalizes it into a repeatable sequence. -->

# Contract Change Template

Any change to an API/data contract follows this 8-step procedure. Do not skip steps under
deadline pressure — non-negotiables (which include contract discipline) outrank deadlines.

---

## The 8-step procedure

1. **Create a `contract_change` message** describing the proposed change (see fields below).
2. **Identify affected agents** — every agent listed in the contract's `affected_agents` field,
   plus any agent whose task currently pins the old `contract_version`.
3. **Assess compatibility impact** — is this additive (non-breaking) or breaking? A field
   addition with a default is usually additive; a field removal, rename, or semantic change is
   breaking.
4. **Collect acknowledgements** from every affected agent identified in step 2. Acknowledgement
   is REQUIRED (per message protocol) whenever scope/contracts change — silence does not count.
5. **Bump `contract_version`** — breaking changes get a new major-equivalent version; additive
   changes may bump minor. Never silently mutate a contract version in place.
6. **Update project state** — `contract_versions` field in `project-state.yaml`, owned by the
   contract's respective owner (not the orchestrator).
7. **Regenerate mocks/fixtures** — any generated client, test fixture, or mock strategy tied to
   this contract must be regenerated before any agent builds against the new version.
8. **Resume only after approval** — no task consuming this contract proceeds past the affected
   step until the new version's approval_status is confirmed.

---

## `contract_change` message fields

```yaml
type: contract_change
from_agent: <PLACEHOLDER canonical_id — usually the contract owner proposing the change>
to_agent: <PLACEHOLDER — send to each affected agent, or use a broadcast pattern per your
  message-transport convention>
subject: <PLACEHOLDER — one line describing the change>
context: <PLACEHOLDER — why the change is needed>
requested_action: <PLACEHOLDER — "acknowledge and update your consuming code to
  contract_version X">
blocking: true
approval_required: <true|false — true if the compatibility assessment found a breaking change>
evidence_refs: <PLACEHOLDER>
status: open
```

## Changed contract fields (from `contract.schema.yaml`)

```yaml
contract_id: <PLACEHOLDER>
contract_version: <PLACEHOLDER — the NEW version>
feature_id: <PLACEHOLDER>
owners: <PLACEHOLDER>
affected_agents: <PLACEHOLDER list>
user_flow: <PLACEHOLDER>
acceptance_criteria: <PLACEHOLDER>
endpoints: <PLACEHOLDER>
request_schemas: <PLACEHOLDER — highlight what changed>
response_schemas: <PLACEHOLDER — highlight what changed>
error_schemas: <PLACEHOLDER>
authentication: <PLACEHOLDER>
authorization: <PLACEHOLDER>
validation_rules: <PLACEHOLDER>
loading_states: <PLACEHOLDER>
empty_states: <PLACEHOLDER>
failure_states: <PLACEHOLDER>
success_states: <PLACEHOLDER>
data_ownership: <PLACEHOLDER>
feature_flags: <PLACEHOLDER | none>
analytics_events: <PLACEHOLDER | none>
test_fixtures: <PLACEHOLDER — must be regenerated per step 7>
mock_strategy: <PLACEHOLDER — must be regenerated per step 7>
compatibility_requirements: <PLACEHOLDER — what must remain compatible, if anything>
migration_requirements: <PLACEHOLDER — how consumers move from old to new version>
rollback_requirements: <PLACEHOLDER>
approval_status: <pending|approved|approved_with_conditions|rejected>
```

---

## Filled mini-example

```yaml
# Step 1 — contract_change message
type: contract_change
from_agent: backend-engineer
to_agent: frontend-engineer
subject: "Add lastSeenAt field to CONTRACT-PRESENCE payload"
context: >
  Frontend needs a last-seen timestamp for the presence indicator UI (see BLOCKER-2026-07-13-03).
  This is an additive field with a default of null for currently-connected clients.
requested_action: "Acknowledge and rebuild your generated client against CONTRACT-PRESENCE-v2"
blocking: true
approval_required: false   # additive, non-breaking — no human approval required
evidence_refs: [BLOCKER-2026-07-13-03]
status: open

# Step 2 — affected agents
affected_agents: [frontend-engineer, qa-engineer]

# Step 3 — compatibility impact
compatibility_assessment: "Additive. New field, nullable, default null. Existing consumers
  unaffected if they ignore unknown fields (already the case per API_GUIDELINES.md)."

# Step 4 — acknowledgements collected
acknowledgements:
  - agent: frontend-engineer
    acknowledged_at: 2026-07-13T17:00:00Z
  - agent: qa-engineer
    acknowledged_at: 2026-07-13T17:05:00Z

# Step 5 — version bump
contract_id: CONTRACT-PRESENCE
contract_version: v2   # bumped from v1, minor/additive
approval_status: approved

# Step 6 — project state updated
project_state_update: "contract_versions.CONTRACT-PRESENCE = v2 (updated by backend-engineer,
  the contract owner — not by orchestrator)"

# Step 7 — mocks/fixtures regenerated
test_fixtures: "tests/fixtures/presence_v2.json regenerated"
mock_strategy: "Frontend typed client regenerated from OpenAPI spec v2"

# Step 8 — resume
resume_condition: "TASK-AB-144 and TASK-AB-145 (previously blocked) resume now that
  contract_version v2 is approved and fixtures are regenerated."
```
