# AGENTS.md

`AGENTS.md` is the regular constitution, without a CLAUDE.md alias. As of 2026-11-07, retrofit preserves root code/history without retrospective acceptance.

## Hard rules — read these before any action

1. **Deliver gate-proved work; the user owns judgment and the destructive git surface.** Once a phase closes with every gate green, the orchestrator commits and fast-forward-pushes it; outside phases, a change is committed locally once the checks it could break pass, and one full gate on the exact tree qualifies the push — staging only its explicit paths (never `git add -A` or `git add .`, since this checkout may be shared), re-verifying the live tree and staged diff, and checking the resulting commit against the intended file list, with no agent credit and never `--no-verify`. Scope-owned nonforced routine completion cleanup follows [delivery resource disposition](policies/human-in-the-loop.md#delivery-resource-disposition); forced deletion and uncertain custody remain excluded. Everything else stays the user's: `git tag`, `git reset --hard`, `git branch -D`, `git rebase`, `git checkout --`, `git clean -fd`, force-pushing, creating or selecting a remote, and any history rewrite. An unexpected path in `git status`, a shared file whose hunks cannot be attributed safely, an **unresolved** hook refusal, a missing or ambiguous upstream, a rejected push, divergence, or residual dirt **parks delivery** — report it and wait; never work around it. A hook refusal whose cause the diagnostic names, whose defect is in the agent's own work, and whose correction is safe and already authorized is work to finish: correct it, rerun the rejecting check against the staged content, renew every gate whose candidate moved, and retry with all hooks enabled — never disable, bypass, weaken or conceal a hook, and never retry unchanged input. **Delivery is not acceptance.** Manual, perceptual, product, and custody criteria — and the phase's `User Demo:` protocol — stay open for the user *after* the work is delivered, and the orchestrator never claims them. What does block a phase from closing at all is an unresolved *gate*: a failed build gate, an unmet executable criterion, an open `DECIDE` ripple. Full policies: [`policies/human-in-the-loop.md`](policies/human-in-the-loop.md) and [`policies/commit-staging.md`](policies/commit-staging.md).

2. **Preserve existing public and retained-data contracts.** Keep current supported mirror readers, provenance, source-byte identity, privacy/configuration boundaries and independently installed PDF-engine boundary. A methodology transfer does not authorize product rewrites or removal of existing compatibility. New or breaking product contracts require their approved phase scope and truthful versioning; see [the receiving compatibility policy](policies/greenfield-until-released.md).

An explicit user restriction or scoped waiver is recorded verbatim in the owning immutable activity entry. Restrictions narrow delivery and never relax gates, permissions, custody or evidence preservation. The existing user authorization for the PPTX release governs its concrete qualified release actions; it is not permission to publish private operational material or unrelated changes.

<!-- PROJECT_CONTEXT_START -->

# Project Context

## Drawbridge

Python CLI/library: any supported file in, one provenance-headed Markdown mirror out. Preserve original bytes; return an inspectable mirror, typed failure or truthful deferred result. Paid/network stages require explicit privacy, egress and cost policy.

## Project briefs and surfaces

- [Project entry point](briefs/BRIEF.md)
- [Existing design](briefs/design.md)
- [Profiles and network stages](briefs/profile.md)
- [PowerPoint ingestion research](briefs/powerpoint-ingestion.md)
- [Word citation research](briefs/word-page-citations.md)

The root deliverable retains `src/drawbridge/`, `tests/`, runtime metadata, lock, build constraints and licenses; do not move it to project/. [Isolation policy](policies/project-isolation.md) records this adaptation. Root tests include product and governance proofs; preserve existing fixture behavior.

## Existing product invariants

- Python >=3.12; the existing runtime declaration, uv lock, package metadata, build constraints, license notices and independently licensed fixture grants remain authoritative.
- Vellric is an independently installed AGPL executable. Drawbridge's MIT runtime neither imports nor depends on Vellric, PyMuPDF or fitz. Real PDF/OCR qualification uses its explicit selected trusted executable and prerequisites.
- Content admission and typed failures remain truthful; extraction is not visual rendering. Original source hashes/ordinals and complete physical PDF citation maps are verified independently of untrusted Markdown headings, HTML and fences.
- Preserve credential scrubbing, explicit configuration precedence, local-only/no-AI restrictions, named egress and budgets. No implicit network/provider, linked-resource execution or credential expansion.
- Existing `docs/` files are first-party product guides, cataloged by [their index](docs/README.md). Third-party pins live under `references/`, with the complete catalog/no-outbound-links obligations in [reference policy](policies/docs.md). The optional local product manual lives under `manual/`; this grants no hosted deployment.
- The historical numbered plans and plan/README.md retain original bytes and original meanings. [Current discovery](plan/INDEX.md) distinguishes them from prospective `plan/phases/` and `plan/events/`. Do not fabricate historical completions, migrate closed review identities or reset consumed allowances.
- Private `local/` and `.kickoff/` evidence stays in existing custody and out of public source/distribution artifacts. Preserve original failures, advice, receipts and source history. Do not infer new claims from old evidence.

## Toolchain, workflow and delivery

Use `./bin/setup`, `./bin/test [repo-relative selections]`, `./bin/check all` and `./bin/python`. The root profile and real dependency probe own interpreter/lock selection; invalid explicit overrides fail without fallback. No broad product restyle is implied by governance adoption. The style/check applicability inventory names its actual covered paths; every existing product correctness test remains in the full lane.

The Methodology Contract governs transfers and product advice. Recipient kickoff.yaml/preflight owns routing/budgets; copy no donor runtime values or infer a writer, worktree, hook trust, global setting or service.

Keep existing origin/master and GitHub Releases; exact VCS dependencies preclude a package-index release. Delivery is not human acceptance. Full suites/builds require the coordinator's explicit heavy window; elapsed time never releases it.

<!-- PROJECT_CONTEXT_END -->

<!-- METHODOLOGY_CONTRACT_START -->

# Methodology Contract

## Methodology briefs

- [Eleven steps, doctrine and glossary](briefs/methodology.md)
- [Diagnosis and durable learning](briefs/rule-one-diagnostic-learning.md)
- [Portable bootstrap procedure](briefs/agentic-bootstrap.md)
- [Cross-CLI invocation contracts](briefs/cross-agent-invocation.md)
- [Candidate-bound incremental assurance](briefs/incremental-orchestration.md)
- [Command authority and custody](briefs/deterministic-orchestration-control-plane.md)
- [Draft deterministic workflow design](briefs/deterministic-orchestration.md)
- [Lessons and maintenance flywheel](briefs/harness-self-improvement.md)
- [Dated loading and continuity guidance](briefs/session-context-compaction.md)
- [Proof-estate design](briefs/test-suite-value-governance.md)
- [Minimal methodology scaffold](briefs/mini-method.md)
- [Reader-centered documentation](briefs/software-documentation.md)
- [Refactoring method and sources](briefs/refactoring-methodology.md)
- [Draft multi-operator collaboration](briefs/multi-operator-collaboration.md)
- [Open-source release design](briefs/open-source-releases.md)

## Policies catalog

Every applicable policy binds.

- [Policy catalog](policies/README.md)
- [Brief lifecycle](policies/briefs.md)
- [Authority direction](policies/briefs-and-policies.md)
- [Reference pins](policies/docs.md)
- [Software documentation](policies/software-documentation.md)
- [Mirrors and loading](policies/cross-harness-parity.md)
- [Roles and convergence](policies/four-canonical-agents.md)
- [Role routing](policies/role-models.md)
- [Role deadlines](policies/role-timeouts.md)
- [Research authority](policies/research-authority.md)
- [Evidence and close](policies/orchestration-evidence.md)
- [Command custody](policies/orchestration-control-plane.md)
- [Timing and reports](policies/execution-telemetry.md)
- [Scripts versus judgment](policies/mechanistic-vs-intelligence.md)
- [Staging](policies/commit-staging.md)
- [Build gates](policies/build-gates.md)
- [Test governance](policies/test-suite-governance.md)
- [Park/resume](policies/fail-closed-resume.md)
- [Review lanes](policies/review-lanes.md)
- [Multi-operator migration](policies/multi-operator-migration.md)
- [Phase state](policies/phase-status.md)
- [Ripple](policies/phase-ripple.md)
- [Acceptance](policies/acceptance-empirical.md)
- [User demos](policies/user-demo-protocols.md)
- [Treatise](policies/treatise.md)
- [Verification](policies/verification-discipline.md)
- [Log](policies/log-discipline.md)
- [User actions](policies/user-actions.md)
- [Lessons](policies/lessons.md)
- [Human judgment](policies/human-in-the-loop.md)
- [Paths](policies/repo-relative-paths.md)
- [Isolation](policies/project-isolation.md)
- [Simplicity](policies/simplicity-and-consolidation.md)
- [Greenfield](policies/greenfield-until-released.md)

## Universal repo layout

[reference catalog](references/README.md): third-party pins; [bin catalog](bin/README.md): executables. `lib/agentic_starter/`: shared machinery; `tests/`: independent proofs. `.githooks/`: opt-in via `bin/install-hooks`, witnessed by `bin/check-hooks-installed`. `reports/execution/`: sanitized reports; `reports/test-governance/`: recipient-local proofs. `log/entries/`: immutable history; `user-actions/` and `lessons/`: per-file queues with archive directories.

### Universal skills

- [kickoff](.claude/skills/kickoff/SKILL.md)
- [methodology](.claude/skills/methodology/SKILL.md)
- [rule-one](.claude/skills/rule-one/SKILL.md)
- [learn](.claude/skills/learn/SKILL.md)
- [teach](.claude/skills/teach/SKILL.md)
- [roles](.claude/skills/roles/SKILL.md)
- [sweep](.claude/skills/sweep/SKILL.md)
- [sweep-planning](.claude/skills/sweep-planning/SKILL.md)
- [sweep-coding](.claude/skills/sweep-coding/SKILL.md)
- [demo](.claude/skills/demo/SKILL.md)
- [treatise](.claude/skills/treatise/SKILL.md)
- [plain](.claude/skills/plain/SKILL.md)
- [ask](.claude/skills/ask/SKILL.md)
- [refactor](.claude/skills/refactor/SKILL.md)
- [mutate](.claude/skills/mutate/SKILL.md)
- [docs](.claude/skills/docs/SKILL.md)

### Canonical roles and mirrors

- [phase-planner](.claude/agents/phase-planner.md)
- [plan-reviewer](.claude/agents/plan-reviewer.md)
- [phase-coder](.claude/agents/phase-coder.md)
- [code-critic](.claude/agents/code-critic.md)

`.claude/` is canonical. `.agents/skills/<name>` → `../../.claude/skills/<name>` exposes all resources. `.codex/agents/<role>.toml` is a thin canonical pointer with matching description. Edit canonical sources. Product phases use `kickoff`; methodology follows the routing rule below.

## Phase work and the `kickoff` skill

Invoke `/kickoff` (Claude Code) or `$kickoff` (Codex). Read the [kickoff](.claude/skills/kickoff/SKILL.md) and each linked resource before its branch, including follow-ups/recovery; links do not prove reads. Limits: root 20480 UTF-8 bytes; entry 10240. Preserve obligations and catalogs; move explanation to its owner.

### Phase identity and status

`plan/phases/<id>.md` defines each permanent three-word phase id, title, rational order, parent, dependencies and informed phases. `plan/events/` is its append-only lifecycle and owner/claim authority; `plan/INDEX.md` is discovery context only. Use `./bin/multioperator select --root . --owner <operator>` (or `--phase <id>`) and verify real coordinated custody before starting. Each operator may queue one next phase; no global arrow or renumbering rule remains. Completion binds real accepted run inputs and current custody. Read [phase status](policies/phase-status.md).

### Reading protocol for phase work

1. Read `plan/INDEX.md` for context, then the canonical definitions/events for dependencies, order and custody.
2. Read the parent phase if targeting a child, then the target phase.
3. Read every Brief ref and every pinned document on which it depends.
4. Read the phase file of every `depends_on` id and the immediately preceding completed phase.
5. Read applicable policies, root invariants and the stage resource. Read only required phase files.

### Architectural invariants (load-bearing — do not violate)

Rationale: [methodology](briefs/methodology.md#operating-invariants-and-vocabulary).

- **Rules, not memory; Rule One.** Keep durable cross-harness knowledge in its owning repo authority. Diagnose failures, corrections, surprises and discarded work; separate containment, correction and prevention. File unsettled learning in `lessons/` and harvest every END/PARK, including `none`; only the human graduates rules.
- **Monotonic progress.** Hold authorized scope fixed; defer tangents once. Stop unsupported expansion. Dispatch authorized unblocked work or state the hold; inspect any command refusal before continuing.
- **Evidence over proxies.** Name the authoritative property, proxy, innocent triggers and sign-inversion risk. Read cited identifiers at their definitions; grep is a lead. Recheck affected callers, fixtures, tests and independent inventories.
- **Concrete uses; one home.** No speculative abstraction without a second present use. Consolidate at three copies; prefer fewer concepts. Use scripts for deterministic work and intelligence for contextual judgment.
- **Tests earn their cost.** Every test must address a plausible anticipated or demonstrated failure mode and add confidence worth its authoring, execution and maintenance cost. Do not test merely to restate behavior true by inspection or enumerate every possible invariant. Preserve necessary security and genuine protocol, boundary and contract checks based on credible risk and additional confidence. Neither trivial-looking code nor a deletion quota decides value; apply [test governance](policies/test-suite-governance.md#judging-a-proof).
- **Authority direction.** Policies prevail; plans refine and outrank briefs. Fix ambiguity at its owner; briefs never cite policies or plans as evidence. The documented migration-runbook handoff is navigation only.
- **Coherent outcomes.** Multiple surfaces and absent children do not require splitting. Split only at consequential decisions, independently accepted prerequisites, deployment/migration/human seams or demonstrated coherence limits. Ordinary internals belong to the coder; consequential scope stays approved. Never merge completed phases.
- **Empirical acceptance and product review.** Name the checks that could falsify each claim and the criteria only a human can judge. Find blockers broadly and report them together with their evidence; keep optional advice separate and finding identities stable across passes. Re-baseline review when authority, scope, risk or continuity changes. For a high-risk, large or cross-cutting correction, recommend an inserted phase, normally a sub-phase of the current one; if the operator instead rules it an inter-phase change without formal review, keep validation, tests, safety, permissions, scope and history intact. Formal reviews belong to phase work. Product primary mode uses advisory reviews: at most two passes per stage, the second for a recorded cause, plus the operator's single-use extra code review. Delegated mode keeps the role policy's limits on plan size, growth, stalls and ten cycles. Methodology work needs no independent review.
- **Candidate-bound assurance.** Review binds to the product's identity; gates and delivery bind to the whole tree's identity, which a gate must not change. Checks of declared authority and of reviewed bookkeeping stay independent of both. A tracked path with an unknown classification is refused; an untracked, unignored path of unknown classification, and `candidate-partition.yaml` itself, count as active.
- **Targeted candidate, one full run.** Focused iteration precedes product critique; methodology work is self-checked by the primary. The implementation-candidate sequence ends in the changed-path selection `./bin/test --changed-from '@{upstream}'`; accepted close precedes captured status mutation. After all bookkeeping, the one bare `./bin/check all` handoff gate qualifies the push; no tracked write follows success. Bind prospective child completion; parent completion requires separate acceptance.
- **Execution truth.** One append-only trace, exact joins and overlap-safe unions; separately report operator-input parks. Missing measurement is unknown, never zero. Give a refusing command its own block and read its diagnostic before the next command; repair and delivery are where chaining recurs. Finalize evidence before sanitized offline reports.
- **Safe acceleration.** Run independent required tests in parallel by default within resource limits; document concrete reasons for serial groups and prevent nested worker oversubscription. Use substantial, obvious low-risk time savings within scope, preserving correctness, coverage, determinism, the selected product review contract and both gates. No optimization tangents.
- **Atomic toolchain.** Runtime, metadata, lockfile, setup, focused/full tests, receipts, proofs and callers move together. Use repository wrappers; bad overrides and failed probes never fall back. Keep required evidence in durable private storage outside the reviewable tree or explicitly ignored; temporary storage is only disposable execution scratch.
- **Methodology routing.** All authorized methodology work, including `teach` and `learn`, is one-shot by the primary with commit and fast-forward-push authority after required checks. No delegated planning/coding or independent review/critique. Applies across harnesses and model tiers. Read [review lanes](policies/review-lanes.md).
- **Portable parity.** Canonical sources and thin mirrors; repo-relative committed paths; recipient-owned deliverable layout. Greenfield replacement and delivery/human-judgment boundaries follow the hard rules.

### Activity log (`log/entries/`)

Owning writers append new immutable entries with `multioperator append`; preserve exact bodies and per-writer predecessor sequences. Parks remain in progress; terminal records carry Lessons, evidence, remaining work and truthful outcomes.

### User actions (`user-actions/`)

Glob `user-actions/*.md` at session start; read frontmatter and surface dependencies before work. File human-only actions before ending; use `bin/new-name`, record dependencies/deferral and archive closed entries. Agents close only personally completed actions; GUI, console, pricing and billing checkoff stays human-only.

### Lessons (`lessons/`)

Read both lesson directories before filing/recurring; one row per observation. Run `./bin/lessons validate` and `./bin/lessons candidates`. Human ratification owns graduation/rejection. Harvest process observations and failure analysis at each close/park.

## Universal conventions

Never hard-wrap Markdown prose: one physical line per paragraph, including list-item prose. Preserve syntax-required breaks. Give one executable command per copyable shell fence. Use bare skill names in neutral prose and both harness invocation forms when showing commands. Follow `plain` for operator messages; peers retain full technical fidelity. Use User/operator/owner and they/them in durable role language; authorship credit is separate.

Agent decisions use kickoff’s input-park/`blocked-owner` route; unattended decisions park in artifacts. Only the operator invokes `ask`. Record rulings at their authority and human work in `user-actions/`.

## Glossary

Use the canonical [glossary](briefs/methodology.md#glossary); flag terminology mismatches.

<!-- METHODOLOGY_CONTRACT_END -->
