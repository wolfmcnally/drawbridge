# Phase 4: Progress reports

Status: done (2026-09-28).

## Outcome

A caller running many conversions at once can say which document is at which step and how far through. A client's ingest seemed stalled for 40 minutes while three documents of 412 to 755 pages were being structured a page at a time; nothing the converter did was visible until each document finished.

## Work

- `drawbridge.report_progress(listener)` scopes a listener to a conversion, as `record_calls` does for paid calls; `drawbridge.advance(step, done, total)` reports to it. A listener that raises is ignored.
- `recognition` reports pages recognised of those selected, in page order from the caller's thread while the page workers run side by side; `structure` reports sections of the document's sections; `refinement` reports reviewed windows in window order; `transcription` reports the recording's seconds when it starts and when its package is ready (the dependency transcribes the recording as a whole). Each reports zero done when it starts; a kept transcription reports nothing.
- `__version__` stays 0.4.2: no mirror changes, and a client keys stored recognition and kept transcription packages by the version.

## Acceptance

- One test per step hears the exact sequence of reports; removing any step's report, or letting a listener's failure through, fails it; a mirror produced with a listener (including a failing one) is the mirror produced without one.
- The whole suite passes.
