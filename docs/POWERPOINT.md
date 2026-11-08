# PowerPoint ingestion

The native PowerPoint path reads ordinary transitional OOXML presentations by content, preserves original bytes, and writes one section per source slide in canonical deck order. It extracts stored native text, grouped text, table cells and existing presenter notes. It does not render slides, run animations, execute embedded objects, fetch links, OCR images, or reconstruct charts and SmartArt.

Each fully built slide is one section. Animation/build steps never become separate sections. Stored objects can include content that would be hidden by an animation or obscured visually; native extraction cannot determine the final visible frame. Hidden slides remain represented and labelled. A slide with no recovered native text gets an explicit marker; that marker does not mean the slide is visually blank.

## Convert and verify

Convert a local deck:

```bash
drawbridge convert slides.pptx
```

Exclude presenter notes from the output:

```bash
drawbridge convert slides.pptx --notes exclude -o public-slides.md
```

Verify slide identity, count, native content, notes and assets against the original bytes:

```bash
drawbridge verify public-slides.md --source slides.pptx
```

Verification re-admits the original package. A self-consistent map alone cannot prove that its text came from the source. The existing PDF verification spelling, `--pdf`, remains an alias for `--source`.

## Notes and configuration

Existing presenter notes appear inside their slide section, after its content, with separate authoritative spans. The local fidelity default preserves notes. This is extraction behavior, not permission to publish notes or send them to a provider. Inspect a mirror before sharing it. An existing notes part with no presenter text is distinguished from an absent notes part.

The API's explicit `ConversionOptions(include_notes=False)` or CLI `--notes exclude` wins over configuration. Otherwise the active profile's strict boolean `presentation_notes` setting applies:

```yaml
drawbridge:
  presentation_notes: false
```

The legacy standalone profile uses `presentation_notes: false` at its root. An explicit per-call `True` or `--notes include` overrides that setting. The original configuration inputs still pass to the independently installed PDF engine unchanged; no new PDF-engine notes flag is added.

No whole-deck speaker-notes source is supported by this native profile. Notes-master boilerplate is not invented as deck notes. A future supported whole-deck source must precede the slide sections.

## Slide mirror contract

Presentation mirrors declare `format: drawbridge.mirror.v2`, `unit: slide`, `slide_count`, and a `drawbridge.slide-map/1.0` map bound to the original source digest. Existing v1 mirrors, units and readers remain supported; older v1-only readers reject v2. Current semantic/refinement/transcript stages refuse slide mirrors rather than interpret them as pages or turns.

Every slide record has a one-based ordinal, original numeric slide id and package part locator, hidden/text-free flags, stable source-bound anchor, separate content and optional notes spans, and feature limitations. Offsets count Unicode code points in the normalized mirror body. Canonical order comes from the presentation's slide-id list, not part filenames or ZIP order. Dynamic plaintext fences prevent source headings, HTML and fence strings from manufacturing authoritative sections.

`slide_sections(body, header=header)` returns full framed payloads in source order, including attached notes. Header-aware `sections` returns `(Slide N, payload)` pairs. Map spans separately identify native text and notes. A body-only heading splitter is not an authoritative slide reader.

`presentation_assets` inventories non-XML parts with digest, declared type, byte size and per-slide/notes/inherited reference occurrences where associated. Shared assets keep repeated uses. Relationship-only references and unreferenced package assets remain explicit. External references record scheme and target digest, never fetched contents or raw targets. Excluding note text does not remove package metadata or the existence and digests of note-owned assets. Excluded notes can also leave note-owned external-link schemes and unsalted target digests in the inventory; low-entropy URLs or addresses can be confirmed by guessing. Notes exclusion is text selection, not a complete sharing redaction.

## Admission and limitations

The initial profile excludes binary PowerPoint, macro-bearing packages, templates, slideshows, encrypted packages and Strict OOXML. A proven unsupported family returns a truthful deferred mirror with its admitted media type. Malformed packages, unresolved required relationships, ambiguous slide or notes ownership, unsafe ZIP paths, duplicate members, DTD/entity declarations and exceeded limits fail the complete job. They do not return a partial success mirror.

Native extraction always carries `presentation-native-only`. Detected images, embedded media, charts, alternate content, timing/transitions, external references and inherited master/layout text carry limitations. Asset inventory and a successful text extraction do not establish visual completeness or rendering fidelity. Master/layout text is not flattened into slide text. Custom shows are recorded as alternate sequences; the canonical deck order remains authoritative.

Limits are 64 MiB source bytes, 256 MiB expanded package bytes, 64 MiB per expanded member, 4,096 members, 1,000 slides, 20,000 shapes, 16 MiB aggregate XML, 8 MiB per XML part, 200,000 XML nodes, XML depth 128, relationship depth 64, 100,000 graph traversal steps and 16 MiB child output. The isolated job has a 60-second deadline and 30 CPU-second soft limit (31 seconds hard). An expansion/XML/resource refusal is typed and leaves the source unchanged.

The initial profile admits stored and deflated ZIP members. It counts actual decompressed output independently of attacker-declared lengths, checks each member's actual size and CRC, and refuses inconsistent or trailing compressed data. Declared ZIP sizes alone cannot establish the expanded-byte bound.

As of 2026-11-08, the worker supports macOS with the installed Seatbelt executable and dyld startup profile, and 64-bit Linux x86_64/aarch64 with native seccomp controls. Missing or refused controls fail closed; there is no uncontained fallback. macOS permits only selected runtime/package/job reads, denies network access and watches resident memory every 100 ms against 2 GiB. Sampling can overshoot between observations. Linux applies a 2 GiB address-space limit and denies socket creation, child creation, exec and io_uring syscalls after startup; it does not claim filesystem isolation. A parser compromise on Linux can read and write files available to its account. Closed inherited descriptors and a scrubbed environment reduce exposure but are not a filesystem sandbox. Unsupported platforms report unavailable capability. Qualification evidence must name the actually tested host and architecture; a supported code path is not itself a cross-platform test result.

## Reproducible first-party sample

From a source checkout, create the small synthetic sample used by the tests:

```bash
./bin/python -c 'from pathlib import Path; import sys; sys.path.insert(0, "tests"); from presentation_fixtures import build_deck; build_deck(Path("sample.pptx"))'
```

Then convert and verify it using the commands above with `sample.pptx`. It contains deliberately reordered slides, attached notes, a hidden slide, grouped/table text, repeated image uses an empty slide and two paragraph-build metadata records on one slide. This demonstrates section accounting, not animation playback. Human inspection remains necessary for readability and suitability. Downloaded qualification decks and their mirrors are private evidence and are not distributed.

Malformed presentation errors expose a stable short code through the API and CLI JSON reason, including `duplicate-member`, `unsafe-member`, `xml-doctype`, `missing-internal-target`, `ambiguous-slide-identity` and `ambiguous-notes-owner`. Resource refusals remain a distinct type, with `xml-byte-limit` or `expanded-byte-limit` where identified. Missing containment/runtime capability is distinct from a reader that terminates after its startup handshake; an unexplained post-startup crash is operational and is not claimed to prove malformed input.
