# CLI, API and configuration

`drawbridge --help` and subcommand help define the public options. The main commands are convert, inspect, verify, profile, speakers and doctor. Conversion emits a provenance header plus unit-anchored fidelity text; source bytes are never rewritten. A separately requested structure stage derives another mirror and preserves the strict word gate.

PDF mirrors targeting Vellric 0.2.4 carry validated original-digest/physical-page anchors and a separate page map. Use `page_sections(body, header=header)` for metadata-aware slices, including text with fake Markdown markers. See [physical page citations and safe downstream rendering](PAGE-CITATIONS.md). Combined Markdown is untrusted presentation; preserving anchor bytes does not qualify an HTML viewer or sanitizer.

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

The profile format and endpoint/egress/strict preservation controls are documented in [the retained profile design](../briefs/profile.md). Use `--no-profile` for local deterministic examples. `--dry-run` reports resolved work without calls/writes; `--no-ai` skips endpoint stages and `--local-only` refuses cloud and brokered egress. Audio/model stages require explicit configuration; credentials pass only to the stage that needs them. Paid-call/progress recorder APIs and concurrency are in the README.

## Explicit composed configuration

Repeat `convert --config FILE` to compose YAML layers in order with Conric. Included relative files apply before the containing file; later layers override earlier values. `--config-root DIRECTORY` explicitly confines all files and includes; without it Conric uses the first file's directory. A root requires at least one configuration file. Explicit configuration conflicts with `--profile` and `--no-profile` and bypasses ambient profile and dotenv discovery.

```bash
.venv/bin/drawbridge convert input.pdf --config base.yaml --config local.yaml --config-root . --local-only --no-ai --dry-run
```

Drawbridge validates its optional `drawbridge` subtree. Network endpoints claiming local egress require an explicit HTTP(S) loopback URL, and applicable model stages require an explicit model. Other leaf schemas remain opaque to Drawbridge. The independently installed PDF CLI validates its own top-level `vellric` subtree for configured PDF jobs. A minimal deterministic PDF configuration is:

```yaml
drawbridge: {}
vellric: {}
```

Original absolute file paths, their order and the explicit root are forwarded to Vellric conversion only. Drawbridge preserves symlink spellings; Conric and Vellric own confinement and resolution. No merged replacement file is written. Before forwarding configuration, doctor must report a stable numeric Vellric version of at least 0.2.2 as well as the supported schema/behavior. With explicit files, `--local-only` also reaches Vellric's policy for every provider route; `--no-ai` explicitly selects Vellric's `--vision-provider none` and takes precedence over its configured provider. Without files these flags continue to restrict Drawbridge's own stages and add no new Vellric arguments. Native PDFs execute a complete conversion with OCR and preflight disabled so the CLI can validate its leaf. They reserve the supplied `CliOcrBackend` CPU capacity and use its jobs/memory/resource limits; without that backend the native job uses one CPU token and a default 2048 MiB memory limit, subject to explicit Vellric limit environment settings. Native page text must still equal the admitted text, and outstanding OCR candidates are refused. Scanned PDFs use the existing single complete OCR job. Explicit configured OCR requires `CliOcrBackend`; custom backends remain available without explicit configuration.

Dry-run reports that Vellric leaf validation and provider routes are unevaluated. Configured provider routes may execute unless the report identifies a forwarded `--local-only` or `--vision-provider none` restriction; the Drawbridge stage egress list alone does not describe Vellric's opaque leaf. Dry-run cannot promise that an independently installed CLI will accept the configuration. Vellric configuration references remain unresolved in Drawbridge, and reports omit opaque leaf data. The fixed Vellric subprocess environment does not carry provider credentials. Configuration forwarding therefore does not enable keyed-provider execution: missing references fail closed in Vellric. Drawbridge's own endpoint stages retain their existing credential behavior, with local-only policy refusal occurring before key-presence checks.

The scoped library API uses the same selection without ambient discovery:

