---
title: "drawbridge: PowerPoint ingestion"
date: 2026-10-29
status: proposal
scope: |
  Researches a bounded PowerPoint ingestion path, supported formats, extraction fidelity, notes and assets, dependency alternatives, security, provenance and qualification. This is a research proposal, not implemented or benchmarked functionality, dependency approval or installation authority.
---

# PowerPoint ingestion

## Recommendation

Add a native, local OOXML extraction path using **python-pptx 1.0.2** as the first implementation candidate. Preserve one ordered unit per source slide, with speaker notes explicitly separated and embedded resources inventoried. Start with a qualified subset of ordinary `.pptx` packages; admit `.ppsx` only after equivalent package tests. Keep binary `.ppt`, macro-enabled presentations, templates and unsupported constructs truthfully deferred until their respective paths are qualified. Do not promise that stored shape text is a faithful rendering of what an audience saw.

Use an optional, isolated **LibreOffice Impress PDF export** when visual evidence is required, followed by the existing independently installed Vellric PDF pipeline. Keep the native slide mirror and rendered rendition distinct. This recommendation is an engineering inference from the sources below and the inspected checkout; no representative deck was processed in this research.

Research baseline: **As of 2026-10-29; sources retrieved 2026-10-29.** Release dates below describe the releases, not their retrieval. See the related [Word citation brief](word-page-citations.md) for immutable rendered-page citations and renderer provenance.

## Why it belongs in Drawbridge

In the inspected Drawbridge 0.2.0 checkout, `identify._OOXML_PARTS` recognizes `ppt/presentation.xml`, but `documents._BY_TYPE` has no presentation converter. Such a file currently reaches the typed deferred path, not a slide extractor. `office.py` owns native Office extraction; `_vellric.py` owns the complete-job boundary to an independently installed PDF CLI. Adding a PowerPoint reader fits the former; importing Vellric or PyMuPDF into the runtime does not.

The existing [design brief](design.md) establishes immutable received bytes, explicit source units and complete-or-refuse results. Some of its older dependency descriptions predate the current CLI boundary; current source and README take precedence. `mirror.UNITS` currently permits `page`, `sheet`, `message`, `turn` and `document`, **not `slide`**. A slide mirror therefore requires an explicit contract extension, reader compatibility decision and fixture updates before implementation can advertise support. The existing ten provenance fields must remain intact; a slide must not silently masquerade as an original PDF page.

## What the first supported profile should mean

| Input or feature | Proposed boundary |
|---|---|
| Ordinary transitional OOXML `.pptx` | First qualification target: source slide list, paragraphs/runs, text boxes, nested groups, tables, notes and embedded resource inventory. |
| `.ppsx` slide show | Same general OOXML family, different main-part content type; a separately tested admission, not acceptance by renamed extension. |
| `.potx`, Strict OOXML | Explicitly identified but deferred until namespace/template semantics and fixtures qualify. Do not return blank success for an unrecognized namespace. |
| `.pptm`, `.ppsm`, `.potm` | Defer initially. Do not execute, strip, resave or silently ignore macros while claiming full support. |
| Binary `.ppt` / `.pps` | Separate binary reader or qualified conversion route; python-pptx is not that reader. An OLE container alone does not establish presentation type. |
| Encrypted or rights-managed input | No automatic password acquisition or protection removal. A generic encrypted Office container may not reveal its application type; report only what admission proves. |
| `.odp`, Keynote, arbitrary ZIP | Outside this PowerPoint profile. Optional converter capability is not blanket admission. |
| Animations, transitions, interactive builds | Inventory/flag where detectable; no timing, animation-state or narrated-show fidelity claim. |

Content admission must use package content types and relationships, not a suffix or the mere presence of `presentation.xml`. The existing coarse detector does not itself distinguish all these variants. Reject ambiguous, malformed or incomplete required package structure before conversion.

## Extraction and fidelity contract

