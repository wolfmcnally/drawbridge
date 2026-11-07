---
title: "drawbridge: citable page numbers for Word documents"
date: 2026-10-29
status: proposal
scope: |
  Researches truthful page citations for Word inputs: actual layout versus stored breaks/counts, retained renderings, stable anchors, renderer alternatives, licensing, security, provenance and qualification. Does not implement pagination, install a renderer, ingest documents or establish production fidelity.
---

# Citable page numbers for Word documents

## Recommendation

Make a page citation refer to **a specific retained PDF rendition of specific Word bytes**, not to a guessed location in flowing XML. Keep today's native Word text mirror available and unchanged by default. Add an explicit paginated-rendition mode only after its renderer, provenance and compatibility contract qualify.

Prefer a supplied authoritative PDF when its association with the Word edition is established; otherwise qualify **LibreOffice Writer 26.8.1** as the first local external rendering candidate. Feed the resulting PDF through the existing independently installed Vellric CLI. Record that these are pages of the named Writer rendition, not guaranteed pages of every Microsoft Word installation. When exact author-visible Word pagination is required, require the corresponding author/exported PDF or a qualified, licensed Word export; do not silently substitute Writer layout.

This is an engineering recommendation, not a measured fidelity claim. **As of 2026-10-29; sources retrieved 2026-10-29.** No Word file was rendered in this research. See the [PowerPoint brief](powerpoint-ingestion.md) for the related optional Office-renderer boundary.

## Current architecture and the missing evidence

In this checkout, `office.docx_text` reads paragraph text from `word/document.xml` with ZIP/XML facilities. It treats line/page-break elements as newlines; it does not lay out a document or produce physical page assignments. The binary `.doc` reader is a bounded Word97 main-story piece-table reader, explicitly excluding header and footnote stories. `documents._docx` and `_doc` emit `unit=document`, with methods `docx-xml-extract` and `word97-piece-table`. They do not already support citable pages.

`mirror.py` already supports `unit=page`, page sections and immutable source hashes. PDF completeness, parsing and OCR belong to the independent Vellric CLI, not a runtime Python import. A proposed Word renderer should create a derivative and reuse that boundary; it should not make the Word XML walker infer PDF geometry, change the original bytes, or repurpose the current `.pdf` result as though the original input were a PDF. The exact new CLI/API and provenance fields remain future design work.

## What is and is not a page

| Evidence | What it establishes | What it cannot establish |
|---|---|---|
| Explicit `w:br` page break, paragraph page-break-before, or section properties | Authored layout constraints and candidate boundaries | All automatic overflow boundaries, physical page count or text-to-page mapping. Odd/even sections may introduce blank pages. |
| `w:lastRenderedPageBreak` | A saved pagination marker from an application that previously laid out the file [W1] | Current pagination under different fonts/settings, marker completeness, or an independently verified edition. |
| `docProps/app.xml` page count or a `NUMPAGES` field result | Stored count/field information | The page containing a quotation; a fresh total still contains no per-span map. Treat unvalidated stored values as hints. |
| Header/footer `PAGE` fields or printed numbers | Labels produced under a numbering policy | Unique physical indices: sections may restart numbering or use Roman numerals. |
| Paragraph order, word counts, heading structure | Logical/source locations | Physical page boundaries. A paragraph or table row can span multiple pages. |
| Complete retained PDF plus its hash and validated page sequence | Physical pages of that exact rendition | Layout identity with another renderer, later edit or unverified authoring environment. |

python-docx 1.2.0 documents that it does not render; its rendered-break objects reflect Word's saved pagination. Its convenience paragraph fragments can even move a break that occurs inside a hyperlink [W2]. Consequently neither adding python-docx nor counting its break objects produces an authoritative current page map. A text-only converter must continue to say that page numbers are unavailable rather than manufacture them.

## The citation contract

The minimum proposed citation identity is `(Word source hash, retained PDF hash, one-based physical PDF page index)`. Add a quoted span and, where available, its rectangle or a disambiguated text anchor within that PDF page. Keep any printed page label separately, with its source; a label is not a substitute for the physical index. Cite “page 7 of the recorded rendition,” not an unsupported universal “Word page 7.”

Preserve a source identity for the native Word content too. Existing bookmarks and optional `w14:paraId` identifiers can help locate source paragraphs; Microsoft documents `paraId` for Office 2010 onward [W3]. They are not guaranteed present, unique across edits or sufficient for pagination. A proposed fallback is a package-part plus structural ordinal/path and quote hash, all bound to the original file hash. For legacy binary Word, use a separately qualified main-story location scheme rather than invent XML IDs.

