# Drawbridge

Any file in, one Markdown mirror out. A mirror is a plain-text twin of a document: a YAML provenance header that names the exact bytes it was made from, then the document's text in sections that match the original's own units (pages, sheets, a message). Local fidelity conversion preserves the input and ends in an inspectable mirror, typed failure or truthful deferred stub. Optional audio/model stages require explicit profiles and report their egress. The first public candidate is **0.1.0**, under **MIT**.

| Input | How | Sections |
|---|---|---|
| PDF | native text where the PDF has it, orientation-recovered OCR where it does not | `## Page N` |
| Word (`.docx`) | standard-library walk of the package XML | one document |
| Word 97-2003 (`.doc`) | OLE2 piece-table reader, main story only | one document |
| Excel (`.xlsx`, `.xls`) | cached values, merged ranges noted, one fenced CSV per sheet | `## Sheet: name` |
| Email (`.eml`) | headers table, plain body (or the words of an HTML-only body), attachments listed, not converted | `## Body` |
| Text, JSON, YAML, CSV, HTML source | UTF-8 decode, line endings normalised | one document |
| Images | OCR at four rotations, best kept | `## OCR` |
| Anything else | a deferred stub flagged `mirror-pending` | none |

Types are decided from content, never from the filename: an OOXML package by the parts it carries, an OLE2 file by its streams, an email by its header block. The design rationale for the PDF path is in `briefs/design.md`; the plan for audio, video and model stages is in `plan/`.

## What the PDF path does

1. **Identify by content.** The media type comes from magic bytes (`file(1)` when available, else the `%PDF-` signature), never from the filename. The independently installed Vellric CLI then traverses every page and returns a validated complete inspection. Password-protected and zero-page files stop as `blocked`; malformed or partially readable files stop as `failed`. There is no partial result.
2. **Select pages for OCR, page by page.** A page goes to OCR when it has no extractable text or when raster images cover at least half of it. The second rule catches scans that carry a stale OCR layer. Pages with real text and modest imagery keep their native text exactly.
3. **Recognise selected pages.** Optionally, `ocrmypdf` runs on a disposable copy of the selected pages as a preflight that proves the document is OCR-able and kept its page count; the derivative can be kept as a searchable PDF. Then each selected page is rendered from the original at 300 DPI in all four right-angle rotations, Tesseract reads each, and the rotation with the highest confidence-weighted character score wins.
4. **Assemble and write.** Native and recognised pages are merged in order, the count is checked against the page count, and the mirror is rendered with a header that records the content hash, byte size, method (`pymupdf-text` or `ocr`), and which pages were recognised at which rotation.

No headings, tables, links or columns are reconstructed in the mirror. It is a page-anchored fidelity artifact; the optional `structure` stage derives a semantic rendering beside it and never changes it.

## Quick start

With Python 3.12+ and uv, from the downloaded wheel directory:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python ./drawbridge-0.1.0-py3-none-any.whl
.venv/bin/drawbridge --version
printf 'Plain local evidence.\n' > example.txt
.venv/bin/drawbridge convert example.txt --no-profile --stdout
```

PDF conversion requires independently installed Vellric 0.1.0; configure DRAWBRIDGE_VELLRIC to its trusted executable. Drawbridge runtime contains no PyMuPDF or Vellric import/dependency. Pillow handles images; image OCR needs Tesseract. No sibling checkout is required.

[Installation/platform prerequisites](docs/INSTALLATION.md) · [Worked examples](docs/EXAMPLES.md) · [CLI/API/configuration](docs/USAGE.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [Licensing/boundary](docs/LICENSING.md)

The retained [design brief](briefs/design.md), [profile specification](briefs/profile.md), [plan](plan/README.md) and test estate remain developer references. For a source checkout, `uv sync --locked --group dev` plus the independent Vellric executable prepares `uv run --locked pytest`; actual live OCR prerequisites are required.

## Use

```bash
drawbridge convert scan.pdf                    # writes scan.md beside the input
drawbridge convert ledger.xlsx                 # writes ledger.xlsx.md: a non-PDF keeps its whole name
drawbridge convert scan.pdf -o out/scan.md --json
drawbridge convert scan.pdf --searchable-pdf out/scan-searchable.pdf
drawbridge convert scan.pdf --skip-preflight   # tesseract only, no ocrmypdf
drawbridge convert born-digital.pdf --no-ocr   # refuse rather than OCR scan-like pages
drawbridge inspect scan.pdf                    # JSON: media type, page count, text layer, pages selected for OCR
drawbridge verify scan.md --pdf scan.pdf       # header hash, size, and page-section count match
```

Exit codes: `0` ok, `2` usage, `3` blocked (password-protected or no pages), `4` failed (unreadable or malformed input), `5` operational (OCR tooling unavailable or conversion incomplete), `6` verify mismatch.

## The mirror

```markdown
---
mirror_of: scan.pdf
content_hash: sha256:…
media_type: application/pdf
byte_size: 103856
acquired_at: 2026-09-14T19:02:11Z
acquisition_method: drawbridge-cli
acquired_from: /path/to/scan.pdf
processing:
- seq: 1
  method: ocr
  performed_at: 2026-09-14T19:02:14Z
  agent: drawbridge