1. **Use presentation order.** Traverse the presentation's ordered slide-ID list and resolve its relationships. Never sort ZIP members or infer order from `slide1.xml`, numeric IDs or displayed slide-number text. Microsoft documents the presentation/slide relationship structure [P1]. Preserve both a one-based ordinal and original slide ID/part locator, bound to the input hash.
2. **Account for every slide.** Include hidden and text-free slides in the canonical source sequence, with explicit hidden status and an empty-text marker that does not claim an image-only slide is blank. Record custom slide shows as alternative sequences, not the deck's canonical ordering. Distinguish ordinal, source ID and authored display label.
3. **Name the text-order policy.** python-pptx shape iteration follows drawing order, which is not evidence of semantic reading order [P2]. Walk group children and text paragraphs deterministically; preserve breaks, table row/cell positions and shape locators. Do not silently impose top-left sorting, deduplicate repeated text or call the result audience reading order. An accessibility reading order can differ from visual order [P3].
4. **Keep notes separate.** Store presenter text under a clearly identified notes section for its source slide, with an explicit include/exclude policy recorded in provenance. The proposed completeness default includes existing speaker notes, without notes-master boilerplate or slide-number placeholders. Check `has_notes_slide` before reading notes: accessing a missing notes slide can create one in memory [P4]. Never save the source presentation. Notes are not necessarily audience-visible text.
5. **Inventory assets without executing them.** Identify pictures, media, OLE attachments and relationships; retain content hashes, types, bounded sizes, part/relationship locators and all slide occurrences, even when one asset is shared. Use safe output names, not archive-controlled paths. Do not activate objects, play media, fetch linked resources or recursively ingest attachments by default. Mark external targets unvisited and redact sensitive URL details from diagnostics.
6. **Be explicit about unsupported content.** Chart labels/cached values, SmartArt, equations, master/layout text, vector artwork, cropped images and objects outside the visible frame need coverage decisions. Extracting some text is not complete visual coverage. Unsupported visible content needs a verification flag or qualified rendition; failure to enumerate a required slide is an operational failure, not partial success. Alt text is authored metadata, not an independently verified image description.

python-pptx exposes useful text, image, table and chart APIs but acknowledges incomplete feature coverage [P5]. Its preservation of elements during round trips does not imply that its extraction API understands every element. The recommendation is to use its maintained object model with narrow, tested package inspection for missing metadata, rather than grow a complete PresentationML implementation in Drawbridge.

## Dependency alternatives and licensing

Versions are evaluation baselines, not newly qualified pins. Check exact artifacts and current advisories again when implementation starts.

| Option | Version/evidence | License and operating cost | Decision |
|---|---|---|---|
| python-pptx | 1.0.2, released 2024-08-07; Python >=3.8; official docs still display 1.0.0 [P5, P6] | MIT; works without installed PowerPoint. Adds parser dependencies and a maintenance surface. | Preferred native reader on Drawbridge's Python 3.12 baseline; do not infer renderer capability. |
| Direct ZIP/XML reader | Current standard-library facilities plus an explicitly hardened XML parser | No PowerPoint dependency; application owns OPC relationships, drawing objects and every unsupported case. | Useful for admission and missing metadata; reject as the default full-format implementation. |
| Apache POI HSLF/XSLF | 6.0.0 released 2026-10-22; JDK 17 minimum [P7] | Apache-2.0 plus transitive notices; JVM deployment, classpath and memory costs. HSLF requires the scratchpad component [P8]. | Strong later candidate if native binary `.ppt` ingestion is important; disproportionate for first Python OOXML support. |
| LibreOffice Impress | 26.8.1 current branch; 26.2.6 mature previous branch [P9] | MPL-2.0 distribution with additional component licenses, plus independently licensed fonts [P10]. Suite size and process isolation required. | Optional external rendering/conversion candidate, not the native reader or a PowerPoint-equivalence guarantee. |
| Author-supplied PowerPoint PDF | Renderer/export version belongs in supplied provenance | Requires an appropriately licensed authoring application; no application installation in Drawbridge. | Useful visual evidence, but does not by itself recover notes or embedded assets. |
| Microsoft Graph conversion | Documented v1.0 service accepts `.ppt`/`.pptx` and other formats for PDF [P11] | Cloud storage/API authorization and tenant terms; service renderer is not locally pinned. | Not the default local path; any future cloud mode requires separate egress/authorization design. |

