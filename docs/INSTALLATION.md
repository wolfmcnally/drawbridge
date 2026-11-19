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

For a developer checkout, use `./bin/setup` and `./bin/test` with a qualified independent Vellric. The test harness visibly skips tests marked `live` when either `ocrmypdf` or `tesseract` is absent from its PATH. An installed OCR qualification requires those tests or equivalent installed smoke checks to execute successfully.

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


## Offline Linux aarch64 source qualification

The following procedure is for wheels built from the matching unreleased source. Prepare a local glibc arm64 image with Python 3.12, the `en_US.UTF-8` locale, `file` and its magic database, Tesseract and the selected tessdata, OCRmyPDF, its qualified system dependencies including Ghostscript and QPDF where used, and a font for the synthetic OCR example. Keep Vellric and its native Python dependencies in a separate runtime. Record the image digest, the exact executable paths and versions, and the candidate source identity. The optional audio route additionally needs `ffmpeg` and `ffprobe`. The Linux PPTX worker uses the installed Python executable and Linux seccomp through libc.

Prepare a wheelhouse for the image's architecture, ABI and glibc version. Build the Drawbridge and Conric wheels from the candidate source and exact locked Conric commit. Stage the independently pinned Vellric wheel and its exact dependencies. Provide a hash-locked requirements file for each environment that names the local wheels by version and hash, including all transitive dependencies. Use the locked Quillric source wheel only for an audio-enabled build, and include the locked Botocore wheels only for the optional SigV4 transport. Keep the candidate wheel hash and the original source commits in the qualification record.

Run installation and verification in a local container started with `--pull=never --platform linux/arm64 --network none`. Mount the wheelhouse and source read-only. Give the container a separate writable work directory for the environments, mirrors and temporary files. With the verified requirements mounted at `/wheelhouse/drawbridge.txt` and `/wheelhouse/vellric.txt`, install each independently:

```sh
python -m venv /work/drawbridge
```

```sh
python -m venv /work/vellric
```

```sh
/work/drawbridge/bin/python -m pip install --no-index --find-links /wheelhouse --no-deps --require-hashes -r /wheelhouse/drawbridge.txt
```

```sh
/work/vellric/bin/python -m pip install --no-index --find-links /wheelhouse --no-deps --require-hashes -r /wheelhouse/vellric.txt
```

Using `--no-deps` is intentional for the verified, complete wheel lists: the published metadata contains direct source references that a resolver could otherwise try to fetch. Keep `file` at `/usr/bin/file`, expose the qualified OCR tools on the executable path supplied in the smoke script, and install the pinned font at the path provided to the script. Run the doctor and installed checks using the matching source mounted at `/source`. Set `DRAWBRIDGE_CANDIDATE` to the exact identity recorded when building the wheel.

```sh
/work/drawbridge/bin/python -I /source/scripts/qualify_linux_arm64.py --root /work/qualification --fixtures /source/tests/fixtures --font /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf --drawbridge /work/drawbridge/bin/drawbridge --vellric /work/vellric/bin/vellric --candidate "$DRAWBRIDGE_CANDIDATE"
```

The script generates its text, DOCX, PPTX and image fixtures locally, and uses the matching public born-digital and scanned PDF fixtures. Retain wheel hashes, locale and binary version output, doctor output and successful conversion records for the tested candidate. Include an exact, hash-verified NumPy wheel in the qualification environment. The qualification invokes the real PPTX worker entry point in a fresh Python child, imports NumPy after seccomp is active and the worker's CPU, file-size and address-space limits are set, and requires the worker to report a successful conversion. NumPy is a qualification dependency.