verify: []
generated_by: drawbridge
page_count: 1
ocr_pages:
- page: 1
  rotation: 0
  score: 5123.0
---

# Scan

## Page 1

The LinnSequencer
32 Track MIDI Sequence Recorder
…
```

Pages with nothing recoverable are kept and marked `[No text recovered from this page; check the original.]`, so page numbers in the mirror are always page numbers in the PDF.

## The format

Every mirror declares `format: drawbridge.mirror.v1` and a `unit` (`page`, `sheet`, `message`, `turn`, `document`) after the ten required provenance fields. A mirror written before the format was versioned carries neither and still parses as a page mirror.

Anything a caller wants to record goes under `extensions`, one mapping per namespace. drawbridge writes it, preserves it and never reads it, and refuses an extension that is not a mapping, so a caller's fields cannot collide with the format's own:

```python
ConversionOptions(extensions={"my-pipeline": {"document_number": 1204}})
```

`parse_mirror_header` returns `(header, body)` and refuses anything off-contract; `page_sections(body)` returns page texts in order; `sections(body)` returns `(heading, text)` for any unit.

## Profiles: audio, video and grooming

With no profile, nothing networked runs, and an audio or video file is refused. A profile (`--profile PATH`, `$DRAWBRIDGE_PROFILE`, `./drawbridge.yaml`, or `~/.config/drawbridge/profile.yaml`; first match wins) names endpoints once and switches stages on by their presence. `briefs/profile.md` has the full schema. A profile never holds a secret: each endpoint names the environment variable that does, `.env` files in the working directory and beside the profile are loaded without overriding the environment, and key values are never printed. Validation is fail-closed: an unknown key, an undeclared endpoint, an endpoint with no declared `egress`, or a stage widened beyond what it can act on is an error before anything runs.

```bash
drawbridge convert call.m4a --profile p.yaml --dry-run    # the plan: stages, endpoints, what leaves the machine, minutes, estimate; no calls, no writes
drawbridge convert call.m4a --profile p.yaml              # call.m4a.md plus call.m4a.transcribe/ (raw response, adjusted audio, speaker table)
drawbridge convert call.m4a --profile p.yaml --local-only # refused, with the plan it would have run
drawbridge convert scan.pdf --profile p.yaml              # scan.md and, with a structure stage, scan.semantic.md
drawbridge convert scan.pdf --profile p.yaml --no-ai      # exactly the local result
drawbridge speakers call.m4a.md speaker_0="Jane Smith" speaker_3="Jane Smith"
drawbridge profile check --profile p.yaml
```

**Audio and video** go through the [Quillric](https://github.com/wolfmcnally/quillric) distribution (Python import `transcribe`) (install the audio extra as shown below). Only a `transcription` stage is required. Before anything is sent, the recording is measured locally: its length against `limits.max_audio_minutes` (a `RunBudget` caps a whole batch), and its **speech-level spread**, the distance in decibels between its loud and its quiet speech. At or above `transcription.uneven_threshold_db` (default 25) the recording is *uneven*, and two things follow:

Audio conversion passes each required profile credential directly to Quillric's
per-call API (requires distribution `quillric>=0.1.0`). It does not overwrite
`AUPHONIC_API_KEY` or `ELEVENLABS_API_KEY` in the process environment. An injected
`run` callable used for offline conversion tests accepts the same keyword
arguments: `elevenlabs_api_key` and, only when leveling is selected,
`auphonic_api_key`.

Quillric 0.1.0 is absent from PyPI at preparation. Its exact locked Git commit is publicly reachable. From the directory containing the Drawbridge wheel, install the source dependency first, then the audio extra:

```bash
uv venv --python 3.12 .venv-audio
uv pip install --python .venv-audio/bin/python 'quillric @ git+https://github.com/wolfmcnally/quillric.git@c48b76e522f4e677df9184a2e82469ddcdb9cee9'
uv pip install --python .venv-audio/bin/python './drawbridge-0.1.0-py3-none-any.whl[audio]'
.venv-audio/bin/drawbridge --version
```

This route requires Git and network access to the public source and dependency index. Audio/video processing additionally needs ffmpeg and the selected provider credentials. Installation and CLI startup make no provider calls.

For locked development, `uv sync --locked --all-extras` uses the exact Quillric Git commit in this repository's lock. Do not coinstall an old distribution named `transcribe`; rebuild ambiguous environments because the two distributions share the Python import and CLI.


- **Leveling is opt-in.** Without an `audio_cleanup` stage the audio is never leveled and the second provider is never contacted. With one, `mode: auto` (the default) levels only uneven recordings and `mode: on` levels all of them. The plan and `--dry-run` show exactly the hops this recording will make, and only the keys those hops need are required. The default is off because a paired test found no gain in recognised words, quiet-stretch words, speakers or attribution from leveling, while the same unleveled audio transcribed twice agreed with itself only 95 to 97% on hard recordings; [Quillric's README](https://github.com/wolfmcnally/quillric) has the numbers.
- **An uneven recording is transcribed twice** (`transcription.second_pass: auto`; `on` and `off` force it), and **one mirror is made from both passes with their disagreements kept in the flow**. Where the passes heard different words, both readings sit inline as `{first | second}`, with `—` where a pass heard nothing: `through a {POST | police} academy`. Where they gave the same words to different speakers, that stretch is its own turn section headed with both identities, `speaker_1 or speaker_3`. Neither pass is treated as right, and each side reads back as its own pass word for word. The mirror is flagged `transcript-word-disagreements:N` and `transcript-speaker-disagreements:N`, records `second_pass_agreement`, and the second response is kept in the package. The estimate counts both passes.

The mirror has `unit: turn`, the recording's SHA-256 as its `content_hash`, the measured `speech_level_spread_db`, whether leveling was applied, a **Speakers** table with one row per identity the provider emitted and a name column that starts empty, and one section per speaker turn. The same name may be given to several identities, because providers split one voice into several. `drawbridge speakers` edits the package's table and renders the body again; a named turn reads `Jane Smith (speaker_3)`, and no word changes. A package already present for the same bytes is reused, not paid for again. Video contributes its audio track only and the mirror is flagged `video-visual-content-not-captured`.

**Transcript refinement** is the `transcript_refinement` stage, for audio and video. It writes `<name>.semantic.md` beside the transcript mirror. The model sees the turns with provider identities only, never assigned names, and returns numbers and identities, not prose. Code applies the one safe thing, paragraph breaks between sentences of long turns, and proves each turn's words unchanged. Everything else is a proposal in a `## Proposals` table with the time to listen at, none applied: two identities that may be one voice, a few words at a turn's edge that may belong to the neighbouring speaker, a word that may be misspelled (the suggestion must resemble the word it replaces). Code writes every sentence a reader sees, so a proposal has nowhere to carry a name. A two-pass disagreement, `{first | second}`, is one unit that is never split, judged or resolved. `speaker_resolution: off` drops the one-voice proposals.

