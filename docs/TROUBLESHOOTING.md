# Troubleshooting

| Problem | Check |
| --- | --- |
| Vellric unavailable | Set DRAWBRIDGE_VELLRIC to the actual independently installed executable; run its doctor and --version. Do not install a PDF engine into Drawbridge to bypass the boundary. |
| Scan requires OCR | Install Vellric's OCR extra and qualified Tesseract/data/system preflight tools. `--no-ocr` truthfully refuses those pages. |
| Blocked input | Password-protected/zero-page inputs are typed terminal conditions; see inspect's reason and partial facts. |
| Failed / operational input | Inspect the exact typed failure; missing engines, deadlines/resource limits and changed sources need their own repair, not repeated blind retries. |
| Image mirror says ocr-pending | Check Tesseract, supported Pillow decoder and bounded pixel admission. Unsupported/oversize images retain a truthful fallback. |
| Profile unexpectedly enables work | Use --no-profile, or --dry-run to inspect resolved stages/egress before calls. |
| Audio extra unavailable | Use the pinned public Quillric Git installation in INSTALLATION.md before the Drawbridge audio extra; its compatibility import is transcribe. Quillric 0.1.0 is absent from PyPI at preparation. Rebuild ambiguous environments containing the old separate transcribe distribution. |
| Verification fails | Preserve original bytes and mirror identity; a source change is not the same document. Do not normalize away the word/hash gate. |

CLI exit codes: 0 success, 2 usage, 3 blocked input, 4 failed input, 5 operational failure, 6 verification failure. Library callers receive DrawbridgeError subclasses; blocked_reason identifies terminal input classes. Complete bundles and source custody checks refuse inconsistent artifacts. Supported platform and hard containment limits belong to Vellric's guide; no hostile-document sandbox is promised.
