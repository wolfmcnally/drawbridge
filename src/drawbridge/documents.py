"""One dispatch for every file type: a file in, one mirror out.

Each converter is deterministic and local. A type nothing here can read yields a deferred stub
that says so in ``verify``; it never pretends to be a conversion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from . import office
from .convert import ConversionOptions, ConversionResult, convert_pdf
from .errors import DrawbridgeError
from .identify import PDF_MEDIA_TYPE, sniff_media_type
from .mirror import (
    Mirror,
    build_header,
    now_iso,
    render_mirror,
    sha256_file,
    title_from_name,
)
from .ocr import CliOcrBackend, OcrBackend
from .orientation import recover_page
from .profile import EMPTY_PROFILE, Plan, Profile, build_plan

NO_TEXT_MARKER = "[No text detected.]"
TEXT_LIKE = frozenset(
    {"application/json", "application/yaml", "application/x-yaml", "application/xml"}
)
MAIL_HEADERS = ("Date", "From", "To", "Cc", "Subject")


@dataclass(frozen=True)
class FileConversion:
    """The result of converting any file. ``pdf`` carries the page-level detail for a PDF."""

    mirror: Mirror
    media_type: str
    method: str
    flags: tuple[str, ...] = ()
    pdf: ConversionResult | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    plan: Plan | None = None
    package: Any = None  # the transcription package, for an audio or video input
    semantic: Mirror | None = (
        None  # the groomed rendering, when the plan ran a grooming stage
    )


def _mirror(
    path: Path,
    options: ConversionOptions,
    media_type: str,
    method: str,
    unit: str,
    body: str,
    verify: tuple[str, ...] = (),
    extra: dict[str, Any] | None = None,
) -> Mirror:
    header = build_header(
        path,
        method=method,
        mirror_of=options.mirror_of,
        media_type=media_type,
        acquired_at=options.acquired_at,
        acquisition_method=options.acquisition_method,
        acquired_from=options.acquired_from,
        agent=options.agent,
        verify=(*options.verify, *verify),
        unit=unit,
        extra=extra,
        extensions=options.extensions,
    )
    return Mirror(header, body)


def _newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _titled(path: Path, options: ConversionOptions, text: str) -> str:
    return f"# {options.title or title_from_name(path.name)}\n\n{text}"


def _docx(path: Path, options: ConversionOptions, media_type: str) -> FileConversion:
    body = _titled(path, options, office.docx_text(path))
    return FileConversion(
        _mirror(path, options, media_type, "docx-xml-extract", "document", body),
        media_type,
        "docx-xml-extract",
    )


def _doc(path: Path, options: ConversionOptions, media_type: str) -> FileConversion:
    body = _titled(path, options, office.word97_text(path))
    return FileConversion(
        _mirror(path, options, media_type, "word97-piece-table", "document", body),
        media_type,
        "word97-piece-table",
    )


def _xlsx(path: Path, options: ConversionOptions, media_type: str) -> FileConversion:
    body = _titled(path, options, office.xlsx_text(path))
    return FileConversion(
        _mirror(path, options, media_type, "xlsx-openpyxl-data-only", "sheet", body),
        media_type,
        "xlsx-openpyxl-data-only",
    )


def _xls(path: Path, options: ConversionOptions, media_type: str) -> FileConversion:
    body = _titled(path, options, office.xls_text(path))
    return FileConversion(
        _mirror(path, options, media_type, "xls-xlrd-data-only", "sheet", body),
        media_type,
        "xls-xlrd-data-only",
    )


def _text(path: Path, options: ConversionOptions, media_type: str) -> FileConversion:
    raw = path.read_bytes()
    if b"\x00" in raw:
        # A type sniffer will call almost anything text. NUL bytes say otherwise.
        return deferred(path, options, media_type, "binary-content")
    try:
        text, verify = raw.decode("utf-8"), ()
    except UnicodeDecodeError:
        text, verify = raw.decode("utf-8", errors="replace"), ("text-decode-lossy",)
    body = _titled(path, options, _newlines(text))
    return FileConversion(
        _mirror(
            path, options, media_type, "text-decode:utf-8", "document", body, verify
        ),
        media_type,
        "text-decode:utf-8",
        verify,
    )


_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "tr",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "table",
        "ul",
        "ol",
        "hr",
    }
)
_SILENT_TAGS = frozenset({"script", "style", "head", "title"})


class _HtmlText(HTMLParser):
    """The visible words of an HTML body, with block boundaries as line breaks. No structure is rebuilt."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.silent = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SILENT_TAGS:
            self.silent += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SILENT_TAGS:
            self.silent = max(0, self.silent - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.silent:
            self.parts.append(data)


def html_text(markup: str) -> str:
    parser = _HtmlText()
    parser.feed(markup)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    collapsed: list[str] = []
    for line in lines:
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    return "\n".join(collapsed).strip()


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _eml(path: Path, options: ConversionOptions, media_type: str) -> FileConversion:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    part = message.get_body(preferencelist=("plain",))
    verify: tuple[str, ...] = ()
    content = str(part.get_content()) if part else ""
    if part is None:
        html = message.get_body(preferencelist=("html",))
        if html is not None:
            # No plain alternative was sent: keep the words, and say they came through a tag stripper.
            content, verify = (
                html_text(str(html.get_content())),
                ("email-body-from-html",),
            )
    attachments = [
        item.get_filename() or item.get_content_type()
        for item in message.iter_attachments()
    ]
    lines = [
        "| Header | Value |",
        "|---|---|",
        *[
            f"| {key} | {_cell(message.get(key))} |"
            for key in MAIL_HEADERS
            if message.get(key)
        ],
    ]
    if attachments:
        lines += [
            "",
            "Attachments (not converted here): "
            + ", ".join(_cell(name) for name in attachments),
        ]
    lines += ["", "## Body", "", _newlines(content).strip() or NO_TEXT_MARKER]
    body = _titled(path, options, "\n".join(lines))
    extra = {"attachment_count": len(attachments)}
    return FileConversion(
        _mirror(
            path, options, media_type, "email-rfc822", "message", body, verify, extra
        ),
        media_type,
        "email-rfc822",
        verify,
        extras=extra,
    )


def _image(
    path: Path,
    options: ConversionOptions,
    media_type: str,
    *,
    ocr_available: bool,
    image_ocr: CliOcrBackend | None = None,
    profile: Profile | None = None,
    plan: Plan | None = None,
) -> FileConversion:
    verify: tuple[str, ...] = ()
    extra: dict[str, Any] = {}
    text = ""
    if ocr_available:
        try:
            settings = (
                {
                    "dpi": image_ocr.dpi,
                    "language": image_ocr.language,
                    "timeout": image_ocr.tesseract_timeout,
                    "tessdata_dir": image_ocr.tessdata_dir,
                }
                if image_ocr is not None
                else {}
            )
            page = recover_page(path, 1, **settings)
            text, extra = page.text, {"ocr_pages": [page.as_dict()]}
        except (DrawbridgeError, OSError, ValueError):
            verify = ("ocr-pending",)
    else:
        verify = ("ocr-pending",)
    sections = f"## OCR\n\n{text.strip() or NO_TEXT_MARKER}"
    entry = None
    if profile is not None and plan is not None:
        from .describe import SECTION, describe_image

        description, entry, flag = describe_image(
            path, sha256_file(path), profile=profile, plan=plan
        )
        if description:
            sections += f"\n\n## {SECTION}\n\n{description}"
        if flag:
            verify = (*verify, flag)
    mirror = _mirror(
        path,
        options,
        media_type,
        "image-ocr",
        "document",
        _titled(path, options, sections),
        verify,
        extra,
    )
    if entry:
        mirror.header["processing"].append(
            {
                "seq": len(mirror.header["processing"]) + 1,
                **entry,
                "performed_at": now_iso(),
                "agent": options.agent,
            }
        )
    return FileConversion(
        mirror,
        media_type,
        "image-ocr",
        tuple(mirror.header["verify"]),
        plan=plan,
        extras=extra,
    )


def deferred(
    path: Path, options: ConversionOptions, media_type: str, reason: str
) -> FileConversion:
    """A stub mirror for a file nothing here can read. The original remains the only authority."""
    method = f"conversion-deferred:{reason}"
    body = _titled(
        path, options, "Conversion is deferred. The original remains authoritative.\n"
    )
    return FileConversion(
        _mirror(
            path, options, media_type, method, "document", body, ("mirror-pending",)
        ),
        media_type,
        method,
        ("mirror-pending",),
    )


_BY_TYPE: dict[str, Callable[[Path, ConversionOptions, str], FileConversion]] = {
    office.DOCX_MEDIA_TYPE: _docx,
    office.DOC_MEDIA_TYPE: _doc,
    office.XLSX_MEDIA_TYPE: _xlsx,
    office.XLS_MEDIA_TYPE: _xls,
    "message/rfc822": _eml,
}


def supported(media_type: str) -> bool:
    return (
        media_type == PDF_MEDIA_TYPE
        or media_type in _BY_TYPE
        or media_type in TEXT_LIKE
        or media_type.startswith(("text/", "image/", "audio/", "video/"))
    )


def convert_file(
    path: Path | str,
    *,
    ocr: OcrBackend | None = None,
    options: ConversionOptions | None = None,
    media_type: str | None = None,
    profile: Profile | None = None,
    plan: Plan | None = None,
    artifacts_dir: Path | None = None,
    budget: Any = None,
    stages: bool = True,
) -> FileConversion:
    """Convert one file of any type. ``media_type`` overrides sniffing when the caller already knows it.

    Without a ``profile`` nothing networked runs, and audio or video is refused. ``plan`` lets a caller
    that already narrowed the stages pass its decision in; ``artifacts_dir`` is where a transcription
    package is kept (beside the input by default). With ``stages`` the grooming stages the plan runs
    (structure for a PDF, refinement for a transcript) produce ``semantic``; the fidelity mirror is never changed.

    Raises a typed ``DrawbridgeError`` for every document-local failure, exactly as ``convert_pdf`` does.
    """
    path = Path(path)
    options = options or ConversionOptions()
    flags: list[str] = []
    if media_type is None:
        media_type, flags = sniff_media_type(path)
    if flags:
        options = options.with_verify(flags)
    if media_type == PDF_MEDIA_TYPE:
        result = convert_pdf(path, ocr=ocr, options=options)
        profile = profile or EMPTY_PROFILE
        plan = plan or build_plan(profile, media_type)
        semantic = None
        if stages and plan.runs("structure"):
            from .structure import run_structure

            semantic = run_structure(
                render_mirror(result.mirror), profile=profile, plan=plan, source=path
            )
        return FileConversion(
            result.mirror,
            media_type,
            result.method,
            tuple(flags),
            pdf=result,
            extras=result.extras,
            plan=plan,
            semantic=semantic,
        )
    if media_type in _BY_TYPE:
        return _BY_TYPE[media_type](path, options, media_type)
    if media_type in TEXT_LIKE or media_type.startswith("text/"):
        return _text(path, options, media_type)
    if media_type.startswith("image/"):
        profile = profile or EMPTY_PROFILE
        return _image(
            path,
            options,
            media_type,
            ocr_available=ocr is not None,
            image_ocr=ocr if isinstance(ocr, CliOcrBackend) else None,
            profile=profile,
            plan=plan or build_plan(profile, media_type),
        )
    if media_type.startswith(("audio/", "video/")):
        from .audio import METHOD, convert_audio

        profile = profile or EMPTY_PROFILE
        plan = plan or build_plan(profile, media_type)
        mirror, package = convert_audio(
            path,
            profile=profile,
            plan=plan,
            options=options,
            media_type=media_type,
            artifacts_dir=artifacts_dir or path.parent,
            budget=budget,
        )
        semantic = None
        if stages and plan.runs("transcript_refinement"):
            from .refine import run_refinement

            semantic = run_refinement(render_mirror(mirror), profile=profile, plan=plan)
        return FileConversion(
            mirror,
            media_type,
            METHOD,
            tuple(mirror.header["verify"]),
            plan=plan,
            package=package,
            semantic=semantic,
        )
    return deferred(path, options, media_type, "unsupported-media-type")


def extract_text(path: Path | str, media_type: str | None = None) -> str:
    """The deterministic text of an office document, for a caller re-checking a stored mirror body."""
    path = Path(path)
    if media_type is None:
        media_type, _ = sniff_media_type(path)
    return office.office_text(path, media_type)


def plan_report(
    path: Path | str, profile: Profile, plan: Plan, media_type: str | None = None
) -> dict[str, Any]:
    """What converting this file would run, send and cost. Measures a recording locally; sends nothing."""
    path = Path(path)
    if media_type is None:
        media_type, _ = sniff_media_type(path)
    report: dict[str, Any] = {
        "input": str(path),
        "profile": str(profile.path) if profile.path else None,
        **plan.as_dict(),
    }
    if media_type.startswith(("audio/", "video/")) and plan.runs("transcription"):
        from .audio import audio_estimate, audio_minutes, decide

        decision = decide(path, profile, plan)
        report["decision"] = decision.as_dict()
        report["sends_bytes_off_machine"] = list(decision.cloud_stages)
        report["estimate"] = audio_estimate(profile, decision, audio_minutes(path))
    return report
