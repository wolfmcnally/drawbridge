---
{"at": "2026-11-14T23:38:09+00:00", "body_sha256": "8b413921b87dd3afc3367b2d9f60cc29636d3cce7728e1026638fe3b4a4d0930", "id": "51aaea4d3ae9498aa06ebcd5fc5478fb", "previous": "93c22f3c7cba4eb3be8766630dda6761", "sequence": 39, "writer": "drawbridge-maintainer"}
---
## 2026-11-14 — METHODOLOGY SCOPE — teach Starter 1.7.0

Written after the approved bytes and the proof admission had been applied to the checkout, not before them; see the departure recorded in the terminal entry. Authorized outcome: the Starter hub, acting as the operator's coordinator, approved this recipient's plan on 2026-11-14 exactly as sent, for a single maintenance transfer of Starter 1.7.0, with conditions: recheck that the checkout is clean and equal to origin/master before writing, keep the root product profile, run admission once in the real checkout, and qualify delivery by one changed-path selection and one bare full gate on the final tree.

Source: agentic-coding-starter at tag v1.7.0, revision 37edf41ea22ce383a81102ab7819c1b998cae5f1; previous recorded baseline Starter 1.6.0. Donor preflight: route maintenance, `releases_not_recorded: ["1.7.0"]`.

Surfaces in scope:
- Take as released (byte-identical to v1.6.0 before): `bin/multioperator`, `lib/agentic_starter/multioperator.py`, `lib/agentic_starter/multioperator_transition.py`, `policies/build-gates.md`, `policies/test-suite-governance.md`, `tests/test_multioperator.py`; new `lib/agentic_starter/native_suite.py`.
- Merge Starter's v1.6.0 to v1.7.0 change onto this repository's copy, keeping every recipient line and the root product profile: `.claude/skills/teach/SKILL.md`, `bin/README.md`, `bin/test`, `lib/agentic_starter/test_governance.py`, `policies/software-documentation.md`, `tests/proof-plants.json`, `tests/test_kickoff_config.py`, `tests/test_test_governance.py`, `tests/test_toolchain_entrypoints.py`.
- One `./bin/test-governance admit` input for five arriving proofs and one corrected proof; its rows in `reports/test-governance/drawbridge-decisions.jsonl` and `drawbridge-witnesses.jsonl`.
- `collaboration/methodology-provenance.json` to release 1.7.0 and the terminal log entry.

Exclusions: product code and product tests, `AGENTS.md`, `README.md`, `manual/`, `docs/`, `pyproject.toml`, `uv.lock`, `kickoff.yaml`, `plan/**`, lessons and user-action content, hooks installation, settings, tags and releases; Starter's `tests/test_methodology_toolchain_contract.py` change and its recorded defect (that test is absent here), Starter's release notes, briefs, lessons, log entries and proof ledgers.

Independent review: not applicable — primary one-shot methodology work.