**As a library**, `convert_file(path, profile=…)` returns the fidelity mirror and, in `semantic`, the groomed rendering when the plan ran a grooming stage; `plan_report` says what a conversion would run, send and cost without sending anything; `load_profile`, `parse_profile`, `build_plan` and `RunBudget` (safe to share across threads) are exported from the package root. `ProfileError` belongs to the package's error family. A semantic mirror names its source twice: `derived_from` is the hash of the whole fidelity mirror, and `derived_from_body` the hash of its body alone, which still matches after a consumer regenerates the header.

**Image description** is the `image_description` stage, for image files. It is the one stage where a model writes prose, so the prose is fenced: it goes in its own `## Description` section, the header names the model and endpoint, and `description-model-written` stays in `verify`. The recognised text in `## OCR` is never touched. The image is sent as a JPEG no larger than 1,568 pixels on its long edge; the answer is reduced to plain paragraphs, capped at `max_words`, and cached. If the endpoint gives nothing usable the mirror is still written, flagged `description-pending`.

**Grooming** is the `structure` stage. Born-digital PDF pages are groomed from the PDF's own typography with no model and no endpoint (`stages: {structure: {}}` is enough, and `--no-ai` keeps this pass): font flags give bold, italic and monospace, the sizes that stand above the body size give up to three heading levels, link rectangles give link targets, detected tables become tables, wrapped lines become paragraphs and bullet glyphs become list items. A page set mostly in large type gets no headings. Scanned pages go to the model, and a born-digital page goes to it only under `native_pass: none` with `pdf-native-page` in `applies_to`. The stage writes `<name>.semantic.md`, derived from the fidelity mirror (`derived_from` carries its hash) with the same sections, so page anchors still resolve. The model never writes words: it is shown numbered lines and returns annotations only (heading, paragraph, list, list item, quote, keep), and code applies them. A gate then requires the groomed section's word sequence to equal the fidelity section's, for both passes (the typography pass may offer a rendering with tables and one without, and the first whose words match is used); a section that fails keeps its fidelity text and is listed in `verify` as `structure-fallback:<section>`. Results are cached under `limits.cache_dir` by content hash, stage, model and prompt. Endpoints may declare `cost_per_audio_hour_usd`; the estimate uses only declared rates and says so when one is missing.

