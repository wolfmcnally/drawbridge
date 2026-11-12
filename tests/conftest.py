from __future__ import annotations

import os
import shutil
from pathlib import Path

import pymupdf
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def isolate_fixture_git_signing(environment: dict[str, str]) -> None:
    """Fixture repositories never sign: the operator's signing setup is not under test.

    A machine that signs every commit hands that setting to each throwaway repository a
    test creates, and a signing agent asked to sign many commits at once refuses some of
    them. Git reads these variables after every configuration file, so the override holds
    whatever the machine configures. Entries a caller already supplied are kept, and a
    nested test run that inherits these does not add them twice.
    """
    count = int(environment.get("GIT_CONFIG_COUNT", "0") or "0")
    supplied = {environment.get(f"GIT_CONFIG_KEY_{index}") for index in range(count)}
    for key in ("commit.gpgsign", "tag.gpgsign"):
        if key in supplied:
            continue
        environment[f"GIT_CONFIG_KEY_{count}"] = key
        environment[f"GIT_CONFIG_VALUE_{count}"] = "false"
        count += 1
    environment["GIT_CONFIG_COUNT"] = str(count)


isolate_fixture_git_signing(os.environ)


REPOSITORY = Path(__file__).resolve().parents[1]
PREPARE_SCRIPTS = "drawbridge_prepare_scripts"


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node):
    """Only a top-level run's workers prepare; a run nested inside a worker builds lazily.

    A test that launches its own parallel run starts inside a worker, whose environment
    names that worker. Its workers would otherwise rebuild every script environment.
    """
    node.workerinput[PREPARE_SCRIPTS] = "PYTEST_XDIST_WORKER" not in os.environ


def pytest_configure(config):
    """Standalone uv script environments must not be rebuilt by another worker.

    Each worker of a private run has its own cache, which the supervisor's build never
    reaches, so the worker builds its script environments there before any test runs
    tools together. A serial run has no workers and prepares nothing.
    """
    private_root = os.environ.get("DRAWBRIDGE_TEST_UV_CACHE_ROOT")
    if private_root:
        workerinput = getattr(config, "workerinput", {})
        worker = workerinput.get("workerid", "master")
        cache = Path(private_root) / worker
        cache.mkdir(parents=True, exist_ok=True)
        os.environ["UV_CACHE_DIR"] = str(cache)
        if workerinput.get(PREPARE_SCRIPTS):
            import importlib.util

            runner = REPOSITORY / "lib" / "agentic_starter" / "test_runner.py"
            spec = importlib.util.spec_from_file_location("drawbridge_test_runner", runner)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            arguments = ["-n", str(workerinput["workercount"])]
            module.prepare_script_environments(REPOSITORY, arguments, os.environ)


MINIMAL_ZERO_PAGE_PDF = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj
xref
0 3
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
trailer << /Size 3 /Root 1 0 R >>
startxref
110
%%EOF
"""


def _ocr_tools_present() -> bool:
    return shutil.which("ocrmypdf") is not None and shutil.which("tesseract") is not None


def pytest_collection_modifyitems(config, items):
    if _ocr_tools_present():
        return
    skip = pytest.mark.skip(reason="ocrmypdf and tesseract are required for live OCR tests")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def native_pdf(tmp_path: Path):
    """Factory: a born-digital PDF with one page per string."""

    def make(texts: list[str], name: str = "native.pdf") -> Path:
        target = tmp_path / name
        with pymupdf.open() as document:
            for text in texts:
                document.new_page().insert_text((72, 72), text)
            document.save(target)
        return target

    return make


@pytest.fixture
def raster_png() -> bytes:
    """A page-sized PNG carrying rendered text, for building synthetic scans."""
    with pymupdf.open() as source:
        source.new_page().insert_text((72, 72), "Scanned source evidence")
        return source[0].get_pixmap().tobytes("png")


@pytest.fixture
def mixed_pdf(tmp_path: Path, raster_png: bytes) -> Path:
    """Page 1 native, page 2 raster-only, page 3 raster with a stale invisible OCR layer."""
    target = tmp_path / "mixed.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Native text remains exact")
        for index in range(2):
            page = document.new_page()
            page.insert_image(page.rect, stream=raster_png)
            if index == 1:
                page.insert_text((72, 100), "stale wrong OCR", render_mode=3)
        document.save(target)
    return target


@pytest.fixture
def logo_pdf(tmp_path: Path, raster_png: bytes) -> Path:
    """Native text with a small image: must not be selected for OCR."""
    target = tmp_path / "logo.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Letterhead body text")
        page.insert_image(pymupdf.Rect(400, 20, 500, 80), stream=raster_png)
        document.save(target)
    return target


@pytest.fixture
def encrypted_pdf(tmp_path: Path) -> Path:
    target = tmp_path / "secret.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "hidden")
        document.save(
            target,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw="user-secret",
            owner_pw="owner-secret",
        )
    return target


@pytest.fixture
def permissions_only_pdf(tmp_path: Path) -> Path:
    """Owner password only: opens with the empty user password and reads normally."""
    target = tmp_path / "locked-print.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "readable despite owner password")
        document.save(
            target,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw="",
            owner_pw="owner-secret",
            permissions=pymupdf.PDF_PERM_ACCESSIBILITY,
        )
    return target


@pytest.fixture
def zero_page_pdf(tmp_path: Path) -> Path:
    target = tmp_path / "zero.pdf"
    target.write_bytes(MINIMAL_ZERO_PAGE_PDF)
    return target


@pytest.fixture
def tmp_path():
    """Owned private scratch shared by product and methodology fixture factories."""
    import tempfile

    parent = Path(__file__).resolve().parents[1] / ".kickoff" / "proof-runtime"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=parent) as directory:
        yield Path(directory)
