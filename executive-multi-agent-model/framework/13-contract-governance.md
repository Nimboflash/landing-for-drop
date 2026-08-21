# 13 — Contract Governance

**Purpose.** How front-end, back-end, database, design, QA, and DevOps coordinate through a versioned
contract, so parallel work is safe and a contract change can never silently break a consumer.

> **Provenance banner.** Contract-first parallel work with a generated client is **Extracted** (the
> source's FE/BE seam). The full shared-contract object and the eight-step change procedure are a
> **Recommended** formalization.

## Contract-first is the unlock for parallelism

Parallel work is permitted **only after contracts and file ownership are established**. The reason is
the source's central coordination insight: *the interface is the coordination mechanism* — two agents
can build either side of a contract "without meeting," provided the contract is fixed first and the
consumer is generated from it rather than hand-written. So before front-end and back-end fan out, the
contract is defined, versioned, and approved; the front-end generates its typed client from the
contract schema and never hand-drifts from it.

## The shared implementation contract

A contract (`schemas/contract.schema.yaml`) is defined before parallel implementation begins and
includes: `contract_id, contract_version, feature_id, owners, affected_agents, user_flow,
acceptance_criteria, endpoints, request_schemas, response_schemas, error_schemas, authentication,
authorization, validation_rules, loading_states, empty_states, failure_states, success_states,
data_ownership, feature_flags, analytics_events, test_fixtures, mock_strategy,
compatibility_requirements, migration_requirements, rollback_requirements, approval_status`. The
contract is a shared, high-conflict artifact, so it has named owners and a required-reviewer set, and
it is registered in `projects/<slug>/state/contract-registry.yaml`.

## The eight-step contract-change procedure

A contract change is never a quiet edit. It follows exactly these steps:

1. Create a `contract_change` message.
2. Identify the affected agents.
3. Explain the compatibility impact (backward-compatible or breaking; a breaking change is a new
   version).
4. Receive acknowledgements from the affected agents (mandatory acknowledgement, per `08`).
5. Update (bump) the contract version.
6. Update project state (`contract_versions`).
7. Regenerate mocks or fixtures where needed.
8. Resume implementation **only after approval**.

Skipping any step is how two parallel agents end up building against different versions of the same
interface — the precise failure this procedure prevents.

## The cross-lane coordination pairs

The contract is the medium, but different pairs exchange different things across it:

- **Product ↔ Architecture** — Product sends problem definition, goals, non-goals, user journeys,
  business rules, acceptance criteria, and scope constraints. Architecture returns a feasibility
  assessment, technical risks, an architecture proposal, required trade-offs, missing technical
  requirements, and a dependency analysis.
- **Architecture ↔ Engineering** — Architecture sends the approved design, service boundaries, API
  and data contracts, technical constraints, and decisions. Engineering returns implementation
  questions, feasibility issues, contract conflicts, performance concerns, and implementation
  evidence.
- **Front-end ↔ Back-end** — coordinate strictly through the versioned contract; changes follow the
  eight steps above; the front-end consumes a generated client.
- **Back-end ↔ Database** — Back-end sends data-access requirements, transaction requirements, query
  patterns, performance expectations, and integrity requirements. Database returns the schema,
  migration, indexes, constraints, a rollback plan, and performance risks.
- **Engineering ↔ QA** — Engineering sends the feature handoff, requirements, acceptance criteria,
  changed files, test environment, known limitations, and automated test results. QA returns
  pass/fail, defects, reproduction steps, severity, regression impact, and a release recommendation.
- **Engineering ↔ Security** — Engineering sends architecture, authentication, authorization,
  dependency, data-handling, and infrastructure changes. Security returns findings, severity,
  blocking status, required remediation, and approval or rejection (with the scoped veto where it
  applies).
- **QA, Security, and Release** — the `release-manager` receives **independent** results from QA and
  from Security and must **not** rely only on an implementation agent's summary. This independence is
  what makes the release evidence trustworthy (see `14`).

## Reusable rules (recap)

- Fix and version the contract before parallel work; generate consumers from it, never hand-write.
- A contract change follows all eight steps, including acknowledgement and re-approval, before work
  resumes.
- Each coordination pair exchanges a defined set of inputs and returns; nothing crosses a lane
  informally.
- The release manager gets QA and Security evidence independently, never through the implementer.
- The contract registry records every contract and its current version.