Mapping a Word paragraph to a rendered page is a different claim from knowing the PDF's page index. Do not assign page numbers to native paragraphs by nearest text match or XML order. Repeated headers, duplicated quotations, fields, tracked changes, footnotes, tables, ligatures and hyphenation can make alignment ambiguous. The first useful delivery can provide PDF-page citations without promising a source-paragraph-to-page map. An optional later alignment map must carry confidence/ambiguity and allow a paragraph to span several pages; unmatched or ambiguous spans remain unresolved.

The retained rendition is the durable evidence. Re-rendering is not how a citation is resolved. New source bytes, renderer/font settings or different PDF bytes establish a new rendition identity; never silently reuse old page locators. Fixing a random seed or pinning a version alone does not prove identical layout or byte output.

## Proposed bounded workflow

1. Preserve and hash the received `.docx` or qualified `.doc`; identify its actual container/content type. Keep the existing native extraction result as a separate artifact. Macro-enabled templates, encryption, rights management and unsupported binary versions need explicit admission decisions, not hidden conversion retries.
2. If a PDF is supplied, hash it and establish its relationship to the Word edition through trusted conversion evidence or explicit supplied-edition metadata. Similar filenames or similar text are insufficient proof. Without that relationship it can still be cited as its own supplied PDF, but not falsely attributed as a proven conversion of the Word file.
3. Otherwise render a read-only disposable copy with one explicitly selected, qualified local renderer and a fresh per-job profile/workspace. Pin a complete rendering profile and reject unsupported or incomplete output. Do not save changes back to the Word source.
4. Retain the actual PDF and conversion receipt in caller-approved artifact storage, rather than leave the only citation target in a temporary directory. Validate nonempty output, expected media type, complete traversal, actual page count and source/rendition association. Process the derivative with Vellric's existing expected-input-hash, CPU/resource-grant and terminal/exit/bundle checks.
5. Build one page section per physical PDF page, including blank pages. Bind the outer record to the original Word hash and the inner PDF processing record to the PDF hash; retain Vellric's processing fingerprint separately from the Office renderer's identity. A transient Vellric bundle is not itself a persistent citation store.
6. Bind any quoted span to retained page text or an explicitly labelled OCR result. Preserve visual access to the cited page. Do not silently mix original Word XML text with rendered-page boundaries when the two disagree. A semantic rendering remains derived material, not the citation authority.

If rendering is unavailable or fails, retain a truthful document-level result with an explicit “pagination unavailable” outcome, or fail the requested paginated mode. Never substitute cached counts, estimated words per page or explicit-break counts as successful pagination. Operational renderer failures must remain distinguishable from inherent password/protection blocks and unsupported profiles.

## Choose the rendering profile explicitly

Record renderer product, full build and executable/package identity; OS/architecture or container image identity; export filter/options; page geometry; locale/timezone; font files/versions/hashes and actual substitutions; hyphenation/language resources; and the output PDF hash. A renderer upgrade creates a new cache identity even if the document is unchanged. Preserve settings sufficient to investigate the result, without leaking credentials or private host paths into public logs.

Fix the revision view (for example, final text without markup), comments/balloons, hidden text, fields/links, numbering and automatically inserted blank-page policy. Defaults are not interchangeable across engines. Decide how volatile fields such as dates are handled; do not refresh external data or normalize them silently. LibreOffice exposes a Writer empty-page suppression setting, so preserve blank pages deliberately for the canonical rendition [W4]. Microsoft Word's PDF API exposes markup, bookmarks and font handling; font embedding restrictions can affect whether text remains extractable [W5]. These choices belong in the receipt and visual acceptance tests.

An approved font set must have actual deployment and embedding rights. The existence of fonts on an author's computer is not redistribution permission. Record substitutions and block or explicitly classify degraded fidelity where a required font is unavailable. Pinning fonts and locale reduces drift but does not prove Word-equivalent layout. Preserve the PDF precisely because later systems may paginate differently.

## Dependency alternatives and decisions

The table records researched candidates, not installed dependencies or approved production pins.