## Library use

```python
from drawbridge import CliOcrBackend, ConversionOptions, convert_file, extract_text, render_mirror

result = convert_file("ledger.xlsx", ocr=CliOcrBackend(), options=ConversionOptions(title="Ledger"))
print(result.media_type, result.method, result.mirror.header["verify"])
open("ledger.xlsx.md", "w").write(render_mirror(result.mirror))

extract_text("ledger.xlsx")   # the deterministic text alone, to re-check a stored mirror body
```

`convert_file` sniffs the type (or takes `media_type=`), dispatches, and returns a `FileConversion`; for a PDF its `.pdf` carries the page-level result. `convert_pdf` remains for callers that only handle PDFs:

```python
from drawbridge import CliOcrBackend, convert_pdf, render_mirror

result = convert_pdf("scan.pdf", ocr=CliOcrBackend(preflight=False))
print(result.method, result.selected_pages)
open("scan.md", "w").write(render_mirror(result.mirror))
```

Every document-local problem raises a `DrawbridgeError` subclass. `blocked_reason(exc)` returns `"password-protected"` or `"degenerate-input"` for inputs no retry can fix, and `None` otherwise. Batch callers can treat the first as terminal and the rest as retryable.

Concurrency: construct one `OcrCapacity(cores)` and pass it to every `CliOcrBackend(document_workers=W, capacity=...)` you run in parallel. Each complete PDF job reserves and forwards `max(1, cores // min(W, cores))` tokens, and every subprocess runs with `OMP_THREAD_LIMIT=1`, so total recognition threads never exceed the machine.

### Reporting paid calls

Every call a conversion makes to a paid model or service is reported to a recorder you supply, so cost can be accounted per call:

```python
from drawbridge.calls import record_calls

calls = []
with record_calls(calls.append):
    convert_file("recording.m4a", profile=profile)
```

Each report is a `ModelCall`: the profile stage, endpoint and model; the outcome (`succeeded`, `failed`, or `reused` when a kept transcription stood in and nothing was charged); the duration; and, for model calls, the prompt and completion tokens and the cost the provider reported. OpenRouter endpoints are asked to include that cost. Audio calls carry the recording's length and the rate the profile declares, from which their cost follows. Calls made on threads the conversion starts itself are reported too; answers served from a cache are not, since no call was made.

### Reporting progress

A step that works through a document unit by unit reports how far it has got to a listener you supply, so a caller running many conversions can say which document is at which step:

```python
from drawbridge import report_progress

with report_progress(lambda step, done, total: print(step, done, total)):
    convert_file("scan.pdf", ocr=CliOcrBackend(), profile=profile)
```

