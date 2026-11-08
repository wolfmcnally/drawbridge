---
id: qualify-release-artifacts
title: Qualify the final PowerPoint release artifacts
order: 5/2
parent: pptx-release-qualification
depends_on:
- powerpoint-slide-ingestion
informs:
- pptx-release-qualification
review_lane: full
evidence_lane: full
---

# Qualify the final PowerPoint release artifacts

## Goal

Deliver the gate-qualified 0.3.0 source and exact public wheel/source artifacts, preserving the accepted PPTX implementation and all existing contracts. Leave the release parent active for actual CI, signing/tag publication and public asset readback.

## Decomposition

This is the independently accepted prerequisite at the explicit source-delivery/publication seam. It adds no product behavior, services, dependency upgrades, CSV alias or Starter work. Ordinary implementation and focused checks stay on the current primary; plan and code advice use the qualified independent venue.

## Decisions and scope

Promote 0.3.0.dev0 to regular version 0.3.0 consistently in package metadata, import version, lock metadata and public install/release guides. Keep all other locked versions and sources identical. Retain ordinary native PPTX and source-preserving v1/v2 behavior, explicit notes selection, independent Vellric and current platform limits. Qualify installed behavior on macOS arm64 and Linux aarch64 with Python 3.12.12; do not claim visual rendering, Windows or additional installed platforms.

The existing maintainer checkout owns private historical proof and required full gates. Public artifacts and fresh installed use are proved independently. Document public-clone audit limitations and the corrected local lesson; preserve the observed optional-check refusal without making it a new gate. Preserve original failures, phase claims, writer custody and history. No raw private proof enters public source/distribution assets.

## Deliverables

- Freeze Drawbridge version 0.3.0 across metadata, import version and current install/use/release claims, without changing existing dependency versions or sources.
- Document actual PowerPoint/PDF/version/platform/privacy/license boundaries and the public-source versus private-maintainer validation distinction.
- Build and inspect exact allowlisted wheel and source archive with locked constraints, complete public source/member equality and notices; retain regular proof outputs apart from disposable runtimes.
- Prove fresh offline installed PPTX API/CLI/configuration/verification on macOS arm64 and Linux aarch64, plus independent native/configured/real OCR PDF behavior on the qualified host.
- Run current candidate assurance and changed-path selection last, accepted close with truthful parent continuation, tracked bookkeeping and one separately scheduled bare full handoff before signed nonforced master source delivery.

## Acceptance

Executable: metadata/import/CLI versions agree at 0.3.0; old dependency pins/sources remain equal; actual public wheel/source members and licenses match allowlists with private material excluded; fresh installed native/configured/OCR/PPTX proofs pass on their named platforms; complete diagnostics and current-candidate identity are recorded. The maintainer's full historical validation and all existing required tests remain intact. Implementation qualification ends in changed-from selection; one post-bookkeeping bare full gate qualifies source delivery. No public tag or release is claimed by this child.

Human: the existing first-party sample readability/suitability review remains open and nonblocking. Parent publication, remote CI, tag and downloaded asset readback remain objective work for the parent, not human acceptance or completed child results.

User Demo: Install the candidate wheel in an isolated environment using the matching source/lock instructions, generate the first-party sample from matching source, convert it with associated notes, verify the original four-slide inventory and compare explicit notes exclusion. Open the two mirrors and judge readability and slide/note placement. The release parent supplies the eventual public download URLs; no publication is claimed here.

## Brief refs

- [Project entry point](../../briefs/BRIEF.md)
- [PowerPoint ingestion research](../../briefs/powerpoint-ingestion.md)
