# Install Drawbridge 0.1.0

Python 3.12+ and uv are required for the examples. From the directory containing the downloaded wheel:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python ./drawbridge-0.1.0-py3-none-any.whl
.venv/bin/drawbridge --version
printf 'Plain local evidence.\n' > example.txt
.venv/bin/drawbridge convert example.txt --no-profile --stdout
```

Text/office/email conversion needs no Vellric. PDF work requires **independently installed Vellric 0.1.0** and its qualified native/OCR prerequisites. Install that wheel/source into a different environment, then set:

```bash
export DRAWBRIDGE_VELLRIC=/absolute/vellric-env/bin/vellric
.venv/bin/drawbridge inspect input.pdf
.venv/bin/drawbridge convert input.pdf --no-profile --stdout
```

Use the real absolute executable path, not the illustrative placeholder. No sibling checkout, PyMuPDF import or editable Vellric package is required in Drawbridge. Image OCR uses Pillow plus Tesseract. The Vellric installation guide explains pinned OCRmyPDF/Tesseract, language data and platform prerequisites; doctor reports the actual installation.

For exact locked runtime packages, export this source's uv.lock with `uv export --locked --no-dev --no-emit-project --format requirements-txt`, install it with `uv pip install --require-hashes`, then install the project wheel with `--no-deps`. Source builds use build-constraints.txt; matching source includes tests, methodology/design docs and notices.

The optional audio extra installs the **Quillric** distribution. Its compatibility Python namespace/CLI and retained artifact directories remain `transcribe`; do not install a separate old distribution named transcribe. Provider stages need an explicit profile and keys and can incur charges. Start with dry-run; those paid examples are not part of local PDF release qualification.

Developer setup: `uv sync --locked --group dev`, configure the independent Vellric executable, then `uv run --locked pytest`. Existing live tests require actual qualified OCR tools; they are not silently skipped when the engine is missing.

Quillric 0.1.0 is absent from PyPI at preparation. Its exact locked Git commit is publicly reachable. From the directory containing the Drawbridge wheel, install the source dependency first, then the audio extra:

```bash
uv venv --python 3.12 .venv-audio
uv pip install --python .venv-audio/bin/python 'quillric @ git+https://github.com/wolfmcnally/quillric.git@c48b76e522f4e677df9184a2e82469ddcdb9cee9'
uv pip install --python .venv-audio/bin/python './drawbridge-0.1.0-py3-none-any.whl[audio]'
.venv-audio/bin/drawbridge --version
```

This route requires Git and network access to the public source and dependency index. Audio/video processing additionally needs ffmpeg and the selected provider credentials. Installation and CLI startup make no provider calls.
