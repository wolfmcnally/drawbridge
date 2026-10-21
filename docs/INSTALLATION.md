# Install Drawbridge 0.2.0

Python 3.12+ and uv are required for the examples. From the directory containing the downloaded wheel:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python ./drawbridge-0.2.0-py3-none-any.whl
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

Explicit composed configuration requires the Conric-aware Vellric CLI. As of 2026-10-21, [Vellric 0.2.2](https://github.com/wolfmcnally/vellric/releases/tag/v0.2.2) is a public regular release at commit `18c89b9ede1ec5cf3dbf198fed7fbac7c67945ae`. Install its trusted release wheel into its own environment using the matching source archive's lock and installation instructions, then select it with `DRAWBRIDGE_VELLRIC`. Drawbridge's CI verifies the exact release artifact hashes before installing registry dependencies with hashes and the exact public Conric source separately. Doctor schema/behavior admission and complete job validation still apply. Cloud-vision human acceptance and Windows desktop acceptance remain open upstream; this integration does not establish either. Configuration forwarding preserves the credential scrub and does not enable authenticated provider execution. See [explicit configuration usage](USAGE.md#explicit-composed-configuration).

Drawbridge's runtime dependency pins public MIT Conric 0.1.0 to the flat repository root at `https://github.com/wolfmcnally/conric`, commit `ed9286297e92b8c049f70eb15a3b5556ed107ff0`. Wheel dependency installation requires Git and network access to that source; it does not require a sibling source checkout. Vellric and its PDF engine remain outside the Drawbridge runtime environment.

For locked source development, use `uv sync --locked`. For a core wheel installation with registry hashes enforced, export the lock, separate the single approved Conric Git reference using the matching source's helper, and install that immutable source separately. A full `--require-hashes` requirements file cannot include a Git dependency. From matching source, after creating `.venv`:

```bash
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt
python3 scripts/split_conric_requirements.py requirements.txt registry-requirements.txt
uv pip install --python .venv/bin/python --require-hashes --requirements registry-requirements.txt
uv pip install --python .venv/bin/python --no-deps --build-constraints build-constraints.txt 'conric @ git+https://github.com/wolfmcnally/conric.git@ed9286297e92b8c049f70eb15a3b5556ed107ff0'
uv pip install --python .venv/bin/python --no-deps ./dist/drawbridge-0.2.0-py3-none-any.whl
```

The helper refuses a changed or missing Conric source and any additional direct URL/VCS requirement. Source builds use build-constraints.txt; matching source includes tests, methodology/design docs, the helper and notices. The audio extra has its separate pinned source procedure below.

The optional audio extra installs the **Quillric** distribution. Its compatibility Python namespace/CLI and retained artifact directories remain `transcribe`; do not install a separate old distribution named transcribe. Provider stages need an explicit profile and keys and can incur charges. Start with dry-run; those paid examples are not part of local PDF release qualification.

Developer setup: `uv sync --locked --group dev`, configure the independent Vellric executable, then `uv run --locked pytest`. Existing live tests require actual qualified OCR tools; they are not silently skipped when the engine is missing.

Quillric 0.1.0 is absent from PyPI at preparation. Its exact locked Git commit is publicly reachable. From the directory containing the Drawbridge wheel, install the source dependency first, then the audio extra:

```bash
uv venv --python 3.12 .venv-audio
uv pip install --python .venv-audio/bin/python 'quillric @ git+https://github.com/wolfmcnally/quillric.git@c48b76e522f4e677df9184a2e82469ddcdb9cee9'
uv pip install --python .venv-audio/bin/python './drawbridge-0.2.0-py3-none-any.whl[audio]'
.venv-audio/bin/drawbridge --version
```

This route requires Git and network access to the public source and dependency index. Audio/video processing additionally needs ffmpeg and the selected provider credentials. Installation and CLI startup make no provider calls.