```python
from drawbridge import CliOcrBackend, convert_file
from drawbridge.configuration import configuration_context, load_configuration

settings = load_configuration(["base.yaml", "local.yaml"], root=".", local_only=True, no_ai=True)
with configuration_context(settings):
    result = convert_file("input.pdf", ocr=CliOcrBackend(preflight=False))
```

`convert_file` uses the scoped profile by default and intersects scoped policy with each supplied stage's run/model restrictions; an explicit caller profile still selects Drawbridge's own stages. A profile-only `Configuration(profile=profile)` scope is also supported without configuration files or policy flags. Settings are immutable and reset after nested contexts or exceptions. Serialization produces detached ordinary containers without weakening stored immutability. Async tasks inherit their current context and remain isolated when setting their own; new threads do not inherit it automatically. Pass the settings explicitly and open a context in a new thread, or deliberately propagate a copied context. Direct `convert_pdf` performs the fidelity conversion and forwards scoped Vellric settings; Drawbridge's optional stages belong to `convert_file`.

Keep package version, source content hash and processing identity distinct. First public Drawbridge is 0.1.0; private 0.4.x history remains. The inherited Vellric behavior label names the qualified extraction baseline, not the current distribution version. Clear affected consumer caches when migrating processors. See [boundary/license notes](LICENSING.md).


## Runtime settings in unreleased source

`drawbridge.vellric` selects the installed executable and tessdata and accepts positive `limits.timeout_seconds`, `limits.memory_mib`, `limits.max_input_bytes`, `limits.max_output_bytes` and `limits.max_pages`. Use an absolute `drawbridge.identify.file_executable` to select libmagic's executable. `drawbridge.paths.path` is an ordered list of absolute search directories for child tools. Set `paths.work_dir`, `paths.output_dir` and `paths.cache_dir` to contain temporary files, outputs and cached responses. Directory values may be absolute or relative to the configuration root or first file's directory. Vellric and PPTX keep their established child search paths until a path list is supplied. In explicit mode, discovery of Vellric, file identification, image OCR and audio probing uses the system search path when no list is supplied. To find Vellric in a virtual environment or another installation directory, set `drawbridge.vellric.executable` or list that directory under `drawbridge.paths.path`. Standalone discovery still uses the invoking shell's PATH. An omitted cache directory uses the configured work directory's cache. With neither directory supplied, explicit mode now disables disk caching instead of using the previous home-relative default. This change applies to explicit configuration files. The standalone profile cache retains its prior default. Explicit mode uses `paths.work_dir` for scratch and child home directories. When omitted on POSIX, explicit mode uses `/tmp` and bypasses the ambient `TMPDIR`. It also bypasses home expansion and dotenv.

`drawbridge.convert` accepts the conversion flags by their underscore-separated names, including provenance fields, `out`, `stdout`, `artifacts_dir`, OCR and preflight options, stage filters and `notes`. Explicit CLI values override defaults from the file, and policy flags can further restrict the run. Without a config file, standalone flags, profiles and environment settings keep their existing roles. An explicit Vellric selection or limit takes precedence over its corresponding standalone environment setting. Inspect also accepts `drawbridge.inspect.page_texts`, and speakers accepts `drawbridge.speakers.package` and `clear`. Positional input files and speaker assignments stay on the command line.

### Bedrock Converse

An endpoint with `kind: bedrock-converse` requires an exact region and an explicit transport. Select an exact foundation-model ID in each of `structure`, `image_description`, and `transcript_refinement` that uses it. Inference profiles and ARNs are refused. The limits mapping supports `timeout_seconds`, `max_concurrency`, `max_output_tokens`, `max_image_bytes` and `max_image_side_px`. The image defaults and ceilings are 3,932,160 bytes and 8,000 pixels on either side. The defaults for the other limits are 120 seconds, four concurrent requests per loaded endpoint and 1,024 output tokens.

Cloud routes use `transport: bearer` with a named `api_key_env`, optionally written as `!env VARIABLE` in Conric, or `transport: sigv4` with the optional `bedrock` extra. Standalone SigV4 uses the standard AWS credential chain. Explicit Conric mode uses only AWS environment credentials for SigV4, avoiding ambient files and credential discovery processes. Drawbridge resolves secret values at use time and omits them from diagnostics.

