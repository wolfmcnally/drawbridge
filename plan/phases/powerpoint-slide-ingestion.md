---
id: powerpoint-slide-ingestion
title: Ordinary PowerPoint slide ingestion
order: '1'
parent: null
depends_on: []
informs: []
review_lane: full
evidence_lane: full
---

# Ordinary PowerPoint slide ingestion

## Goal

Add qualified deterministic native ingestion of ordinary transitional .pptx presentations using the existing research. Preserve original source identity, canonical slide order, hidden/text-free slide accounting, separate notes and asset inventory, with truthful completeness and unsupported-content outcomes.

## Decomposition and decisions

One coherent native ingestion outcome, elaborated on 2026-11-08 from the existing researched brief. Existing historical PDF work remains separately preserved. Full plan advice and code advice apply; implementation stays on the primary. Gate-proved source is committed and fast-forward-pushed to existing origin/master; publication remains the separate dependent release phase.

Operator ruling: “1. Per-slide speaker notes should be associated with the slide content to which they apply. If whole-deck speaker notes are supported, they should appear at the start. 2. Yes. Represent each fully built slide as a section. Do not break out individual builds.” This affirms the presented new slide-format proposal while preserving existing v1 behavior. It does not establish a blanket notes inclusion/exclusion preference.

Newly pinned decisions: ordinary transitional .pptx only; native extraction without visual-render fidelity; new drawbridge.mirror.v2 slide mirrors while existing v1 generation/reading remains supported; exactly one section per source slide with all stored shape text, never one section per animation/build step; present speaker notes associated with their slide, with any explicitly supported whole-deck notes preceding slides. Whole-deck notes are conditional: notes-master boilerplate is not deck notes and no absent notes are manufactured. Native extraction cannot reconstruct animation visibility or promise a rendered final frame. Notes selection is explicit in provenance and supports exclusion through the existing API/CLI/configuration precedence; the engineering default follows the brief's local preservation recommendation without attributing an additional preference to the operator. Embedded attachments are inventoried, not exported or executed. No linked resource is fetched. These choices and the phase elaboration itself are included in independent plan advice.

## Deliverables

- Qualify ordinary .pptx package admission and a maintained permissive reader with current exact dependency/security/license evidence.
- Extend the mirror contract deliberately for slide identity and metadata; update every independent public-contract fixture inventory and reader.
- Preserve source bytes and account for every admitted slide, speaker notes and embedded-resource occurrence without executing linked content.
- Exercise synthetic ordinary/hostile cases, representative licensed-deck trials, API/CLI/configuration parity and actual installed behavior.
- Document actual limitations; leave binary, macro-bearing, template, Strict OOXML and rendered-visual fidelity claims outside initial scope unless separately qualified.

## Acceptance

Executable: focused tests through ./bin/test cover the public conversion boundary, explicit notes policy, reordered identities, hidden/text-free slides, nested groups/tables, repeated assets, hostile package/XML/relationships and unsupported families/content. An independent slide-map validator refuses incomplete or tampered sections, including headings embedded in source text. Required checks end with ./bin/test --changed-from '@{upstream}' against the implementation candidate and one bare ./bin/check all after all tracked close writes, each unchanged during execution. Prove source bytes are unchanged and all existing v1 readers/tests retain their contract. Inspect exact dependency artifacts/licenses/advisories and build package members; exercise fresh installed API/CLI/configuration behavior and a legally usable representative deck, retaining private trial inputs and complete diagnostics. Full suites/builds require a new coordinator window. No provider/credential expansion or hidden partial-success claim is allowed.

User Demo: Using the supplied first-party sample deck, run conversion locally, open its Markdown mirror and confirm there is one section per slide, hidden/text-free slides are explicitly accounted for, presenter notes occur with the applicable slide and are labelled separately, and explicit notes exclusion removes their text and records the policy. Compare the sample's source slide order/content with the mirror. Confirm animation/build steps do not become extra slide sections. This is a native-text review, not a visual-render fidelity judgment. No user demo has run; human acceptance remains open after delivery.

## Brief refs

- [PowerPoint ingestion research](../../briefs/powerpoint-ingestion.md)
- [Existing product design](../../briefs/design.md)
