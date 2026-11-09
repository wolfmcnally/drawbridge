# Drawbridge 0.3.1 release facts

The 0.3.1 patch candidate includes the CSV correction: content sniffed as `application/csv` uses the same source-preserving text path as `text/csv`. Binary content and unknown application media types remain deferred. It retains the ordinary native PowerPoint ingestion, physical PDF citation integration, existing page mirrors and independent PDF-engine boundary from 0.3.0. Public publication is a separate verified operation: use the established GitHub Releases destination and compare the actual downloaded artifact digests with its release notes. A prepared candidate is not proof of a published release.

## Public artifacts

The intended downloadable files are `drawbridge-0.3.1-py3-none-any.whl` and `drawbridge-0.3.1.tar.gz`. The source archive includes the lock, exact build constraints, source, public product tests/fixtures and notices. Dependency native binaries, private phase proof, operational logs, downloaded trial decks and their derivatives are excluded. Conric and optional Quillric reference their published `v0.1.0` tags, resolved by the lock to the same previously qualified commits. Conric remains a public Git dependency, so the destination is GitHub Releases rather than a package index. Follow [installation](INSTALLATION.md).

## Product boundaries

- Ordinary transitional PowerPoint packages produce `drawbridge.mirror.v2` with `unit: slide`, one canonical section per source slide and separately mapped associated notes. Hidden and native-text-free slides remain explicit. Builds do not become extra slide sections. Existing v1 behavior remains supported.
- Notes selection is explicit through API, CLI and configuration. Excluding note text is not complete asset/link-inventory redaction and grants no publication permission. Whole-deck speaker notes are not invented from notes-master boilerplate.
- Binary, macro-bearing, template, slideshow, encrypted and Strict OOXML ingestion, slide rendering, visual fidelity and provider execution are not claimed. See [the PowerPoint guide](POWERPOINT.md) for admission, containment and resource limits.
- Fresh installed PPTX qualification targets macOS arm64 and Linux aarch64 with Python 3.12.12; fresh installed native/configured/OCR PDF qualification targets macOS arm64 only. Linux seccomp controls deny network/process execution but do not provide filesystem isolation; macOS uses its documented Seatbelt profile and sampled RSS watchdog. Windows and other installed-platform qualification remain outside these claims.
- PDF parsing/rendering/OCR continues to use independently installed Vellric. Drawbridge's MIT core does not import or vendor its AGPL engine. Dependencies retain their own component licenses, including the selected lxml wheel's independent native notices; see [licensing](LICENSING.md).

## Validation surfaces

The release qualification checks exact metadata and preserved dependency pins, allowlisted source/wheel contents and notices, rebuilding the wheel from public source, and fresh installed native/configured/OCR/PPTX API/CLI/configuration behavior. Actual CI results, signing and downloaded-byte verification are separate release evidence. No public CI result is represented as proof of an unrun human sample review.

The retained maintainer checkout owns full private historical acceptance and runs its complete gate. A fresh public clone omits that ignored proof, so it cannot replay the private methodology-acceptance portion of `./bin/check all`. Public CI's `./bin/test` checks the product test suite with declared prerequisites; it does not replace the maintainer audit. This known limitation does not require publishing private proof or adding a new public-history gate to artifact qualification.

Human review of the first-party sample remains open for slide order, labelled associated notes and readability. Automation proves the declared extraction and installed boundaries, not whether the result meets the operator's needs. [Create the sample](POWERPOINT.md#reproducible-first-party-sample) from matching public source and compare notes included/excluded before sharing a mirror.
