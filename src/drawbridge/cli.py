"""Command-line interface.

Exit codes:
  0  success
  2  usage error
  3  blocked: the input is inherently unprocessable (password, no pages)
  4  failed: the input is not a readable PDF
  5  operational: OCR tooling unavailable or the conversion could not complete
  6  verify: the mirror does not match the PDF
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .convert import ConversionOptions
from .documents import convert_file, plan_report
from .errors import (
    ConversionOperationalError,
    ConverterUnavailable,
    DrawbridgeError,
    MediaTypeError,
    MirrorFormatError,
    OcrOperationalError,
    blocked_reason,
)
from .identify import identify, sniff_media_type
from .mirror import page_sections, parse_mirror_header, render_mirror, sha256_file
from .ocr import CliOcrBackend
from .pdf_tools import (
    MalformedPdfError,
    PdfOpenOperationalError,
    PdfReadOperationalError,
    ocr_page_numbers,
)
from .profile import EgressRefused, ProfileError, build_plan, resolve_profile

EXIT_OK, EXIT_USAGE, EXIT_BLOCKED, EXIT_FAILED, EXIT_OPERATIONAL, EXIT_VERIFY = 0, 2, 3, 4, 5, 6


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def _exit_code_for(exc: DrawbridgeError) -> int:
    if blocked_reason(exc) is not None:
        return EXIT_BLOCKED
    if isinstance(exc, (MalformedPdfError, PdfReadOperationalError, PdfOpenOperationalError, MediaTypeError)):
        return EXIT_FAILED
    return EXIT_OPERATIONAL


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="drawbridge", description="Any file in, one provenance-headed Markdown mirror out.")
    parser.add_argument("--version", action="version", version=f"drawbridge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser("convert", help="convert one file of any supported type to a provenance-headed Markdown mirror")
    convert.add_argument("pdf", metavar="file", type=Path)
    convert.add_argument("-o", "--out", type=Path, help="output path (default: <input name>.md beside the input)")
    convert.add_argument("--stdout", action="store_true", help="write the mirror to standard output instead of a file")
    convert.add_argument("--title", help="H1 for the body (default: derived from the filename)")
    convert.add_argument("--mirror-of", help="identity recorded in the header (default: the filename)")
    convert.add_argument("--acquired-from", help="provenance recorded in the header (default: the input path)")
    convert.add_argument("--acquired-at", help="ISO-8601 acquisition timestamp (default: now)")
    convert.add_argument("--no-ocr", action="store_true", help="refuse documents with scan-like pages instead of running OCR")
    convert.add_argument("--skip-preflight", action="store_true", help="skip the ocrmypdf preflight and recognise pages directly")
    convert.add_argument("--searchable-pdf", type=Path, help="keep the ocrmypdf derivative here (implies preflight)")
    convert.add_argument("--tessdata-dir", type=Path, help="explicit trusted Tesseract language-data directory")
    convert.add_argument("--lang", help="Tesseract language code(s), e.g. eng or eng+deu")
    convert.add_argument("--dpi", type=int, default=300, help="render resolution for recognition (default 300)")
    convert.add_argument("--workers", type=int, default=1, help="documents you intend to process concurrently; bounds per-document OCR jobs")
    convert.add_argument("--raster-threshold", type=float, default=0.5, help="image coverage at which a page counts as a scan (default 0.5)")
    convert.add_argument("--json", action="store_true", help="print a JSON summary instead of prose")
    convert.add_argument("--profile", type=Path, help="profile that enables networked and model stages")
    convert.add_argument("--no-profile", action="store_true", help="ignore every profile; run the local pipeline only")
    convert.add_argument("--stages", help="comma-separated stages to run; others in the profile are skipped")
    convert.add_argument("--skip", help="comma-separated stages to skip")
    convert.add_argument("--no-ai", action="store_true", help="run no stage that uses an endpoint")
    convert.add_argument("--local-only", action="store_true", help="refuse any stage whose endpoint declares egress: cloud")
    convert.add_argument("--dry-run", action="store_true", help="print the resolved plan and exit: no calls, no writes")
    convert.add_argument("--artifacts-dir", type=Path, help="where a transcription package is kept (default: beside the input)")

    profile = sub.add_parser("profile", help="show or check the resolved profile; secrets are never printed")
    profile.add_argument("action", choices=["show", "check"])
    profile.add_argument("--profile", type=Path)

    speakers = sub.add_parser("speakers", help="name the speakers of an audio mirror and render it again")
    speakers.add_argument("mirror", type=Path)
    speakers.add_argument("--package", type=Path, help="transcription package (default: the one the mirror names, beside it)")
    speakers.add_argument("assignments", nargs="*", metavar="ID=NAME", help="the same NAME may be given to several identities")
    speakers.add_argument("--clear", action="append", default=[], metavar="ID")

    inspect = sub.add_parser("inspect", help="report identification and OCR page selection as JSON")
    inspect.add_argument("pdf", type=Path)
    inspect.add_argument("--page-texts", action="store_true", help="include every page's native text")
    inspect.add_argument("--raster-threshold", type=float, default=0.5)

    verify = sub.add_parser("verify", help="check that a mirror matches its PDF")
    verify.add_argument("mirror", type=Path)
    verify.add_argument("--pdf", type=Path, required=True)
    return parser


def _cmd_convert(args: argparse.Namespace) -> int:
    if args.searchable_pdf is not None and args.skip_preflight:
        print("error: --searchable-pdf requires the preflight; drop --skip-preflight", file=sys.stderr)
        return EXIT_USAGE
    ocr = None
    if not args.no_ocr:
        ocr = CliOcrBackend(
            document_workers=args.workers,
            preflight=not args.skip_preflight,
            searchable_pdf=args.searchable_pdf,
            dpi=args.dpi,
            language=args.lang, tessdata_dir=args.tessdata_dir,
        )
    try:
        active = resolve_profile(args.profile, no_profile=args.no_profile)
        media_type, _ = sniff_media_type(args.pdf)
        split = lambda value: [item.strip() for item in value.split(",") if item.strip()] if value else None  # noqa: E731
        plan = build_plan(active, media_type, only=split(args.stages), skip=split(args.skip) or (), no_ai=args.no_ai, local_only=args.local_only)
    except EgressRefused as exc:
        print(json.dumps({"outcome": "refused", "message": str(exc), "plan": exc.plan.as_dict()}) if args.json else f"refused: {exc}", file=sys.stdout if args.json else sys.stderr)
        return EXIT_USAGE
    except (ProfileError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.dry_run:
        print(json.dumps(plan_report(args.pdf, active, plan, media_type), indent=2))  # a recording is measured locally; nothing is sent
        return EXIT_OK
    options = ConversionOptions(
        title=args.title,
        mirror_of=args.mirror_of,
        acquired_at=args.acquired_at,
        acquired_from=args.acquired_from,
        raster_threshold=args.raster_threshold,
    )
    try:
        result = convert_file(args.pdf, ocr=ocr, options=options, media_type=media_type, profile=active, plan=plan, artifacts_dir=args.artifacts_dir)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except DrawbridgeError as exc:
        code = _exit_code_for(exc)
        label = {EXIT_BLOCKED: "blocked", EXIT_FAILED: "failed", EXIT_OPERATIONAL: "operational"}[code]
        reason = blocked_reason(exc)
        if args.json:
            print(json.dumps({"outcome": label, "reason": reason, "error": type(exc).__name__, "message": str(exc)}))
        else:
            detail = f" ({reason})" if reason else ""
            print(f"{label}{detail}: {exc}", file=sys.stderr)
        return code
    rendered = render_mirror(result.mirror)
    out: Path | None = None
    if args.stdout:
        sys.stdout.write(rendered)
    else:
        # The whole input name is kept, so report.pdf and report.docx cannot collide on report.md.
        out = args.out or (args.pdf.with_suffix(".md") if result.pdf else args.pdf.with_name(args.pdf.name + ".md"))
        _atomic_write_text(out, rendered)
    semantic_out: Path | None = None
    if result.semantic is not None and out is not None:
        semantic_out = out.with_name(out.name.removesuffix(".md") + ".semantic.md")
        _atomic_write_text(semantic_out, render_mirror(result.semantic))
    summary = {
        "outcome": "ok",
        "input": str(args.pdf),
        "output": str(out) if out else None,
        "content_hash": result.mirror.header["content_hash"],
        "media_type": result.media_type,
        "unit": result.mirror.header["unit"],
        "method": result.method,
        "verify": list(result.mirror.header["verify"]),
        "semantic_output": str(semantic_out) if semantic_out else None,
    }
    if result.pdf:
        summary.update(
            page_count=result.pdf.page_count,
            ocr_pages=list(result.pdf.selected_pages),
            rotations={page.page: page.rotation for page in result.pdf.recovered},
            searchable_pdf=str(result.pdf.searchable_pdf) if result.pdf.searchable_pdf else None,
        )
    if args.json:
        print(json.dumps(summary))
    elif not args.stdout:
        if result.pdf:
            ocr_note = f", OCR on pages {summary['ocr_pages']}" if result.pdf.selected_pages else ""
            print(f"wrote {out}: {result.pdf.page_count} pages, method {result.method}{ocr_note}")
        else:
            flags = f", verify {summary['verify']}" if summary["verify"] else ""
            print(f"wrote {out}: {result.media_type}, method {result.method}{flags}")
    return EXIT_OK


def _cmd_profile(args: argparse.Namespace) -> int:
    try:
        active = resolve_profile(args.profile)
    except (ProfileError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    shown = active.redacted()
    if args.action == "check":
        unset = sorted(name for name, endpoint in shown["endpoints"].items() if endpoint["api_key_set"] is False)
        shown = {"path": shown["path"], "valid": True, "stages": list(shown["stages"]), "endpoints_without_a_key": unset}
        print(json.dumps(shown, indent=2))
        return EXIT_OK if not unset else EXIT_USAGE
    print(json.dumps(shown, indent=2))
    return EXIT_OK


def _cmd_speakers(args: argparse.Namespace) -> int:
    from .audio import rerender
    from .mirror import parse_mirror_header

    try:
        import transcribe
    except ImportError:
        print("operational: naming speakers needs the transcribe package: install drawbridge[audio]", file=sys.stderr)
        return EXIT_OPERATIONAL
    try:
        header, _ = parse_mirror_header(args.mirror)
        package_dir = args.package or args.mirror.parent / str(header.get("transcription_package", ""))
        package = transcribe.Package.load(package_dir)
        names: dict[str, str | None] = {}
        for item in args.assignments:
            identity, separator, name = item.partition("=")
            if not separator or not identity.strip():
                raise ValueError(f"an assignment must look like ID=NAME: {item!r}")
            names[identity.strip()] = name
        names.update({identity: None for identity in args.clear})
        if names:
            package.assign(names)
            _atomic_write_text(args.mirror, rerender(args.mirror, package_dir))
        for row in package.speakers["speakers"]:
            print(f"{row['id']}\t{row.get('name') or ''}\t{row['turns']} turns")
    except (DrawbridgeError, transcribe.PackageError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


def _cmd_inspect(args: argparse.Namespace) -> int:
    ident = identify(args.pdf)
    data = ident.as_dict(include_page_texts=args.page_texts)
    if ident.processable:
        try:
            data["ocr_pages"] = ocr_page_numbers(
                args.pdf, raster_threshold=args.raster_threshold, inspection=ident.inspection
            )
        except DrawbridgeError as exc:
            data["ocr_pages"] = None
            data["ocr_selection_error"] = str(exc)
    print(json.dumps(data, indent=2))
    return {"processable": EXIT_OK, "blocked": EXIT_BLOCKED, "failed": EXIT_FAILED}[ident.outcome]


def _cmd_verify(args: argparse.Namespace) -> int:
    problems: list[str] = []
    try:
        header, body = parse_mirror_header(args.mirror)
    except (OSError, MirrorFormatError) as exc:
        print(f"verify: {exc}", file=sys.stderr)
        return EXIT_VERIFY
    if not args.pdf.is_file():
        print(f"verify: PDF not found: {args.pdf}", file=sys.stderr)
        return EXIT_VERIFY
    if header.get("content_hash") != sha256_file(args.pdf):
        problems.append("content_hash differs from the PDF")
    if header.get("byte_size") != args.pdf.stat().st_size:
        problems.append("byte_size differs from the PDF")
    ident = identify(args.pdf)
    page_count = ident.inspection.page_count if ident.inspection else None
    try:
        sections = page_sections(body)
    except MirrorFormatError as exc:
        problems.append(str(exc))
        sections = []
    if page_count is not None and len(sections) != page_count:
        problems.append(f"mirror has {len(sections)} page sections; PDF has {page_count} pages")
    declared = header.get("page_count")
    if declared is not None and declared != len(sections):
        problems.append(f"header declares {declared} pages; body has {len(sections)} sections")
    if problems:
        for problem in problems:
            print(f"verify: {problem}", file=sys.stderr)
        return EXIT_VERIFY
    print(f"ok: {args.mirror} matches {args.pdf} ({len(sections)} pages)")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "convert":
            return _cmd_convert(args)
        if args.command == "inspect":
            return _cmd_inspect(args)
        if args.command == "verify":
            return _cmd_verify(args)
        if args.command == "profile":
            return _cmd_profile(args)
        if args.command == "speakers":
            return _cmd_speakers(args)
    except ConverterUnavailable as exc:
        print(f"operational: {exc}", file=sys.stderr)
        return EXIT_OPERATIONAL
    except (OcrOperationalError, ConversionOperationalError) as exc:
        print(f"operational: {exc}", file=sys.stderr)
        return EXIT_OPERATIONAL
    parser.error("unknown command")
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
