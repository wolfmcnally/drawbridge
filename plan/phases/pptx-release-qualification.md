---
id: pptx-release-qualification
title: Qualify and publish the PPTX release
order: '2'
parent: null
depends_on:
- powerpoint-slide-ingestion
informs: []
review_lane: full
evidence_lane: full
---

# Qualify and publish the PPTX release

## Goal

Publish a truthful qualified Drawbridge release to its established GitHub Releases destination after PPTX ingestion is accepted and required release decisions are settled.

## Decomposition

The independently accepted qualify-release-artifacts child owns final-version source, public artifact and installed-runtime qualification and normal source delivery. This parent remains active for actual final-source CI, signed tag creation, GitHub publication and downloaded asset readback. A child completion includes a truthful parent_continuation reason and cannot close this parent. The parent receives its own real primary plan/code advice, acceptance and final handoff; child acceptance is not substituted for it.

## Inherited source qualification

The accepted ingestion source identifies itself as 0.3.0.dev0 and emits drawbridge.mirror.v2 only for slides, preserving v1 behavior. Native ordinary transitional PPTX ingestion, associated notes selection and complete slide/asset accounting were qualified on macOS arm64 and Linux aarch64 with Python 3.12.12. Rendering, binary/macro/template/Strict ingestion, Windows and Linux x86 runtime qualification were not claimed. Release qualification must preserve these boundaries, qualify the actual release version and artifacts, and keep the ingestion User Demo open until the operator performs it. The established branch and destination are origin/master and GitHub Releases; no package-index release is implied.

## Release boundary and decisions

The selected final version is 0.3.0, the regular minor successor to published 0.2.0 and promotion of the accepted 0.3.0.dev0 source. Existing v1 contracts remain supported; slide mirrors use the already-approved v2 contract. Keep the established master branch, existing GitHub Releases destination, exact dependency pins and original licensing/source history. Publish only the qualified wheel and source tarball; no package-index upload, raw private proof, downloaded deck or dependency binaries. These are the existing release outcome and ordinary version/artifact choices; no new product behavior or access is introduced.

The operator-directed publication seam keeps actual publication and remote readback as objective parent requirements. The retained maintainer checkout must run its full private historical audit and bare gate. Fresh public wheel/source and installed conversion are separate proofs. A public clone cannot replay the private historical-acceptance portion of the full gate; document that limitation without relaxing a check or treating it as an extra release gate. No Starter changes are proposed. Human sample acceptance remains open, and the CSV alias remains excluded.

## Deliverables

- Freeze a version consistent with actual mirror/API changes and update current installation/usage/release claims.
- Qualify locked tests, independently installed PDF/OCR boundary, package/notice/dependency/source contents and installation outside the source checkout.
- Observe required CI and release actions through terminal results; inspect the exact public files and verify published asset identity.
- Retain private operational evidence and original failures; publish no credentials, client material, internal logs or unrelated records.

## Acceptance

Executable: required candidate/handoff gates, complete build diagnostics, installed conversion and artifact/license/security checks, and actual destination asset readback. Human: visible product review and any applicable platform acceptance remain explicitly open unless actually performed. No new repository, cloud service, credentials, package-index upload or unqualified platform/rendering claim.

User Demo: Download the published 0.3.0 wheel and matching source archive from the existing GitHub release, follow the installation guide, create the first-party sample from matching source, convert with notes included and excluded, and verify against the original deck. Open the mirror and judge the slide order, labelled associated notes and readability. This is human acceptance, not a condition already answered by automated extraction or publication.

## Brief refs

- [Project entry point](../../briefs/BRIEF.md)
- [PowerPoint ingestion research](../../briefs/powerpoint-ingestion.md)
