# Getting Started

Use Python 3.12+ and uv. From a source checkout, provision the locked environment:

```bash
./bin/setup
```

For deterministic local text conversion:

```bash
uv run --locked drawbridge convert example.txt --no-profile --stdout
```

Create example.txt with the text you intend to convert before running that command. PDF conversion additionally requires the independently installed qualified Vellric executable selected by DRAWBRIDGE_VELLRIC. Full PDF/OCR tests require actual OCR tools and language data. No provider credentials are needed for ordinary local text extraction.
