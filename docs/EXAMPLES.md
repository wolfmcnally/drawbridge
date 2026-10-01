# Local examples

Use the fresh Drawbridge environment from [installation](INSTALLATION.md). These examples are executed with release packages and public/synthetic input, without a sibling checkout or provider call.

```bash
printf 'Plain local evidence.\n' > example.txt
.venv/bin/drawbridge convert example.txt --no-profile --stdout
.venv/bin/python - <<'PYDEMO'
from drawbridge import convert_file, render_mirror
result = convert_file("example.txt")
assert "Plain local evidence." in result.mirror.body
print(render_mirror(result.mirror))
PYDEMO
```

Create example.pdf through Vellric's documented synthetic-PDF example in its independent environment, copy the resulting input file here, and configure DRAWBRIDGE_VELLRIC to that environment's executable. Only the input PDF is shared; no source checkout/import path is shared.

```bash
.venv/bin/drawbridge inspect example.pdf
.venv/bin/drawbridge convert example.pdf --no-profile -o example.md
.venv/bin/drawbridge verify example.md --pdf example.pdf
```

The local review bundle shows exact native typography, mixed rotated/stale scans, a 59-line banded scroll and two image examples. Text matches the qualified baseline/expected words. Image confidence and a corrected upright-columns rotation value are explicit metadata differences; there is no unexplained new qualified text requiring a blanket owner review.

Examples in the README for audio/model stages are optional configured workflows. Use --dry-run before enabling provider calls. They require actual inputs/profile/keys; no paid-run success is claimed by this local release audit.