A broker route uses `transport: command` plus `command.argv` with an absolute executable and fixed arguments. `command.pass_env` contains the names of any explicitly forwarded environment variables. In explicit mode the configured child `PATH`, work-local home, temp and XDG directories, locale and runtime safety settings take precedence over named ambient values. `command.pass_fds` optionally contains up to four caller-owned descriptor numbers from 3 through 255. Each must already be open in Drawbridge when the stage runs. A listed descriptor reaches the helper with its original number, so the helper's fixed arguments can name its channel. Set `allow_brokered: true` in the Drawbridge section or standalone profile to permit the route. The helper reads one UTF-8 `bedrock-converse-request/1` JSON document on stdin and returns one `bedrock-converse-response/1` JSON document on stdout. Successful replies carry the Converse body. Error replies carry a category of `throttled`, `refused`, `unavailable`, `invalid` or `limit`. Drawbridge enforces the helper deadline and a 16 MiB stdout limit. A failed command leaves the stage pending or uses its existing fidelity path. Transport selection is fixed for the endpoint. The bare `command` endpoint kind is refused.

### Bounded raster work

Set `convert.ocr_page_workers` or `--ocr-page-workers` to cap OCR pages in flight per PDF. The default is one, independent of the machine's apparent CPU count. The existing document worker and CPU grant may reduce it further. Vellric processes the complete PDF with that window and handles rotations sequentially. Standalone image OCR writes and removes one PNM rotation or band at a time. Complete-job input, output and page defaults remain 512 MiB, 2 GiB and 10,000 pages. Configure finite overrides under `drawbridge.vellric.limits`. Drawbridge independently checks the configured output and page budgets and reads at most 64 MiB of manifest data. These are per-operation guards for the current complete-job reader. A guard refusal leaves the input intact and reports the operation limit. The complete PDF result and retained searchable derivative can grow with the document, and Vellric snapshots the original for source custody.

## Native media identities and range derivatives

`drawbridge.pdf_tools.page_fingerprints(path)` returns tuples of exact RGB page hashes and native difference hashes, including forms and annotations. `materialize_pdf_range(parent, destination, start, end)` copies a validated deterministic inclusive range artifact. `canonical_image(path, width=None, height=None)` returns ordinary RGB bytes, dimensions and native hashes after validating the standalone image bundle. These complete jobs require independently installed Vellric; Drawbridge never imports the engine. Difference hashes are similarity proposals, not duplicate verdicts. Canonical comparison never upsamples or introduces a pixel-error tolerance.

The adapter caches CLI compatibility diagnosis for the process lifetime, keyed by executable path/inode/size/modification time. An independently reinstalled CLI invalidates the probe. Every complete job still validates its manifest, source and artifact hashes and checks its own engine/resource availability. Diagnosis has a separate 90-second budget and reports unavailable capabilities distinctly from a document failure. Tessdata forwarding applies to conversion jobs; stale ambient OCR settings do not affect native inspection or images. DRAWBRIDGE_VELLRIC_MAX_OUTPUT_BYTES can lower the job output budget. PDF range jobs currently produce temporary 72-DPI render artifacts in addition to the subset PDF. Whole-document fingerprint jobs emit lossless 144-DPI rasters, so large documents must fit the configured output budget.

## PowerPoint release interface

Drawbridge 0.3.1 accepts ordinary transitional PowerPoint packages, with one section per canonical source slide. Use `drawbridge convert slides.pptx --notes include -o slides.md` or explicit `--notes exclude`, then `drawbridge verify slides.md --source slides.pptx`. Notes stay attached to the applicable slide; animation builds do not create extra slide sections. Existing page mirrors and `--pdf` verification spelling remain supported. See [the slide contract and limitations](POWERPOINT.md), including text-only extraction, notes inventory privacy and operating-system controls.
