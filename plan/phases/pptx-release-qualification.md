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

Separate release seam. Elaborate this sketch from the actual accepted product candidate; do not choose the version or claim cross-platform qualification in advance.

## Inherited source qualification

The accepted ingestion source identifies itself as 0.3.0.dev0 and emits drawbridge.mirror.v2 only for slides, preserving v1 behavior. Native ordinary transitional PPTX ingestion, associated notes selection and complete slide/asset accounting were qualified on macOS arm64 and Linux aarch64 with Python 3.12.12. Rendering, binary/macro/template/Strict ingestion, Windows and Linux x86 runtime qualification were not claimed. Release qualification must preserve these boundaries, qualify the actual release version and artifacts, and keep the ingestion User Demo open until the operator performs it. The established branch and destination are origin/master and GitHub Releases; no package-index release is implied.

## Deliverables

- Freeze a version consistent with actual mirror/API changes and update current installation/usage/release claims.
- Qualify locked tests, independently installed PDF/OCR boundary, package/notice/dependency/source contents and installation outside the source checkout.
- Observe required CI and release actions through terminal results; inspect the exact public files and verify published asset identity.
- Retain private operational evidence and original failures; publish no credentials, client material, internal logs or unrelated records.

## Acceptance

Executable: required candidate/handoff gates, complete build diagnostics, installed conversion and artifact/license/security checks, and actual destination asset readback. Human: visible product review and any applicable platform acceptance remain explicitly open unless actually performed. No new repository, cloud service, credentials, package-index upload or unqualified platform/rendering claim.

User Demo: To be specified against the actual installed release and published artifacts during phase elaboration.

## Brief refs

- [Project entry point](../../briefs/BRIEF.md)
- [PowerPoint ingestion research](../../briefs/powerpoint-ingestion.md)
