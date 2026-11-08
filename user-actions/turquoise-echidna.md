---
slug: turquoise-echidna
title: Review ordinary PowerPoint slide ingestion sample
status: pending
category: product-review
urgency: low
blocks: []
filed: '2026-11-07'
needed_at: after source delivery
source: kickoff
refs:
- plan/phases/powerpoint-slide-ingestion.md
---

Run the supplied first-party sample protocol from the phase report. Compare the source deck and generated Markdown for one section per slide, canonical order, explicit hidden/text-free accounting, grouped/table text and associated labelled notes. Compare explicit note exclusion and verify that animation builds do not create extra slide sections. Judge readability and suitability; automated extraction checks cannot establish those judgments. This remains open for the operator and does not block the qualified source delivery or the already-authorized release. No visual-render fidelity claim is made.

The qualified [Drawbridge 0.3.0 release](https://github.com/wolfmcnally/drawbridge/releases/tag/v0.3.0) is now published. Download the explicitly named wheel and matching source archive, keep them together, and follow `docs/INSTALLATION.md` and `docs/POWERPOINT.md` inside that source archive. After entering the extracted source directory, use the explicit parent-directory path to the downloaded wheel. Publication and automated checks do not complete this pending human review.
