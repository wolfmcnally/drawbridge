# Phase 1: Every file type, one mirror contract

Status: implemented 2026-09-18; acceptance met (124 tests including live OCR; 2,361 of 2,373 real office, text and email files reproduce a prior pipeline's stored mirror body exactly, and the 12 that differ are deliberate email improvements).

## Outcome

`drawbridge convert FILE` produces a mirror for every non-audio file type, locally and deterministically, under a versioned mirror format that has a fixed core and an extension area. A consuming pipeline can delete its own document converters and call drawbridge as a library.

## Why this is one phase

The converters share one header, one dispatch, one failure taxonomy and one fixture estate. Splitting by file type would produce several phases that each re-open the same format and the same dispatch. The format change cannot be separated from the converters either: the format only needs versioning and an extension area because it stops being PDF-only.

## Work

1. **Mirror format v1.** The header keeps today's ten required fields and gains `format: drawbridge.mirror.v1` and `unit` (what the body's sections are: `page`, `sheet`, `message`, `document`). Anything else lives under one `extensions` mapping, keyed by the namespace of whoever added it; drawbridge preserves it, never interprets it, and refuses a colliding top-level key. `parse_mirror_header`, `page_sections` and a new general `sections` stay public API, because clients parse mirrors without converting.
2. **Identification for every type.** Content-sniffed media types for Word (OOXML and the 97 binary format), Excel (OOXML and binary), email, images, text, JSON and YAML, with OOXML package classification done here, not borrowed from a client's storage library. Names remain claims; bytes are the authority.
3. **Converters moved in.** Word OOXML (standard library XML walk), Word 97 (OLE2 piece-table walker), Excel OOXML (data-only values with merged ranges), Excel binary, email, text-like files, images (local OCR only in this phase), and the deferred-stub fallback for anything unsupported, which says so in `verify` rather than pretending. Each takes a plain title string; nothing of a client's triage, storage, numbering or ledger comes with it.
4. **One dispatch.** A registry keyed by media type behind `convert_file(path, *, title=None, ...) -> Mirror`, with the existing PDF path as one member. The CLI's `convert` accepts any supported file. Blocked and failed outcomes keep today's taxonomy and exit codes; each new failure mode is classified before it ships.
5. **Deterministic extraction API.** A public `extract_text(path)` for the office types, so a client's fidelity check can re-extract and compare against a stored mirror body.
6. **Tests.** The moved converters arrive with no live tests, so this phase writes them: runtime-synthesized fixtures for every type including malformed and encrypted inputs, golden bodies for spreadsheets and Word, input-bytes-unchanged assertions, and a round trip of every mirror through the parser.

## Out of scope

Audio and video, any model call, image description, structure recovery, unpacking archives, splitting combined files, deciding what is admitted. The last three belong to the client.

## Acceptance

- Every supported type converts from the CLI and from the library; an unsupported type yields a deferred stub that says why.
- The suite passes offline with no keys set, and no test touches the network.
- A mirror written by the current PDF-only release still parses.
- The README documents the format, the extension area, and the library entry points.
