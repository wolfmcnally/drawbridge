# Phase 3: One lock for every PyMuPDF call

Status: done (2026-09-28).

## Outcome

Every public function in `pdf_tools.py` holds one process-wide, reentrant `PDF_LOCK` while it uses PyMuPDF, and the package exports that lock so a client that calls PyMuPDF itself can hold the same one. MuPDF is not safe to drive from several threads at once, even on separate documents; a client running conversions on parallel workers crashed with a segmentation fault inside `fz_load_jpx` while decoding JPEG 2000 images. Only page rendering was serialised before (a private, non-reentrant lock).

## Work

- `PDF_LOCK = threading.RLock()` replaces the private render lock; `page_texts`, `ocr_page_numbers`, `page_image_coverage`, `page_layouts`, `image_jpeg` and `render_page_png` hold it, each through the exported decorator (rendering too, since a failed save inside PyMuPDF keeps its pixmap in the exception's frames). The slow parts of the stages that use them (a recognition process, a model call) already run after these functions return, so the lock is never held across them.
- `drawbridge.PDF_LOCK` and the decorator `drawbridge.pdf_locked` are exported. When a locked function raises, the decorator clears the frames that finished (for the exception and every chained one) before it releases the lock, so native documents and pixmaps a kept traceback would hold are freed under the lock. A native object caught in a reference cycle can still be freed by the cycle collector on any thread.
- `__version__` stays 0.4.2: the lock changes no output, and a client keys stored recognition and kept transcription packages by the version, which a bump would invalidate for no gain.

## Acceptance

- A test opens documents through every public function from several threads at once and sees at most one open at a time; removing the lock from any one of them fails it. A client holding the lock can still call in (reentrant).
- A locked function that fails after creating native objects, and a page render whose save fails inside PyMuPDF, leave none in the exception's frames, and the clearing is seen while the lock is held; removing the clearing, clearing after the lock is released, or rendering under the bare lock fails that test.
- The whole suite passes.
