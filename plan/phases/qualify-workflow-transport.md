---
id: qualify-workflow-transport
title: Qualify bounded transport and exact-source CI control
order: 11/4
parent: pptx-release-qualification
depends_on:
- qualify-release-artifacts
informs:
- pptx-release-qualification
review_lane: full
evidence_lane: full
---

# Qualify bounded transport and exact-source CI control

## Goal

Deliver a narrowly qualified controller workflow on existing master that can run the unchanged full CI pipeline against the exact existing signed 0.3.0 release source, with bounded transient handling for the two existing Vellric release downloads. Preserve the release source, tag object, artifacts, every pin and all original failed runs.

## Decomposition

This child is the authorized independent controller-source delivery prerequisite. Its acceptance and signed master delivery precede the parent's one separately identified actual workflow_dispatch qualification. It does not claim that future external run, close the parent, publish a release or recreate a tag. The parent receives a fresh reviewed plan for the changed evidence route; original advice and consumed allowances remain history rather than approval of new semantics.

## Pinned decisions and boundaries

The fixed release source is 442afd5fcbc726a3683b209102eb0f42125b5aff; the existing signed v0.3.0 tag object is 55693cadf79bdeb0cbb84cabf5c99702f4ec1dd0 and peels to that source. The later controller commit and workflow blob are separately qualified and recorded, never assumed equal to the release source. Keep original ordinary push, pull-request and manual qualification behavior. Add an explicit manual release-qualification mode using fixed release identities, validated controller/blob/request identities and exact checkout; no arbitrary source execution input or new permission is introduced.

Retain contents:read, existing action pins, runner/job bound, dependency/OCR/setup/install/test steps and canonical Vellric URLs/hashes. Bound only the two Vellric asset fetches to at most three attempts per asset, finite connection/request/total time, explicit transient classifications and per-attempt diagnostics. Fatal/auth/not-found/hash mismatch and unclassified failures stop; verified bytes are promoted only after SHA256. No retry-all-errors, alternate asset/host, local recovered-file injection, provider access change or global setup.

Keep transport/identity code inline in the controller workflow so checkout of the older release source cannot silently replace or omit a new helper. Bind actual workflow SHA/blob, source HEAD, tag object/peel, request nonce, event and repository in the specialized mode. Never claim the three failed tag-push attempts passed. Ordinary source and public package behavior remain unchanged.

The bounded local qualification-instrument correction starts the watcher's command execution clocks after successful launch admission and immediately before process creation. Preserve every configured first-event, idle and hard limit, launch-claim order/accounting, refusal, process-group/teardown behavior and telemetry join. A safe synthetic delayed-admission counterexample establishes this boundary defect; it does not establish the mechanism of an earlier timeout or permission diagnostic, or replace missing historical process evidence. Keep the earlier failed run immutable and rebind the current authority and advice before qualification. This is a local correction, with no upstream methodology proposal or edit.

## Deliverables

- Update only the existing qualification workflow's explicit controller/source qualification mode and two-asset transient transport handling, preserving every other runtime step and pin.
- Add focused production-boundary transport and identity proof with credible refusal/exhaustion/byte-integrity cases and actual authoring witnesses; extend only the required local proof mapping/ledgers.
- Correct only the local watcher command-clock boundary in bin/kickoff-config and add bounded timing, exception/accounting and telemetry regression proof in tests/test_kickoff_config.py, preserving existing guards and tests.
- Reconcile all existing attributable parent START/PARK entries and execution lineage without rewriting them; keep private operational evidence outside public artifacts.
- Run actual focused/static preservation checks, changed-path selection last, accepted child close with truthful parent continuation, tracked bookkeeping and a separately scheduled bare full handoff before normal signed master delivery.

## Acceptance

Executable: bounded transient fetch succeeds for valid bytes and refuses exhausted/fatal/unclassified/corrupt outcomes; source/tag/controller/blob/nonce identity mismatches cannot qualify; normal triggers retain their existing checkout and full steps; action/dependency/OCR/runtime test definitions remain unchanged apart from the admitted qualification/fetch delta; original source/tag/assets and failed evidence remain preserved; current candidate/gates/authoring receipts, accepted close and bare handoff are genuine. No source release or dependency bytes are replaced and no fourth old tag-push rerun occurs.

The parent must separately dispatch the qualified controller revision and prove exact tested-source identity, full CI success and complete diagnostics before unchanged public release/readback and its own acceptance/handoff. Child proof is not that external result. Human sample readability/suitability stays open and nonblocking; CSV, new versions, Starter work, permissions and unrelated product behavior remain excluded.

The local instrument proof must show that delayed admission cannot spend the child's execution budget, genuine first-event silence still refuses within the same limit, and admission/process-creation errors retain no-child/cancellation accounting and truthful timestamps. No denied signal retry, process-scan workaround or timeout increase is admitted. Historical cleanup uncertainty remains recorded rather than relabeled as a successful observation.

User Demo: N/A — this prerequisite introduces only CI controls exercised by automated guards. The existing release parent's actual public download and first-party sample review remains open; no user-facing extraction behavior changes here.

## Brief refs

- [Project entry point](../../briefs/BRIEF.md)
- [PowerPoint ingestion research](../../briefs/powerpoint-ingestion.md)

## Pinned platform contracts

- [Manual trigger](../../references/github-actions-20261108/manual-trigger.txt) and [dispatch API](../../references/github-actions-20261108/dispatch-api.txt).
- [Workflow identity](../../references/github-actions-20261108/workflow-identity.txt) and [pinned checkout ref](../../references/github-actions-20261108/checkout-ref.txt).