| Option | Version/interface evidence | Licensing and requirements | Fit and decision |
|---|---|---|---|
| Supplied authoritative PDF | Exact source/renderer/edition when available | No new renderer dependency; permission to retain source, PDF and fonts still matters. | Preferred when the desired published/author-visible pagination already exists and association is established. |
| LibreOffice Writer | 26.8.1 current branch, dated 2026-10-08; 26.2.6 previous mature branch, dated 2026-09-24 [W6] | MPL-2.0 distribution with component-specific licenses; external suite and font inventory [W7]. Headless conversion and separate writable profiles documented [W8]. | Recommended first local qualification candidate: pin a specific 26.8.1 build and artifacts; compare the mature branch if regression evidence requires it. Does not require Office or cloud service. |
| Microsoft Word export | Microsoft 365/Word 2024 product family; actual build/channel must be captured, not “latest Word.” `Repaginate` and `ExportAsFixedFormat` are documented APIs [W5, W9]. | Proprietary application/license and host requirements; interactive author export is different from unattended automation. | Best source for a required Word-specific edition. Do not make unattended desktop COM/Office automation the default worker: Microsoft does not recommend or support unattended noninteractive Office automation [W10]. |
| Aspose.Words for Python via .NET | 26.10 release line, supported by vendor release notes [W11] | Commercial/proprietary license; fonts and native/runtime prerequisites require platform checks. Trial output is watermarked and paragraph-limited [W12, W13]. | Possible paid local renderer if Writer fidelity is insufficient. Vendor describes its own layout engine [W14]; Word similarity is a vendor claim, not proven equivalence. Do not adopt without a licensed representative evaluation. |
| python-docx / OOXML SDK / direct XML | python-docx 1.2.0, MIT; existing native parser already present [W2, W15] | Structural parsing, not a layout engine. Additional parser dependencies if introduced. | Useful for structural anchors or richer extraction; not needed merely to obtain rendered pages and not the pagination solution. |
| Microsoft Graph | v1.0 PDF conversion; documented DOC/DOCX support and a 2 MB format-conversion limit at retrieval [W16] | Cloud/tenant storage, service authorization and egress; service renderer cannot be pinned like a local executable. | Explicit future cloud alternative only. Keep the actual returned PDF if used; do not imply its pagination equals desktop Word or enable it under local-only operation. |

Keep heavy Office rendering outside Drawbridge's Python core. A controlled external adapter to a trusted executable is proportionate and consistent with the current replaceable PDF boundary; creating another repository/service or adopting a large orchestration stack is not required by this recommendation. Share an optional renderer capability with presentation rendering only if later qualification supports both. Do not put Word rendering into Vellric merely because Vellric processes the resulting PDF.

The current checkout targets independently installed Vellric 0.2.2 and public MIT Conric 0.1.0; those are the inspected integration baseline, not a claim that they are the newest upstream releases. No new PDF library import, provider schema duplication or credential forwarding is proposed. Future configuration belongs in the established explicit/typed Drawbridge policy, preserving CLI precedence, local-only/no-AI gating and per-call privacy; no new flags or schema are implemented by this brief.

Vellric is AGPL-3.0-only, independently installed under the existing [licensing contract](../docs/LICENSING.md). Drawbridge's MIT grant does not relicense that executable, LibreOffice, commercial alternatives or font assets. Review the exact distributed or hosted component arrangement before implementation packaging; external process isolation is not a blanket license exemption.

## Security and provenance before deployment

Rendering a document is an attack surface even with macros disabled. LibreOffice's advisories retrieved here include file-write and external-data access issues fixed in 26.2.5/26.8.0 [W17]. The proposed versions are beyond those stated fixes; that is not a vulnerability-free certification. Check all current advisories and exact artifact provenance again at implementation/release time. Verify official checksums/signatures, retain notices and an SBOM, and do not use an unmaintained branch just because its layout was once convenient.

Require OS-enforced filesystem/network isolation, read-only source access, bounded CPU/memory/disk/output/pages/deadline, a private writable profile and process cleanup. Deny macros, extensions and external link/data updates before load; never inherit the operator's trusted profile, keys, network sessions or unrestricted home directory. `--headless` and a timeout do not establish these protections. Python's XML/ZIP warnings also apply to any added source-anchor parser [W18, W19]. No secret, license key or private document should enter diagnostics or research services.

No supplied document, renderer, font or commercial license was installed or exercised for this research. An implementation must independently prove local policy and the complete output contract; a zero process exit or cached page count is not enough.

## Acceptance evidence for the later implementation