The steps are `recognition` (pages recognised of those selected), `structure` (sections structured of the document's sections), `refinement` (transcript windows reviewed) and `transcription` (the recording's seconds, reported when it starts and when its package is ready: the transcription dependency works on the recording as a whole). Each reports zero done when it starts. Reports reach the listener from the conversion's own thread; a listener that raises is ignored, and reporting never changes a mirror. A kept transcription reports nothing.

## Fixtures

`tests/fixtures/` holds public PDFs chosen to cover the cases that matter; see `tests/fixtures/MANIFEST.md` for sources, hashes and licenses. Encrypted, zero-page, mixed native/scan and small-logo documents are generated synthetically in the tests, and so is every office fixture: `tests/office_fixtures.py` assembles OOXML packages, OLE2 compound files, BIFF8 workbooks and Word 97 structures from literals, including malformed and encrypted ones.

## License

MIT. Copyright Wolf McNally.

### Vellric admission and resource settings

PDF helpers require an independently installed `vellric` on PATH, or an absolute trusted executable in `DRAWBRIDGE_VELLRIC`. Development setup is `uv sync --locked --group dev` plus that executable; PDF tests deliberately fail if it is missing. PyMuPDF is present only in the development group for fixtures and existing external-object lock proofs. The installed Drawbridge runtime does not import or install PyMuPDF, fitz, or Vellric.

`CliOcrBackend` accepts `memory_mib`, `document_timeout`, `max_input_bytes`, `max_pages`, and `tessdata_dir`. Its default memory allowance is 2048 MiB plus 512 MiB per additional granted OCR worker. The deadline is at least 3600 seconds and, when page count is known, covers configured preflight plus four rotations per selected page, divided by the worker grant. These are admission defaults, not measured production capacity. Set explicit limits for large workloads. Native inspection also accepts trusted environment settings `DRAWBRIDGE_VELLRIC_MEMORY_MIB`, `DRAWBRIDGE_VELLRIC_TIMEOUT_SECONDS`, `DRAWBRIDGE_VELLRIC_MAX_INPUT_BYTES`, and `DRAWBRIDGE_VELLRIC_MAX_PAGES`. Each must be positive and finite; byte/page limits must be integers. `DRAWBRIDGE_VELLRIC_TESSDATA_DIR` or `TESSDATA_PREFIX` is forwarded explicitly to Vellric. The child environment is scrubbed.

A caller-selected OCR subset is accepted by `extract`; complete conversion still refuses outstanding candidates. `recover_page(pdf, n)` recognizes only page n. Blocked encrypted PDF inspection can carry partial metadata without claiming a complete artifact. A later typography job is bound to the fidelity mirror's original source hash. The `pdf_processor` header records Vellric processing identity separately from the original content hash; changed processing identity requires cache invalidation.

Pillow handles its supported raster formats, bounded to 256 MiB decoded pixel storage. Oversize or unsupported images, including SVG without a raster decoder, retain the existing `ocr-pending` mirror fallback. Image OCR uses automatic column/block segmentation; only horizontal word boxes contribute to orientation choice. Coordinate helpers use clockwise rotation and the inherited 96-DPI default when metadata is absent. PDF rendering accepts PNG, PNM/PPM and JPEG, validates DPI/right-angle rotation, and renders the displayed page frame.

Vellric supervises its worker and recognizers, but this process boundary is not a hostile-document sandbox. Forced supervisor termination after its cleanup grace period remains a deployment concern. Host/container resource limits and production workload sizing must be qualified before a live deployment.

### Prepared local release build

The local candidate is Drawbridge 0.1.0. Build with `SOURCE_DATE_EPOCH=1609459200 uv build . --python 3.12 --build-constraints build-constraints.txt`. Its source includes uv.lock, exact build constraints and NOTICE, including separate public fixture grants. Publish this candidate only after the tested Vellric 0.1.0 commit/artifacts are publicly reachable. Live consumer upgrades remain separately authorized.

Optional audio installation uses the publicly reachable pinned Quillric source shown above; Quillric 0.1.0 is absent from PyPI at preparation. The core quickstart and PDF boundary do not require it. See [the installation guide](docs/INSTALLATION.md).
