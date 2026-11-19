"""Qualify the installed local Drawbridge wheel inside a networkless arm64 image."""

from __future__ import annotations

import argparse
import hashlib
import json
import locale
import os
import platform
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation

SENTINEL = "LOCAL DRAWBRIDGE TEST"


def run(argv: list[str | Path], **options) -> str:
    result = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=420, **options)
    return result.stdout


def synthetic_inputs(work: Path, font_file: Path) -> list[Path]:
    text, docx, pptx, image = [work / ("synthetic." + suffix) for suffix in ("txt", "docx", "pptx", "png")]
    text.write_text(SENTINEL + "\n", encoding="utf-8")
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("[Content_Types].xml", """
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
""")
        archive.writestr("word/document.xml", f"""
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{SENTINEL}</w:t></w:r></w:p></w:body>
</w:document>
""")
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[0])
    slide.shapes.title.text = SENTINEL
    deck.save(pptx)
    canvas = Image.new("RGB", (1200, 400), "white")
    ImageDraw.Draw(canvas).text((80, 140), SENTINEL, font=ImageFont.truetype(font_file, 64), fill="black")
    canvas.save(image, dpi=(150, 150))
    canvas.close()
    return [text, docx, pptx, image]


def probe_numpy_worker(work: Path, source: Path) -> str:
    from drawbridge.presentation_worker import _worker_environment

    code = """
import json
import sys

from drawbridge import presentation_worker

assert "numpy" not in sys.modules
native_filter = presentation_worker._linux_network_filter
versions = []

def load_numpy_under_filter():
    native_filter()
    import numpy
    versions.append(numpy.__version__)

presentation_worker._linux_network_filter = load_numpy_under_filter
result = presentation_worker._main()
if result or len(versions) != 1:
    raise SystemExit(1)
print(json.dumps({"numpy": versions[0]}))
"""
    output = run(
        [sys.executable, "-I", "-B", "-c", code, source, "include"],
        cwd=work, env=_worker_environment(work),
    )
    ready, result, version = map(json.loads, output.splitlines())
    assert ready == {"status": "ready"} and result["status"] == "ok"
    return version["numpy"]


def qualify(root: Path, fixtures: Path, font_file: Path, drawbridge: Path, vellric: Path, candidate: str) -> None:
    if platform.system() != "Linux" or platform.machine() != "aarch64" or not os.confstr("CS_GNU_LIBC_VERSION"):
        raise SystemExit("qualification requires Linux aarch64 glibc")
    locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
    root.mkdir()
    inputs, outputs = root / "inputs", root / "outputs"
    inputs.mkdir()
    outputs.mkdir()
    config = root / "qualification.yaml"
    config.write_text(json.dumps({
        "drawbridge": {
            "identify": {"file_executable": "/usr/bin/file"},
            "vellric": {"executable": str(vellric)},
            "paths": {"work_dir": str(root / "work"), "output_dir": str(outputs),
                      "path": [str(vellric.parent), "/usr/local/bin", "/usr/bin", "/bin"]},
            "convert": {"json": True, "local_only": True, "no_ai": True},
        },
        "vellric": {},
    }), encoding="utf-8")
    scope = ["--config", config]
    doctor = json.loads(run([drawbridge, "doctor", "--require-pdf", "--require-image-ocr", *scope]))
    versions = {
        name: run([executable, "-version" if name in {"ffmpeg", "ffprobe"} else "--version"]).splitlines()[0]
        for name, executable in doctor["tools"].items() if executable
    }
    synthetic = synthetic_inputs(inputs, font_file)
    print(json.dumps({
        "candidate": candidate, "platform": platform.platform(), "doctor": doctor,
        "glibc": os.confstr("CS_GNU_LIBC_VERSION"), "runtime_versions": versions,
        "contained_numpy": probe_numpy_worker(root, synthetic[2]),
    }))
    sources = [*synthetic, fixtures / "trivial.pdf", fixtures / "ccitt.pdf"]
    inputs.chmod(0o555)
    try:
        for source in sources:
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            result = json.loads(run([drawbridge, "convert", source, *scope]))
            output = Path(result["output"])
            assert output.parent == outputs
            assert result["content_hash"] == f"sha256:{original}"
            assert hashlib.sha256(source.read_bytes()).hexdigest() == original
            assert "libmagic-unavailable" not in result["verify"]
            if source in synthetic:
                assert SENTINEL in output.read_text(encoding="utf-8")
                assert "ocr-pending" not in result["verify"]
            if source.suffix in {".pptx", ".pdf"}:
                run([drawbridge, "verify", output, "--source", source, *scope])
            if source.name == "ccitt.pdf":
                assert result["ocr_pages"] and "LinnSequencer" in output.read_text(encoding="utf-8")
            print(json.dumps({"input": source.name, "method": result["method"], "output": str(output)}))
    finally:
        inputs.chmod(0o755)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "fixtures", "font", "drawbridge", "vellric"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    qualify(args.root, args.fixtures, args.font, args.drawbridge, args.vellric, args.candidate)


if __name__ == "__main__":
    main()
