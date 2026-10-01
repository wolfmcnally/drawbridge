# drawbridge plan

As of 2026-09-18. Both phases are done. The goal was a portable master converter: any file in, one Markdown mirror out, with optional model stages that produce cleaned, groomed, easily chunkable Markdown. drawbridge owns the mirror format. Its first client is a document-research pipeline that will delete its own converters and depend on drawbridge instead; audio and video go through the separate `transcribe` project, which drawbridge depends on.

## Two phases, and why two

| Phase | Outcome | Character |
|---|---|---|
| [1. Every file type, one mirror contract](01-every-file-type.md) | Every non-audio file type converts locally to a mirror under a versioned format with an extension area | Deterministic, local, no keys, no spend, provable against golden outputs |
| [2. Profile and networked stages](02-profile-and-networked-stages.md) | Audio and video mirrors through `transcribe`, plus the model grooming stages, all under one profile with egress, cost and preservation guards | Paid, non-deterministic, sends bytes off the machine |
| [3. One lock for every PyMuPDF call](03-one-lock-for-pymupdf.md) | Every PyMuPDF call holds one exported, reentrant process-wide lock | A thread-safety fix; no output changes |
| [4. Progress reports](04-progress-reports.md) | The long steps report units done of total to a listener a caller supplies for a conversion | Observability only; no output changes |

The seam is **whether a byte leaves the machine**. Everything in phase 1 runs offline and is judged by exact expected output. Everything in phase 2 needs the same apparatus before its first call: named endpoints, keys from the environment, an egress rule, a dry-run plan, limits, caching by content hash, and provenance entries that say what went where. Audio needs that apparatus exactly as much as grooming does, which is why audio sits in phase 2 rather than with the other converters: putting it in phase 1 would mean building half the profile there and the other half later.

Each phase stands alone. Phase 1 by itself lets the client retire its document converters and re-ingest every non-audio file. Phase 2 by itself is useless without phase 1's mirrors and format to build on, and is the only place spend and egress decisions are made. Neither is split further: the phase 1 converters share one format, one dispatch and one fixture estate, and the phase 2 stages share one profile and one guard set, so cutting inside either would separate things that are designed and tested together.

`briefs/profile.md` predates the decision to depend on `transcribe`; where it says to port that project's provider code, this plan supersedes it.
