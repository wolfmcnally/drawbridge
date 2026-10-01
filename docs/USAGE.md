# CLI, API and configuration

`drawbridge --help` and subcommand help define the public options. The main commands are convert, inspect, verify, profile and speakers. Conversion emits a provenance header plus unit-anchored fidelity text; source bytes are never rewritten. A separately requested structure stage derives another mirror and preserves the strict word gate.

```bash
.venv/bin/drawbridge convert example.txt --no-profile --stdout
.venv/bin/drawbridge convert input.pdf --no-profile -o input.md
.venv/bin/drawbridge inspect input.pdf
.venv/bin/drawbridge verify input.md --pdf input.pdf
```

Local explicit API:

```python
from drawbridge import CliOcrBackend, convert_file, render_mirror
result = convert_file("input.pdf", ocr=CliOcrBackend(preflight=False))
print(render_mirror(result.mirror))
```

CliOcrBackend accepts CPU capacity, worker count, language/DPI, preflight/page timeouts, tessdata_dir and document input/page/memory/deadline limits. DRAWBRIDGE_VELLRIC selects a trusted absolute executable; resource/data environment settings are listed in the README's admission section. A complete Vellric artifact is independently checked for source identity, page sequence, hashes and recognition completeness. Selected extract/recover_page APIs retain caller scope; complete conversion refuses unresolved OCR candidates.

The profile format and endpoint/egress/strict preservation controls are documented in [the retained profile design](../briefs/profile.md). Use `--no-profile` for local deterministic examples. `--dry-run` reports resolved work without calls/writes; `--no-ai` skips endpoint stages and `--local-only` refuses cloud egress. Audio/model stages require explicit configuration; credentials pass only to the stage that needs them. Paid-call/progress recorder APIs and concurrency are in the README.

Keep package version, source content hash and processing identity distinct. First public Drawbridge is 0.1.0; private 0.4.x history remains. The inherited Vellric behavior label names the qualified extraction baseline, not the current distribution version. Clear affected consumer caches when migrating processors. See [boundary/license notes](LICENSING.md).


## Native media identities and range derivatives

`drawbridge.pdf_tools.page_fingerprints(path)` returns tuples of exact RGB page hashes and native difference hashes, including forms and annotations. `materialize_pdf_range(parent, destination, start, end)` copies a validated deterministic inclusive range artifact. `canonical_image(path, width=None, height=None)` returns ordinary RGB bytes, dimensions and native hashes after validating the standalone image bundle. These complete jobs require independently installed Vellric; Drawbridge never imports the engine. Difference hashes are similarity proposals, not duplicate verdicts. Canonical comparison never upsamples or introduces a pixel-error tolerance.

The adapter caches CLI compatibility diagnosis for the process lifetime, keyed by executable path/inode/size/modification time. An independently reinstalled CLI invalidates the probe. Every complete job still validates its manifest, source and artifact hashes and checks its own engine/resource availability. Diagnosis has a separate 90-second budget and reports unavailable capabilities distinctly from a document failure. Tessdata forwarding applies to conversion jobs; stale ambient OCR settings do not affect native inspection or images. DRAWBRIDGE_VELLRIC_MAX_OUTPUT_BYTES can lower the job output budget; the adapter also enforces its independent 2 GiB artifact cap. PDF range jobs currently produce temporary 72-DPI render artifacts in addition to the subset PDF. Whole-document fingerprint jobs emit lossless 144-DPI rasters, so large documents must fit the configured output budget.
