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

## Explicit composed configuration

Repeat `convert --config FILE` to compose YAML layers in order with Conric. Included relative files apply before the containing file; later layers override earlier values. `--config-root DIRECTORY` explicitly confines all files and includes; without it Conric uses the first file's directory. A root requires at least one configuration file. Explicit configuration conflicts with `--profile` and `--no-profile` and bypasses ambient profile and dotenv discovery.

```bash
.venv/bin/drawbridge convert input.pdf --config base.yaml --config local.yaml --config-root . --local-only --no-ai --dry-run
```

Drawbridge validates only its optional `drawbridge` subtree using the retained profile format. In this mode network endpoints claiming local egress require an explicit HTTP(S) loopback URL, and applicable model stages require an explicit model. Local command endpoints remain supported. Drawbridge does not add fallback models. Its own subtree accepts variable names such as `api_key_env`, rather than unresolved tagged values. Other leaf schemas remain opaque to Drawbridge. Vellric owns its `vellric` subtree, which must be present for a configured PDF job; an absent or invalid leaf is rejected by that independently installed CLI. A minimal deterministic PDF configuration is:

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


## Native media identities and range derivatives

`drawbridge.pdf_tools.page_fingerprints(path)` returns tuples of exact RGB page hashes and native difference hashes, including forms and annotations. `materialize_pdf_range(parent, destination, start, end)` copies a validated deterministic inclusive range artifact. `canonical_image(path, width=None, height=None)` returns ordinary RGB bytes, dimensions and native hashes after validating the standalone image bundle. These complete jobs require independently installed Vellric; Drawbridge never imports the engine. Difference hashes are similarity proposals, not duplicate verdicts. Canonical comparison never upsamples or introduces a pixel-error tolerance.

The adapter caches CLI compatibility diagnosis for the process lifetime, keyed by executable path/inode/size/modification time. An independently reinstalled CLI invalidates the probe. Every complete job still validates its manifest, source and artifact hashes and checks its own engine/resource availability. Diagnosis has a separate 90-second budget and reports unavailable capabilities distinctly from a document failure. Tessdata forwarding applies to conversion jobs; stale ambient OCR settings do not affect native inspection or images. DRAWBRIDGE_VELLRIC_MAX_OUTPUT_BYTES can lower the job output budget; the adapter also enforces its independent 2 GiB artifact cap. PDF range jobs currently produce temporary 72-DPI render artifacts in addition to the subset PDF. Whole-document fingerprint jobs emit lossless 144-DPI rasters, so large documents must fit the configured output budget.
