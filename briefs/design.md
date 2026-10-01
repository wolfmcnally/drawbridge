---
title: drawbridge design: the PDF-to-Markdown mirror pipeline
date: 2026-09-14
status: reference
scope: |
  Why drawbridge is built the way it is. Covers content-based identification, the complete-or-refuse PDF inspection, per-page OCR selection, the OCR branch with four-rotation orientation recovery, the mirror header and body contract, the failure taxonomy that lets a batch caller isolate one bad document, and the concurrency budget. Anything downstream of the written mirror is out of scope.
---

# drawbridge design: the PDF-to-Markdown mirror pipeline

## The problem

Document collections of unknown provenance arrive as `.pdf`: born-digital exports, photographed paper, faxed and re-scanned typewritten pages. The extension says nothing about what is inside. drawbridge carries one such file to the point where it has a Markdown *mirror*: a plain-text twin, one section per original page, with a YAML header that records which method produced it and against which immutable bytes. A downstream consumer reads the mirror and its header and never re-reads the PDF for text.

The mirror is a fidelity artifact, not a semantic rendering. Headings, lists, tables, links and columns are deliberately not reconstructed: every such reconstruction is a heuristic that can misfire, and the mirror body is meant to be exact retained bytes that can be cited by page.

## The four commitments

1. **Received bytes are evidence, never working material.** The original PDF is hashed and never rewritten. OCR runs on a disposable derivative in a temp directory; the orientation pass renders page images from the original without touching it. Tests assert the input bytes are unchanged after conversion.
2. **Content is the authority; names are claims.** The media type is sniffed from bytes. No stage consults a filename suffix. A PDF with no extension is a PDF; a text file named `.pdf` is refused.
3. **Extraction beats recognition, page by page.** A page with a real text layer that is not a page-sized raster keeps its native text character for character. Only scan-like pages go to OCR. The document-level method label still records that OCR was involved, and the header lists exactly which pages.
4. **Fail closed, and say why.** A PDF whose pages cannot all be traversed fails entirely; there is no "most of the pages" result. Inherent defects (password, zero pages) become a terminal `blocked` outcome. Operational problems (missing binary, unreadable file) become `failed`, retryable, and never masquerade as "this document had no text".

## The walk

```text
identify        media type from bytes · full PyMuPDF traversal · one page_texts tuple
                → processable | blocked(password-protected, degenerate-input) | failed(code)
    ↓
select          per page: no text, or raster coverage ≥ threshold → OCR candidate
    ↓
recognise       optional ocrmypdf preflight on a disposable copy of the selected pages
                then, per selected page: render at 300 DPI × 4 rotations → tesseract → best score
    ↓
assemble        native pages exact · recognised pages replaced · count must match
    ↓
mirror          YAML header + "# Title" + one "## Page N" section per page
```

## Identify (`identify.py`, `pdf_tools.py`)

`sniff_media_type` runs `file --mime-type --brief` when libmagic is available and otherwise looks for `%PDF-` within the first 1024 bytes, which is the same tolerance the PDF specification and libmagic allow. Degraded detection is recorded as a flag, never silently.

`page_texts` performs the single complete traversal. The exception mapping is the heart of the fail-closed design:

| Condition | Raised | Identify outcome |
|---|---|---|
| `EmptyFileError`, `FileDataError`, `ValueError` on open | `MalformedPdfError` | `failed` / `malformed-pdf` |
| `OSError` on open | `PdfOpenOperationalError` | `failed` / `pdf-open-operational` |
| needs a password and the empty password fails | `EncryptedPdfError` (inherent) | `blocked` / `password-protected` |
| zero pages | `DegeneratePdfError` (inherent) | `blocked` / `degenerate-input` |
| error mid-traversal, or fewer pages than `page_count` | `PdfReadOperationalError` | `failed` / `pdf-read-operational` |
| PyMuPDF not importable | `ConverterUnavailable` | `failed` / `pdf-open-operational` |

An encrypted PDF *opens* successfully, so open-time guards never fire for it; the `needs_pass` check exists because the failure otherwise surfaces later, on page access, as a bare `ValueError`. A permissions-only PDF has an empty user password, authenticates, and reads normally.

The result is a frozen `PdfInspection` carrying exactly `page_count` strings. `identify()` never raises for a document condition; it returns an `IdentifyResult` whose `raise_for_outcome()` reconstructs the typed error when a caller wants one.

## Page selection (`ocr_page_numbers`)

Each page is judged independently. A page is selected when its extracted text is empty after stripping, **or** when the union of its image bounding boxes clipped to the page covers at least `raster_threshold` (default 0.5) of the page area. The second rule is a scan proxy: it catches scans that already carry an old, possibly wrong OCR layer, which would otherwise count as "has text". Small logos do not force native text through OCR. A large decorative raster background over-selects; the cost is CPU, not content, because rendering the page still preserves its visible text.

## The OCR branch (`ocr.py`, `orientation.py`)

**Preflight (optional, default on).** `ocrmypdf` runs on a disposable copy with `--pages <selected>`, `--force-ocr` (replace any stale layer), `--rotate-pages --rotate-pages-threshold 2` (dense typewritten pages score low orientation confidence and would otherwise be left sideways under the default), `--invalidate-digital-signatures` (only the derivative changes), `--jobs N`, and `OMP_THREAD_LIMIT=1`. The derivative's page count must equal the original's. Its recognised text is **not** used for the mirror; the preflight proves the document is OCR-able, and its output can be kept as a searchable PDF. `--skip-preflight` removes this step entirely.

