# Licensing and the standalone boundary

Drawbridge 0.1.0 is MIT; LICENSE and NOTICE accompany its project artifacts. Its runtime wheel contains Python source/notices and separately installs permissive dependencies. PDF parsing/rendering/OCR/native typography belong to independently installed **Vellric 0.1.0**, AGPL-3.0-only, through complete document jobs. Drawbridge imports/installs neither Vellric nor PyMuPDF in its runtime. Pillow owns non-PDF images.

PyMuPDF remains a development-only fixture/lock-test dependency. Existing external consumers that own native engine objects retain their own obligations and use the real PDF_LOCK/pdf_locked exports until migrated. Quillric is an optional audio distribution with its own notices, compatibility import namespace and provider requirements.

The source archive includes unmodified public fixtures. Their CC-BY-SA-4.0/IETF grants, original sources/hashes and attribution remain in tests/fixtures/MANIFEST.md, NOTICE and LICENSES/CC-BY-SA-4.0.txt. MIT does not overwrite those grants. The full CC text is retained from [SPDX primary license data](https://github.com/spdx/license-list-data/blob/main/text/CC-BY-SA-4.0.txt).

Publish this first-public 0.1.0 candidate only after its exact tested Vellric commit and artifacts are reachable. Matching wheel/source/lock/build material and notices stay together. Live installs/store/cache changes require separate authorization. The preserved briefs/plan/tests explain design and methodology; they are retained in the repository/source archive rather than removed for presentation.