The python-pptx 1.0.2 manifest requires Pillow, XlsxWriter, lxml and typing_extensions [P12]. Pillow is already a Drawbridge dependency. lxml is BSD-3-Clause; **6.1.3**, released 2026-09-02, fixes an external-parameter-entity default issue, so accepting the reader's very old minimum lxml version would be inappropriate [P13]. XlsxWriter is BSD-2-Clause [P14]; typing_extensions is PSF-2.0 [P15]. Freeze exact compatible transitive versions, hashes, bundled native XML libraries and notices in the future lock/SBOM; no lock was changed here. The python-pptx release files have published checksums but no PyPI upload attestations [P6]; checksums establish artifact identity, not independent safety review.

If the small admission parser uses defusedxml, evaluate 0.7.1 under its PSF licensing [P16]. It is a possible hardening dependency for that parser, not a wrapper that automatically secures python-pptx/lxml or a renderer. Do not add python-docx merely to process presentations.

## Optional rendering without losing the slide map

Prefer direct PDF export rather than a print-driver workaround. Explicitly choose full-slide pages, deck order, all slides including hidden ones, and no inserted notes/handout pages for the canonical visual rendition. LibreOffice exposes separate hidden-slide and notes-page export controls; hidden slides are omitted by default [P17]. Validate a one-to-one slide-to-page map rather than assume it. Preserve notes-page or handout exports only as separately labelled renditions with their own mapping.

Rendering may change fonts, line wraps, charts or unsupported drawing effects. Pin the renderer build, platform, font files and substitutions, locale, export settings and resulting PDF hash. Preserve that PDF and then use Vellric's existing complete inspection/conversion validation. Do not change the original input hash to the derivative PDF hash. Derive optional image OCR or semantic descriptions separately, recording source slide and method, rather than mixing recognized/inferred text into native text without attribution. No model is needed for baseline ingestion.

Do not substitute unattended desktop PowerPoint automation as an assumed server renderer. Microsoft's Office automation support limitations and the distinction between author export and unattended workers are covered in the [Word brief](word-page-citations.md#dependency-alternatives-and-decisions).

## Security and operational requirements

Treat each deck as hostile structured input. Bound input size, archive members, actual decompressed bytes, XML depth and shape/slide/asset counts; reject duplicate or unsafe names, invalid internal relationship traversal and external-resource fetching. Python documents XML attack classes and ZIP decompression exhaustion [P18, P19]. Explicitly disable DTD/entity/network resolution and do not rely on library defaults alone. Malformed input, resource exhaustion and unsupported coverage require different typed outcomes.

Run heavy parsing/rendering in a bounded worker with a private workspace, read-only source copy, scrubbed environment, explicit CPU/memory/disk/time limits and enforced network denial. A timeout or `--headless` flag is not a security sandbox. Rendering needs a separate writable LibreOffice profile per job to avoid interacting with an operator's open session [P20]; disable macros and link updates before loading, and do not inherit trusted macros, extensions or unrestricted personal files. LibreOffice's current advisories include malicious-document file-write and external-data access fixes [P21]. Check patched builds rather than claim any version is vulnerability-free. Keep full suite/fonts/native-code redistribution obligations separate from Drawbridge's MIT grant.

The proposed worker can reuse Drawbridge's existing process/privacy and artifact-validation patterns, without making Vellric own PowerPoint parsing or duplicating provider schemas. A future renderer adapter must validate its own PDF output before the independent PDF boundary admits it. No service, installation or capability grant is authorized by this brief.

The existing PDF CLI is Vellric under AGPL-3.0-only; Drawbridge's MIT license does not replace its license or those of LibreOffice, fonts and bundled native libraries. Preserve the separately installed boundary and follow the existing [licensing documentation](../docs/LICENSING.md); any redistribution or hosted packaging needs its own component-level license review.

## Qualification before implementation acceptance

Use synthetic fixtures and public decks with recorded licenses/hashes. Required cases include slide filenames out of order, reorder without ID renumbering, hidden/empty/image-only slides, repeated display numbers, notes absent/present, nested/rotated groups, merged tables, repeated/shared assets, charts, missing relationships, external URLs, ambiguous families, encrypted containers, Strict namespaces and macro-bearing packages. Include malformed XML, ZIP bombs, duplicate entries, traversal, resource exhaustion and missing renderer/fonts.

