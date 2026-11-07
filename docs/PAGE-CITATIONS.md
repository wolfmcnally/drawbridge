# Physical PDF page citations

As of 2026-10-29, this working-tree integration targets independently installed public Vellric 0.2.4, bundle `vellric.document/1.1`, with unchanged PDF behavior identity. It does not add Word pagination, presentation ingestion, image citations or a viewer. Older Vellric bundle envelopes are refused: install the qualified executable and rerun a complete job from the retained original PDF. Existing Drawbridge mirrors without citation metadata remain readable; they do not acquire validated citations retroactively.

## Identity and mapping

A citation binds the SHA-256 of original admitted PDF bytes and its original one-based physical page ordinal. Printed labels, OCR text, rotated/blank/repeated content and searchable/subset derivatives do not replace that identity. Retain the original PDF and verify its digest before attaching a URL; no public URL or absolute file link is invented. Publishing the digest permits correlation against candidate PDFs.

The released [Vellric contract](https://github.com/wolfmcnally/vellric/blob/8b410165a52b246e72dc2ac326ce9e289c80aa43/project/docs/PAGE-CITATIONS.md) defines `vellric-pdf-<64 lowercase hexadecimal SHA-256>-page-<decimal ordinal padded to at least six digits>`, without truncating larger ordinals. Drawbridge independently validates complete ordered pages, source identity, exact anchor equality, job status and every bundle artifact. PDF inspect/convert/render jobs require the closed root `page_citations: {schema: vellric.pdf-page-citations/1.0}`; image jobs forbid PDF-only citation fields. Vellric remains a separately installed AGPL executable; its code and PDF engine are not imported into the MIT runtime.

PDF mirrors retain the original `content_hash`, `page_count`, `unit: page` and the closed `page_citations` object. Separate Drawbridge-owned `pdf_page_map` metadata uses schema `drawbridge.pdf-page-map/1.0`. Its ordered `pages` list has exactly `number`, `anchor`, `start` and `end` per record. `start` is inclusive and `end` exclusive in **Unicode code points** into the normalized mirror body after YAML front matter, not UTF-8 bytes, UTF-16 units or DOM positions. Each span contains that page's presented text, including the existing empty-page notice when needed. Text is normalized for CR/CRLF, NUL removal and edge whitespace before offsets are computed. The original received PDF bytes remain unchanged.

Markers are generated at final assembly: literal `<a id="ANCHOR"></a>` on its own line, a blank line, then `## Page N`. Header-aware parsing validates exact separators, spans, source-derived anchors and complete coverage; it never derives boundaries by searching untrusted text for headings or IDs. `page_sections(body, header=header)` supplies those validated slices. The exported `page_sections(body)` remains a legacy convenience for ordinary old/new Markdown; it cannot establish trustworthy boundaries in adversarial content. Use the header-aware form for new citation-bearing mirrors. `parse_mirror_header` and `render_mirror` validate citation metadata; CLI verification validates it in addition to original digest/size/page count.

Semantic grooming processes only the separately sliced page bodies. Generated markers never enter the annotator; final assembly restores the same destinations and recalculates spans after formatting. Custom OCR backends may omit anchor metadata and retain the original validated inspection mapping; a supplied conflicting map is rejected. A searchable PDF has its own digest and never becomes the source citation target. This mapping asserts identity and framing, not authentication of arbitrary Markdown contents or equivalence to the original PDF's visual presentation.

The generic `sections(body, header=header)` helper also supports the citation map. Its body-only form retains legacy heading-based semantics and must not be used to infer authoritative PDF page boundaries. Citation validation requires canonical preamble and page edges so serialization cannot silently invalidate offsets; structure routing counts mapped physical pages before deciding layout/model work.

## Rendering and sanitization boundary

Combined Markdown is untrusted document presentation. Original page text can include fake headings, raw HTML, unclosed fences and duplicate IDs. Drawbridge preserves that text; emitting anchor bytes does not guarantee that an arbitrary renderer exposes unique clickable destinations. HTML-disabled rendering escapes anchors, sanitizers may strip IDs, and a fence or HTML block can hide later generated markers. No universal renderer, sanitizer, GitHub or browser qualification is claimed.

Consumers needing reliable navigation should validate the mapping, slice page bodies independently, render and sanitize each body under their own policy, remove or namespace untrusted IDs, and insert trusted mapping-derived destinations **outside** those bodies. Do not find authoritative identity by scanning rendered HTML. Preserve the original PDF for visual verification and qualify any viewer-specific `#page=N` URL behavior separately. Drawbridge does not implement that HTML pipeline or install a renderer/sanitizer dependency.

## Selected released artifacts

- Public Vellric v0.2.4 source/tag: `8b410165a52b246e72dc2ac326ce9e289c80aa43`.
- Wheel `vellric-0.2.4-py3-none-any.whl`, 468498 bytes, SHA-256 `0799e067048b5ca34e5e68b088f976e3e2cc08bf84d1c9458d423f9a51d8cfc0`.
- Source archive `vellric-0.2.4.tar.gz`, 2333950 bytes, SHA-256 `d10f806079f04e4a984781036f3f36c99a962409d96188af342d3ab1cdaa6f63`.

Select the trusted independently installed executable through `DRAWBRIDGE_VELLRIC`. Registry requirements come from the matching released source lock with hashes; the unchanged exact public Conric source remains separately pinned. Doctor/schema/behavior checks and complete-job validation still apply. This integration grants no provider access or credential forwarding; cloud-vision acceptance remains outside its qualification. Public Drawbridge release/push is not authorized by this integration alone.
