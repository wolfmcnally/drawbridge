# Drawbridge

Drawbridge turns supported documents into Markdown mirrors with source provenance. Local extraction preserves the original bytes. Unsupported input yields a truthful deferred result; malformed or operational failures remain explicit. Optional audio/model stages require an explicit configuration with privacy, egress and budget rules.

PDF jobs use an independently installed Vellric executable. Drawbridge's MIT runtime does not import Vellric or PyMuPDF. Conversion is not a promise of visual rendering fidelity. Ordinary native PowerPoint ingestion emits one source-bound section per slide, with associated presenter notes and explicit extraction limits. It does not render slides or reconstruct animation builds.

The repository adopts development practices from Starter; this manual describes Drawbridge's product. [Starter](https://github.com/wolfmcnally/agentic-coding-starter) maintains that methodology.
