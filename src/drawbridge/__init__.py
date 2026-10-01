"""drawbridge: any file in, one Markdown mirror out."""

from .audio import AudioLimitExceeded, RunBudget, rerender
from .convert import ConversionOptions, ConversionResult, convert_pdf
from .documents import FileConversion, convert_file, deferred, extract_text, plan_report, supported
from .errors import (
    ConversionOperationalError,
    ConverterUnavailable,
    DrawbridgeError,
    InherentlyUnprocessableError,
    MediaTypeError,
    MirrorFormatError,
    OcrOperationalError,
    OcrPreflightError,
    blocked_reason,
)
from .identify import IdentifyResult, identify, refine_media_type, sniff_media_type
from .mirror import (
    MIRROR_FORMAT,
    Mirror,
    mirror_text,
    page_sections,
    parse_mirror_header,
    render_mirror,
    sections,
)
from .office import OFFICE_TEXT_MEDIA_TYPES, office_text
from .ocr import CliOcrBackend, OcrBackend, OcrCapacity, OcrResult, ocr_jobs_for
from .orientation import RecoveredPage, recover_page
from .progress import ProgressListener, advance, report_progress
from .profile import EMPTY_PROFILE, EgressRefused, Plan, Profile, ProfileError, build_plan, load_profile, parse_profile, resolve_profile
from .pdf_tools import (
    PDF_LOCK,
    pdf_locked,
    DegeneratePdfError,
    EncryptedPdfError,
    MalformedPdfError,
    PdfInspection,
    PdfOpenOperationalError,
    PdfReadOperationalError,
    ocr_page_numbers,
    page_texts,
)

__version__ = "0.1.0"

__all__ = [name for name in dir() if not name.startswith("_")]