Prove input bytes remain unchanged; every admitted slide is accounted for; missing notes are not manufactured; notes and assets remain correctly attached; unknown content cannot become silent completeness. Check native text and slide-map goldens independently from visual render comparisons. Exercise typed errors, CLI/API parity, configuration precedence and existing no-AI/local-only/credential boundaries. Test the `slide` unit decision against every independent mirror-contract fixture inventory and older readers. Rendering qualification must compare actual outputs on supported platforms; no cross-platform byte-equivalence or perfect PowerPoint fidelity follows from the documentation.

## Decisions still needed

- Confirm whether first delivery needs binary `.ppt`, Strict OOXML or templates; recommendation is ordinary `.pptx` first, with `.ppsx` admitted after explicit tests.
- Ratify notes/hidden-slide defaults and where potentially private notes and embedded attachments may be exposed. Proposed default preserves them locally and labels them separately.
- Choose the compatible versioning/capability mechanism for `unit=slide`; do not silently widen an existing reader contract.
- Decide whether visual slide fidelity is required immediately. If so, qualify an external renderer and a licensed font set; native text alone is insufficient evidence.
- Freeze dependency artifacts/transitives and release security/notice checks during the implementation phase. No dependency installation, trial conversion or benchmark was performed for this brief.

## Primary sources

All links below were read in research retrieved 2026-10-29. API documentation is evidence of available interfaces, not a qualification run. Release-page dates remain the dates shown by their publishers.

- **P1:** [Microsoft: presentation packages, slide lists and read-only access](https://learn.microsoft.com/en-us/office/open-xml/presentation/how-to-open-a-presentation-document-for-read-only-access).
- **P2:** [python-pptx shape APIs and drawing order](https://python-pptx.readthedocs.io/en/latest/api/shapes.html).
- **P3:** [Microsoft: accessible reading order](https://support.microsoft.com/en-us/powerpoint/accessibility/video-create-slides-with-an-accessible-reading-order?wt.mc_id=otc_accessibility_video_training).
- **P4:** [python-pptx notes-slide APIs](https://python-pptx.readthedocs.io/en/latest/user/notes.html).
- **P5:** [python-pptx scope and feature limits](https://python-pptx.readthedocs.io/en/latest/).
- **P6:** [python-pptx 1.0.2 release, MIT license and artifact provenance](https://pypi.org/project/python-pptx/1.0.2/).
- **P7:** [Apache POI current release and verification](https://poi.apache.org/download.html) and [6.0.0 Java/runtime changes](https://poi.apache.org/changes.html).
- **P8:** [Apache HSLF/XSLF components](https://poi.apache.org/components/slideshow/) and [parser containment guidance](https://poi.apache.org/security.html).
- **P9:** [LibreOffice current and mature release branches](https://www.libreoffice.org/release-notes/).
- **P10:** [LibreOffice distribution and component licenses](https://www.libreoffice.org/licenses/).
- **P11:** [Microsoft Graph v1.0 format conversion and permissions](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content-format?view=graph-rest-1.0).
- **P12:** [python-pptx 1.0.2 dependency manifest](https://raw.githubusercontent.com/scanny/python-pptx/v1.0.2/pyproject.toml).
- **P13:** [lxml 6.1.3 security fix and BSD-3-Clause metadata](https://pypi.org/project/lxml/).
- **P14:** [XlsxWriter license](https://xlsxwriter.readthedocs.io/license.html).
- **P15:** [typing_extensions license/provenance metadata](https://pypi.org/project/typing-extensions/).
- **P16:** [defusedxml 0.7.1 scope and license](https://pypi.org/project/defusedxml/).
- **P17:** [LibreOffice PDF export properties](https://help.libreoffice.org/latest/en-US/text/shared/guide/pdf_params.html).
- **P18:** [Python 3.12 XML security](https://docs.python.org/3.12/library/xml.html).
- **P19:** [Python 3.12 ZIP handling and decompression pitfalls](https://docs.python.org/3.12/library/zipfile.html).
- **P20:** [LibreOffice command-line and private-profile parameters](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html).
- **P21:** [LibreOffice security advisories](https://www.libreoffice.org/security/).