Build synthetic Word fixtures with overflow without explicit breaks, manual breaks, odd/even sections, blank pages, restarted/Roman numbering, headers/footers, footnotes/endnotes, floating images/text boxes, multi-page tables, repeated quotations, hyperlinks spanning breaks, fields and tracked changes. Add missing/substituted fonts, CJK/RTL layout, corrupted packages, stale/missing saved page markers and misleading cached counts. Include qualified Word97 cases separately from newer/unsupported binary versions.

Compare actual PDFs and page maps against selected reference exports, with a licensed font manifest. Test that changing fonts, revision view, renderer build or source bytes creates a new rendition identity. Prove that every page remains represented, source bytes never change, citation locators resolve to the retained page, ambiguous paragraph alignment remains unresolved, and missing tooling cannot emit fabricated pages. Verify persistence after temp cleanup, hash mismatch/corrupt derivative refusal, CLI/API parity, resource grants, no network/macros and existing mirror/Word regression goldens. Visual checks establish layout expectations; text equality and page totals alone do not.

## Decisions still needed

- Is the target “pages of our retained canonical rendition” or “exactly the pages an author sees in a named Word edition”? The first is achievable with a qualified local renderer; the second needs edition-specific evidence.
- Must the first delivery cover DOCX only, or existing Word97 `.doc` too? Recommendation: DOCX first, preserve existing native `.doc` behavior, then qualify a legacy rendering profile separately.
- Ratify revision/comment/field/blank-page policy and a licensed font set; do not let personal machine defaults decide citation identity.
- Choose derivative retention/access policy and who supplies edition-association evidence for an existing PDF. Citation stability depends on retained immutable artifacts.
- Decide whether source-paragraph-to-page alignment is actually required. Recommendation: deliver retained PDF-page citations first; treat cross-representation alignment as an explicitly qualified follow-up.
- Approve any eventual renderer installation, artifact pins, commercial evaluation or cloud mode separately. This documentation does not grant those actions.

## Primary sources

All links were read in research retrieved 2026-10-29. Undated documentation supports API/format semantics, not a new release date or a tested guarantee. Product licensing remains separate from font and bundled-component rights.

- **W1:** [Microsoft: saved last-rendered page-break semantics](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.lastrenderedpagebreak?view=openxml-3.0.1).
- **W2:** [python-docx rendered breaks, no rendering function and hyperlink caveat](https://python-docx.readthedocs.io/en/latest/api/text.html).
- **W3:** [Microsoft: optional Office 2010 paragraph IDs](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.paragraph.paragraphid?view=openxml-3.0.1).
- **W4:** [LibreOffice PDF export options, including blank-page policy](https://help.libreoffice.org/latest/en-US/text/shared/guide/pdf_params.html).
- **W5:** [Microsoft Word PDF export parameters](https://learn.microsoft.com/en-us/office/vba/api/word.document.exportasfixedformat).
- **W6:** [LibreOffice release branches and dates](https://www.libreoffice.org/release-notes/).
- **W7:** [LibreOffice distribution/component licensing](https://www.libreoffice.org/licenses/).
- **W8:** [LibreOffice headless conversion and per-job profile parameters](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html).
- **W9:** [Microsoft Word Repaginate](https://learn.microsoft.com/en-us/office/vba/api/word.document.repaginate).
- **W10:** [Microsoft: unattended server-side Office automation limitations](https://support.microsoft.com/en-gb/visio/considerations-for-server-side-automation-of-office).
- **W11:** [Aspose.Words Python via .NET 26.10 release notes](https://releases.aspose.com/words/python/release-notes/2026/aspose-words-for-python-via-dotnet-26-10-release-notes/).
- **W12:** [Aspose license options and evaluation restrictions](https://docs.aspose.com/words/python-net/licensing/).
- **W13:** [Aspose platform/native dependencies](https://docs.aspose.com/words/python-net/system-requirements/).
- **W14:** [Aspose's own layout/rendering engine](https://docs.aspose.com/words/python-net/rendering/).
- **W15:** [python-docx 1.2.0 release and MIT metadata](https://pypi.org/project/python-docx/).
- **W16:** [Microsoft Graph format conversion, size limit and permissions](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content-format?view=graph-rest-1.0).
- **W17:** [LibreOffice current security advisories](https://www.libreoffice.org/security/).
- **W18:** [Python 3.12 XML security](https://docs.python.org/3.12/library/xml.html).
- **W19:** [Python 3.12 ZIP security/resource limits](https://docs.python.org/3.12/library/zipfile.html).
