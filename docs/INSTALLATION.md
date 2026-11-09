# Install Drawbridge 0.3.1

Python 3.12+ and uv are required for the examples. From the directory containing the downloaded wheel:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python ./drawbridge-0.3.1-py3-none-any.whl
.venv/bin/drawbridge --version
printf 'Plain local evidence.\n' > example.txt
.venv/bin/drawbridge convert example.txt --no-profile --stdout
```

Text/office/email conversion needs no Vellric. PDF work requires **independently installed Vellric** and its qualified native/OCR prerequisites. Install the qualified wheel/source into a different environment, then set:

```bash
export DRAWBRIDGE_VELLRIC=/absolute/vellric-env/bin/vellric
.venv/bin/drawbridge inspect input.pdf
.venv/bin/drawbridge convert input.pdf --no-profile --stdout
```

Use the real absolute executable path, not the illustrative placeholder. No sibling checkout, PyMuPDF import or editable Vellric package is required in Drawbridge. Image OCR uses Pillow plus Tesseract. The Vellric installation guide explains pinned OCRmyPDF/Tesseract, language data and platform prerequisites; doctor reports the actual installation.

Explicit composed configuration requires the Conric-aware Vellric CLI. As of 2026-10-29, [Vellric 0.2.4](https://github.com/wolfmcnally/vellric/releases/tag/v0.2.4) is a public regular release at commit `8b410165a52b246e72dc2ac326ce9e289c80aa43`. Install its trusted release wheel into its own environment using the matching source archive's lock and installation instructions, then select it with `DRAWBRIDGE_VELLRIC`. Drawbridge's CI verifies the exact release artifact hashes before installing registry dependencies with hashes and the exact public Conric source separately. Doctor schema/behavior admission and complete job validation still apply. Cloud-vision human acceptance and Windows desktop acceptance remain open upstream; this integration does not establish either. Configuration forwarding preserves the credential scrub and does not enable authenticated provider execution. See [explicit configuration usage](USAGE.md#explicit-composed-configuration).

Drawbridge's runtime dependency pins public MIT Conric 0.1.0 to the flat repository root at `https://github.com/wolfmcnally/conric`, release tag `v0.1.0` (resolved in the lock to `ed9286297e92b8c049f70eb15a3b5556ed107ff0`). Wheel dependency installation requires Git and network access to that source; it does not require a sibling source checkout. Vellric and its PDF engine remain outside the Drawbridge runtime environment.

For locked source development, use `uv sync --locked`. For a core wheel installation with registry hashes enforced, export the lock, separate the single approved Conric Git reference using the matching source's helper, and install that immutable source separately. A full `--require-hashes` requirements file cannot include a Git dependency. From matching source, after creating `.venv`:

```bash
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt
python3 scripts/split_conric_requirements.py requirements.txt registry-requirements.txt
uv pip install --python .venv/bin/python --require-hashes --requirements registry-requirements.txt
uv pip install --python .venv/bin/python --no-deps --build-constraints build-constraints.txt 'conric @ git+https://github.com/wolfmcnally/conric.git@v0.1.0'
uv pip install --python .venv/bin/python --no-deps ./dist/drawbridge-0.3.1-py3-none-any.whl
```

The helper refuses a changed or missing Conric source and any additional direct URL/VCS requirement. Source builds use build-constraints.txt; matching source includes product tests and design docs, the helper and notices. The audio extra has its separate pinned source procedure below.

The optional audio extra installs the **Quillric** distribution. Its compatibility Python namespace/CLI and retained artifact directories remain `transcribe`; do not install a separate old distribution named transcribe. Provider stages need an explicit profile and keys and can incur charges. Start with dry-run; those paid examples are not part of local PDF release qualification.

Developer setup: `uv sync --locked --group dev`, configure the independent Vellric executable, then `uv run --locked pytest`. Existing live tests require actual qualified OCR tools; they are not silently skipped when the engine is missing.

Optional Quillric is installed from its published `v0.1.0` GitHub release tag, resolved by the lock to the previously qualified commit. From the directory containing the Drawbridge wheel, install the tagged source dependency first, then the audio extra:

```bash
uv venv --python 3.12 .venv-audio
uv pip install --python .venv-audio/bin/python 'quillric @ git+https://github.com/wolfmcnally/quillric.git@v0.1.0'
uv pip install --python .venv-audio/bin/python './drawbridge-0.3.1-py3-none-any.whl[audio]'
.venv-audio/bin/drawbridge --version
```

This route requires Git and network access to the public source and dependency index. Audio/video processing additionally needs ffmpeg and the selected provider credentials. Installation and CLI startup make no provider calls.

## PowerPoint and release verification

Ordinary PowerPoint ingestion needs the separately installed locked python-pptx, lxml and XlsxWriter dependencies; no renderer or PDF engine is needed. The worker requires its documented operating-system controls. Installed PowerPoint qualification targets Python 3.12.12 on macOS arm64 and Linux aarch64. Fresh installed native/configured/OCR PDF qualification is on macOS arm64 only. Other advertised Python versions, including the 3.13 and 3.14 classifiers, are not additional installation-trial claims. See [PowerPoint boundaries](POWERPOINT.md) and [release facts](RELEASES.md).

The wheel and matching source archive are the public installation artifacts. The source archive supplies its lock, build constraints, notices, public fixtures and product tests. A public repository checkout can run product tests with declared prerequisites. The complete maintainer gate also audits private retained phase acceptance under ignored operational storage; a fresh public clone does not contain that proof and cannot replay that portion of the gate. Public CI runs the product test wrapper and does not establish private historical acceptance. No private proof is needed to install or use the release artifacts, and it must not be copied into them.
