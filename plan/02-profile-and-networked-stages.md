# Phase 2: Profile and networked stages

Status: done (2026-09-18). Done and tested: profile, guards, audio and video through `transcribe` (one live conversion, names re-rendered, package reuse), and the structure stage in annotate mode with its preservation gate and cache (one live grooming of a public scanned page, words identical). Also done: leveling is opt-in and decided per recording from a local measurement of speech-level spread, and an uneven recording is transcribed twice with the differences carried into the mirror inline (one live conversion). Also done: the structure stage's deterministic pass for born-digital pages, which needs no endpoint and survives `--no-ai` (surveyed on 150 real born-digital PDFs: no crash, 98.4% of 1,336 pages groomed with words proven unchanged). Also done: image description, fenced in its own section and flagged as model-written (one live description of a public chart). Also done: transcript refinement, which paragraphs long turns and lists proposals without applying any (one live run on a two-pass transcript: every turn's words and every inline disagreement identical, one one-voice proposal).

## Outcome

Audio and video files convert to mirrors through the `transcribe` dependency, and the optional model stages turn fidelity mirrors into cleaned, groomed, easily chunkable Markdown. Every stage that sends bytes off the machine or spends money runs only under a profile that names it, within limits, with a plan the user can inspect first.

## Why this is one phase

Every stage here needs the same things before its first call: endpoints declared once, keys read from the environment, an egress rule, a dry-run plan, limits, a cache keyed by content hash, and a provenance entry per stage. Building that apparatus for audio alone and again for grooming would be the same work twice. The stages are small once it exists.

## Work

1. **Profile.** Loading, fail-closed schema validation, `.env` handling, `--dry-run`, `--no-ai`, `--local-only`, `--stages`, `--skip`, `profile show`, `profile check`, as `briefs/profile.md` specifies.
2. **Guards.** Limits on pages and audio minutes per document and per run, refused before any call; a running cost estimate in the plan; the cache; a `processing` entry for each stage with its endpoint and egress.
3. **Audio and video.** A `transcription` stage that calls `transcribe` as a library and builds the mirror from its package: `unit: turn`, the source recording's SHA-256 as `content_hash`, a **Speakers** table carried from the package's speaker table (one row per provider identity, a name column that starts empty, the same name allowed on several rows), and one section per speaker turn that keeps the provider identity visible beside any name. Names change by re-rendering from the package, never by editing words. Video contributes its audio track only, and the mirror says so. The raw provider response, the adjusted audio and the package sidecar are retained beside the mirror. `briefs/profile.md`'s instruction to port `transcribe`'s provider code is superseded.
4. **Structure.** The grooming stage: a deterministic native pass, then `mode: annotate` through an OpenAI-compatible adapter, writing `<name>.semantic.md` with `derived_from` pointing at the fidelity mirror's hash and the same sections, so anchors still resolve. A strict word-preservation gate: a groomed section whose words differ from the fidelity text falls back to it and is listed in `verify`.
5. **Image description** and **transcript refinement**, both annotate-only. Refinement proposes speaker merges, boundary moves and paragraphing tied to time ranges; it never asserts an identity.

## Out of scope

Model-based OCR (`ocr: engine: vlm`) unless a measured need appears; per-call cost accounting beyond the estimate; any review interface.

## Acceptance

- With no profile, behaviour is exactly phase 1's.
- `--dry-run` on an audio file lists the cloud stages, the minutes, and the estimate, and makes no call.
- `--local-only` refuses an audio file with a plan showing what it would have run.
- One live audio conversion produces a mirror with a Speakers table; assigning one name to two identities in the package and re-rendering shows in the mirror, with the word content unchanged.
- The preservation gate is proved by a test in which a model response alters a word and the section falls back.