**Recovery (always).** For each selected page, `recover_page` renders the original at 300 DPI in all four right-angle rotations, runs `tesseract --psm 3 tsv` on each, and scores each result by summing, over word-level rows, alphanumeric characters × max(0, confidence − 50). The best rotation's words, regrouped by block/paragraph/line, become the page text; a best score of zero yields an empty page, which the mirror marks explicitly. Every page is checked at all four angles because orientation detectors can be confidently wrong. Malformed TSV raises rather than scoring zero, so tool breakage is not mistaken for a blank page. A page whose rendering would pass 30,000 pixels on its longer side (Tesseract refuses 32,767, and PyMuPDF a pixmap over about two gigabytes) is handled differently: too wide, it renders at a lower resolution; too long, as a full-length screenshot of a web page is, it is read in bands 8,000 pixels tall. Each cut falls on the quietest row in the last quarter of its band's allowance, a blank row between lines wherever the page has one. The four rotations are compared on the first band, the others are read at the winner, and their texts are joined in page order. `ocr_pages` then records `bands` for that page.

**Assembly.** Selected pages are replaced by recovered text; unselected pages keep their identified native text exactly. The result must have exactly one string per page.

## Concurrency

Documents may be processed concurrently by `W` workers while each OCR subprocess parallelises internally. `ocr_jobs_for(W, C)` gives each preflight `max(1, C // min(W, C))` jobs for `C` cores. One `OcrCapacity(C)` pool, shared by every backend in a process, is reserved for `ocr_jobs` tokens per preflight and one token per recovered page; with `OMP_THREAD_LIMIT=1` on every subprocess, recognition threads never exceed `C`.

## The mirror contract (`mirror.py`)

**Header.** Required fields: `mirror_of`, `content_hash` (`sha256:` of the input), `media_type`, `byte_size`, `acquired_at`, `acquisition_method`, `acquired_from`, `processing` (a list of `{seq, method, performed_at, agent}`), `verify` (sorted, de-duplicated flags), `generated_by`. drawbridge adds `page_count` and `ocr_pages` (each `{page, rotation, score}`, plus `bands` for a page read in bands). `method` is `pymupdf-text` when no page was selected and `ocr` when any page was.

**Body.** An H1, then one `## Page N` section per original page, always. An empty page is kept and marked `[No text recovered from this page; check the original.]`, so page numbers in the mirror are page numbers in the PDF.

**Render and parse.** `render_mirror` emits YAML front matter, the body with trailing whitespace stripped, a final newline, and strips NUL bytes. `parse_mirror_header` normalises line endings, requires the fence and every required field, and returns `(header, body)`. `page_sections` recovers the per-page texts and refuses out-of-order sections. `mirror_text` is the normalised reading view of retained bytes.

## Failure taxonomy (`errors.py`)

Every document-local problem is a `DrawbridgeError`. `blocked_reason(exc)` maps only the explicit inherent hierarchy (`EncryptedPdfError`, `DegeneratePdfError`) to `password-protected` / `degenerate-input`; everything else is retryable. A batch caller should treat `blocked` as terminal but keyed by content hash so the same bytes can be re-admitted if the blocker lifts, and `failed` as a candidate for retry after repair.

The rule for anyone extending a converter: a new failure mode is not complete until its exception type is in the classification. A leaf `raise` of an unclassified type inherits the caller's fail-wide default.

| Symptom | Type | CLI exit | Retry helps? |
|---|---|---|---|
| Password required | `EncryptedPdfError` | 3 | Only with the password |
| Zero pages | `DegeneratePdfError` | 3 | No |
| Corrupt bytes, traversal incomplete, not a PDF | `MalformedPdfError`, `PdfReadOperationalError`, `MediaTypeError` | 4 | Needs a replacement file |
| PyMuPDF missing, file unopenable | `ConverterUnavailable`, `PdfOpenOperationalError` | 4 or 5 | After fixing the environment |
| `ocrmypdf` / `tesseract` missing or timed out | `OcrOperationalError` | 5 | Yes |
| Preflight refusal, page-count drift, incomplete page sequence, no backend for scan pages | `OcrPreflightError`, `ConversionOperationalError` | 5 | Yes |

## Known limits

- **No structure recovery.** Multi-column pages come out in PyMuPDF block order; OCR pages are line-grouped by Tesseract.
- **The raster-coverage proxy over-selects** pages with a large decorative background image.
- **The method label is document-level** (`ocr` for a 200-page native PDF with one scanned insert); `ocr_pages` carries the per-page truth.
- **The preflight's own text is discarded.** If ocrmypdf's deskew and cleanup were ever wanted in the mirror, that is a design change.
- **Everything runs locally.** No page image or text leaves the machine. Tooling: PyMuPDF (library), `ocrmypdf`, `tesseract`, `file(1)`.

## Reading order

1. `pdf_tools.page_texts` and `ocr_page_numbers`: the inspection contract and the selection proxy.
2. `ocr.CliOcrBackend.extract`, `OcrCapacity`, `ocr_jobs_for`.
3. `orientation.recover_page` and `tsv_text_and_score`.
4. `mirror.build_header`, `page_body`, `render_mirror`, `parse_mirror_header`.
5. `convert.convert_pdf`, then `cli.py`.
6. `tests/test_live.py` for the whole contract exercised against real OCR.
