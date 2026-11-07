---
title: Keep retained state outside the advertised test temporary root
scope: methodology
proposed_surface: bin
source: learn
slug: enlightened-cow
status: candidate
filed: '2026-11-07'
occurrences:
- date: '2026-11-07'
  ref: Receiving qualification attempt 2
---

Allocate distinct owned sibling HOME/state and TMPDIR roots when adapting test isolation. Sharing HOME with TMPDIR fixed native OCR temporary-file handling but correctly made the evidence-durability guard reject HOME/.local/state as temporary. All 28 failures/setup errors in that attempt had this diagnosis. The correction retains the guard and proves both private-temp ownership and separation from HOME. Deliberate witness mutations are evidence for the correction, not additional occurrences.