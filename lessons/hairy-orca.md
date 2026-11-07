---
title: Freeze the selected interpreter before isolating test HOME
scope: methodology
proposed_surface: bin
source: learn
slug: hairy-orca
status: candidate
filed: '2026-11-07'
occurrences:
- date: '2026-11-07'
  ref: Receiving runtime adaptation before qualification
---

Bind the already selected base interpreter before changing a test process HOME. A real nested uv invocation reselected a temporary managed interpreter and replaced the repository venv; argv-only stubs did not expose the effect. The receiving wrapper now freezes the base interpreter and its real nested proof checks that the venv remains bound. This is an application finding about the methodology runtime adapter, not a proposal to change product runtime requirements.