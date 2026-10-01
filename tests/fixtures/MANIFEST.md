# Fixture provenance

All fixtures are public files retrieved 2026-09-14. Nothing here originates from a private corpus.

| File | SHA-256 | Source | License | Why it is here |
|---|---|---|---|---|
| `rfc8785.pdf` | `1796e120ab220ede15bd88f3740c29f00ebd0d52bd39014aee0cd98b49b8a973` | https://www.rfc-editor.org/rfc/rfc8785.pdf (RFC 8785, JSON Canonicalization Scheme, 20 pages) | IETF Trust Legal Provisions; RFCs may be reproduced and distributed | Born-digital, multi-page, full text layer, no OCR |
| `ccitt.pdf` | `5f4b129bf0eb0d32358a917cd1754c6fd68cac589ad79076b6d0191ebe84f0f1` | https://github.com/ocrmypdf/OCRmyPDF/blob/main/tests/resources/ccitt.pdf (LinnSequencer brochure page, CCITT-encoded) | CC-BY-SA-4.0 (OCRmyPDF test resources, James R. Barlow; image from Wikimedia) | Image-only scan, one page, no text layer |
| `cardinal.pdf` | `ebd7b2233aea5f320562df9635901bbd8e734cb42c85defa1059163d4b1d6ccb` | https://github.com/ocrmypdf/OCRmyPDF/blob/main/tests/resources/cardinal.pdf | CC-BY-SA-4.0 (as above) | The same scanned page baked in at 0, 90, 180 and 270 degrees; proves orientation recovery |
| `graph_ocred.pdf` | `36784b0f8a37f124c7015a68c53d732b07519c30aa1b333e7ec1ba8a69cb6120` | https://github.com/ocrmypdf/OCRmyPDF/blob/main/tests/resources/graph_ocred.pdf | CC-BY-SA-4.0 (as above; image from Wikimedia) | A raster page that already carries an OCR text layer; must still be selected for OCR |
| `trivial.pdf` | `a934a5224754141f1413c9fff2b37c185388ea366ef16c79511c35c61c3d12ff` | https://github.com/ocrmypdf/OCRmyPDF/blob/main/tests/resources/trivial.pdf | CC-BY-SA-4.0 (as above) | Smallest valid PDF: one blank page, no text, no image |
| `invalid.pdf` | `60abfda66889f7ea7721f5b25bf5c189440a988411cb5363c0f616c800f1d889` | https://github.com/ocrmypdf/OCRmyPDF/blob/main/tests/resources/invalid.pdf | CC-BY-SA-4.0 (as above) | A PDF header followed by EOF: malformed input |

Verify with `shasum -a 256 tests/fixtures/*.pdf`.
