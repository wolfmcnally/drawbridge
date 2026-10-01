---
title: drawbridge profiles: optional AI stages configured by YAML
date: 2026-09-15
status: proposal
scope: |
  Proposes the profile file every drawbridge invocation looks for, the YAML schema that carries endpoint specifications and per-stage settings for the optional AI pipeline stages (OCR models, structural recovery of OCR'd text, image description, audio cleanup, transcription, transcript refinement), the activation rule (present and applicable means active, unless the CLI says otherwise), the secrets and egress rules, and how each stage records itself in the mirror's provenance. Candidate providers are listed with retrieval dates; the schema is the deliverable, the candidates are illustrations.
---

# drawbridge profiles: optional AI stages configured by YAML

## Why a profile

drawbridge without a profile is what it is today: local, deterministic, fail-closed, and limited to what PyMuPDF, Tesseract and ocrmypdf can do. Everything beyond that (a model that reads a scan better than Tesseract, a pass that restores headings and emphasis to OCR'd text, a service that levels a recording before transcription, a transcription provider) needs an endpoint, a model name, a key, and a handful of settings. Those belong in one file the user owns, not in a growing list of CLI flags, and not in code.

The profile is optional in both directions. No profile means no AI stage runs. A profile with a key for a stage means that stage runs whenever the input is the kind of document it applies to, unless a CLI option says otherwise. That default is deliberate: the user who wrote a `transcription` block wants their audio transcribed without remembering a flag every time.

## Where the profile lives

Resolution order, first match wins, no merging:

1. `--profile PATH` on the command line.
2. `$DRAWBRIDGE_PROFILE`.
3. `./drawbridge.yaml` in the current directory (a project-local profile).
4. `$XDG_CONFIG_HOME/drawbridge/profile.yaml`, which defaults to `~/.config/drawbridge/profile.yaml`.

`--no-profile` ignores all four and runs the local pipeline only. Merging profiles is not supported in the first version; a project that wants a variant of the user profile copies it. If layering proves necessary later, a single `extends: PATH` key with shallow, key-level override is the most that should be added.

## Secrets

The profile never contains a secret. Every endpoint names the environment variable that holds its key (`api_key_env: OPENROUTER_API_KEY`). Before resolving, drawbridge loads a `.env` file from the current directory and then from the profile's own directory, without overriding variables already set, the same convention the `transcribe` project uses. Keys are never printed, never written to any artifact, and never included in `--dry-run` or `profile show` output; those show the variable name and whether it is set.

## Endpoints

Endpoints are declared once, by name, and referenced from stages. This keeps one provider's URL and key in one place when several stages share it.

```yaml
endpoints:
  openrouter:
    kind: openai-compatible        # openai-compatible | anthropic | ollama | elevenlabs | auphonic | command
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    egress: cloud                  # cloud | local; must be declared, never inferred
    timeout_seconds: 120
    max_concurrency: 4
  local-vlm:
    kind: ollama
    base_url: http://127.0.0.1:11434
    egress: local
  scribe:
    kind: elevenlabs
    api_key_env: ELEVENLABS_API_KEY
    egress: cloud
  auphonic:
    kind: auphonic
    api_key_env: AUPHONIC_API_KEY
    egress: cloud
  paddle-ocr:
    kind: command                  # a local executable that speaks a documented stdin/stdout contract
    command: ["paddleocr-vl", "--json"]
    egress: local
```

`kind` selects the adapter. `openai-compatible` is the workhorse: it covers OpenAI, OpenRouter, Ollama's OpenAI endpoint, LM Studio, vLLM and most hosted OCR-model gateways with one implementation of chat completions with image input. `anthropic` is a second small adapter for the Messages API. `elevenlabs` and `auphonic` are provider-specific because their APIs are. `command` runs a local program under a fixed JSON contract so a dedicated OCR model served by its own runtime can be plugged in without a network hop.

`egress` is declared by the user because drawbridge cannot know whether a URL is a laptop or a data centre. The CLI's `--local-only` refuses to run any stage whose endpoint declares `cloud`, and every run's plan states which stages will send bytes off the machine.

## Stages

Stages are the categories. Each stage key is present or absent; presence is the switch. Each stage has an `applies_to` default drawn from the media types it can act on, which the profile may narrow but not widen.

| Stage | Acts on | What it does | Default engine when the key is absent |
|---|---|---|---|
| `ocr` | scan-like PDF pages, images | Recognises text from pixels | Tesseract, local |
| `structure` | OCR'd pages (optionally native pages) | Restores headings, emphasis, lists, tables, links as annotations over the exact text | Deterministic span-flag pass for native pages; nothing for OCR'd pages |
| `image_description` | images | Produces a prose description in its own `## Description` section beside the OCR text, flagged `description-model-written` | Nothing. `description-pending` appears only when the stage ran and the endpoint gave nothing usable |
| `audio_cleanup` | audio, video audio track | Levels, denoises, isolates speech before transcription | Nothing |
| `transcription` | audio, video audio track | Diarised transcript with timestamps | Nothing; audio is refused with an operational error |
| `transcript_refinement` | transcripts | Speaker resolution, paragraphing, corrections proposed as annotations | Nothing |

Two stages are non-AI but configured here because they are the substrate the AI stages sit on: `ocr` with `engine: tesseract` and `structure` with `native_pass: deterministic`. Putting them in the same file lets a profile say "Tesseract for orientation, then this model for recognition" in one place.

### `ocr`

```yaml
stages:
  ocr:
    engine: vlm                    # tesseract | vlm | api | command
    endpoint: openrouter
    model: qwen/qwen3-vl-32b-instruct
    applies_to: [pdf-scan-page, image]
    orientation: tesseract         # tesseract | none; four-rotation scoring stays local and cheap
    dpi: 300
    prompt: default                # default | PATH to a prompt file
    fallback: tesseract            # tesseract | fail; what happens when the endpoint errors
    max_pages: 500                 # refuse documents larger than this rather than run up a bill
    cache: true                    # content-hash keyed cache of page results under cache_dir
```

The recognition engine replaces Tesseract's text for selected pages only. Page selection (empty text or raster coverage) and orientation recovery stay exactly as they are, because a cheap local pass that fixes a sideways page is worth doing before an expensive one. With `orientation: tesseract`, the VLM sees the best-scoring rotation once; with `none` it sees the page as rendered.

Candidate engines, retrieved 2026-09-15. Dedicated open document-OCR models now outperform much larger general VLMs on document benchmarks at small parameter counts: PaddleOCR-VL, GLM-OCR and MinerU2.5 lead OmniDocBench, with olmOCR, HunyuanOCR and DeepSeek-OCR in the same class; general VLMs (Qwen3-VL, GLM-4.5V, Llama 3.2 Vision) trade accuracy for breadth; Tesseract, PaddleOCR, EasyOCR, Surya and docTR remain the traditional local engines. Hosted document APIs (Mistral OCR, Azure Document Intelligence, Google Document AI, AWS Textract) fit the `api` kind. A dedicated model served locally is the natural `command` endpoint; a hosted one is `openai-compatible` through a gateway.

### `structure`

```yaml
  structure:
    endpoint: openrouter
    model: anthropic/claude-sonnet-5
    applies_to: [pdf-scan-page]    # add pdf-native-page to also annotate born-digital pages
    native_pass: deterministic     # deterministic | none; span flags, size bands, links, tables
    mode: annotate                 # annotate | rewrite
    preservation: strict           # strict | lenient | off
    elements: [headings, bold, italic, code, lists, blockquotes, tables, links, paragraphs]
    render_page_image: true        # the model sees the page image and the numbered text
    output: semantic               # semantic | in-place; in-place is refused unless preservation is strict
```

`mode: annotate` is the default and the recommended one. The model receives the page image and the exact mirror text with line numbers, and returns annotations only: heading level for a line, a character range to embolden, a list item, a blockquote. Code applies the annotations to the retained bytes, so the words cannot change. `mode: rewrite` lets the model emit Markdown directly; `preservation: strict` then strips the syntax from the output and requires token-sequence equality with the mirror text before a page is accepted, and a rejected page keeps its fidelity text and is listed in `verify`. `lenient` accepts a high similarity ratio and records the ratio. `off` exists for experiments and is refused with `output: in-place`.

The deterministic native pass needs no endpoint: PyMuPDF span flags give bold, italic and monospace; a per-document size histogram gives heading levels; `get_links` gives links; `find_tables` gives tables. It runs whenever `structure` is present, before any model, and the model pass on native pages is opt-in (`native_pass: none` with `pdf-native-page` in `applies_to`) because the deterministic evidence is usually better than a guess from pixels. Its output passes the same word-preservation gate as the model's. Measured on 150 real born-digital PDFs (1,336 pages, As of 2026-09-18): 98.4% of pages were groomed with their words proven unchanged, the rest kept their fidelity text, and the pass took about 50 ms a page.

### `image_description`

```yaml
  image_description:
    endpoint: local-vlm
    model: qwen3-vl:8b
    applies_to: [image]            # figure-only PDF pages are not described; nothing measured asks for it yet
    prompt: default
    max_words: 200
```

### `audio_cleanup`

```yaml
  audio_cleanup:
    provider: auphonic             # auphonic | elevenlabs-isolate | command
    endpoint: auphonic
    preset: ~/.config/drawbridge/auphonic/leveling-only.json   # provider algorithm JSON, as in `transcribe`
    settings:                      # inline overrides of preset fields
      levelerstrength_speech: 110
    keep_adjusted_audio: true      # keep the processed file beside the mirror
    output_format: mp3
    bitrate_kbps: 128
```

The `transcribe` project's measured result (2026-08-29) is the starting preset: speech leveling only at strength 110, denoise, dereverb, filtering, normalisation and every cutter off, because gentle denoise introduced substantive word substitutions in the transcript while barely improving level balance. ElevenLabs Voice Isolator is a batch cloud alternative; local candidates are DeepFilterNet or RNNoise behind a `command` endpoint, or plain ffmpeg filters.

### `transcription`

```yaml
  transcription:
    provider: elevenlabs           # elevenlabs | openai-compatible | command
    endpoint: scribe
    model: scribe_v2
    language: auto                 # ISO-639 code or auto
    diarization:
      mode: auto                   # auto | max_speakers | off
      threshold: 0.22
      max_speakers: null
    timestamps: word               # word | segment | none
    verbatim: true
    audio_events: false
    keep_raw_response: true        # the complete provider JSON is retained beside the mirror
    max_duration_minutes: 240
```

The defaults are the ones `transcribe` settled on after its comparison: Scribe v2, automatic speaker count, threshold 0.22, word timestamps, verbatim on, audio events off. A `command` provider covers local whisper.cpp or faster-whisper with a diarization sidecar; an `openai-compatible` provider covers hosted Whisper-style endpoints. The transcript mirror follows the same contract as a PDF mirror: an H1, then one section per speaker turn carrying its timestamp, with the raw response kept for re-rendering.

### `transcript_refinement`

```yaml
  transcript_refinement:
    endpoint: openrouter
    model: anthropic/claude-sonnet-5
    mode: annotate                 # proposals only: speaker merges, boundary moves, paragraph breaks
    preservation: strict
    speaker_resolution: propose    # propose | off; identities are never asserted without review
```

This stage never rewrites words either. It applies paragraph breaks between sentences, under the word gate, and proposes speaker cluster merges, turn boundary moves and spelling corrections, each tied to a time so a reviewer can listen. The model sees provider identities only and answers in numbers and identities; code writes the proposal sentences, so no proposal can assert who someone is. That mirrors the `transcribe` project's human-in-the-loop brief: diarization output is a hypothesis, and identity assignment stays with a person.

## Activation and the CLI

The rule: a stage runs when its key is present in the resolved profile, the input's media type is in the stage's `applies_to`, and no CLI option excludes it.

| Option | Effect |
|---|---|
| `--profile PATH`, `--no-profile` | Select or suppress the profile |
| `--stages ocr,structure` | Run only the named stages (others present in the profile are skipped) |
| `--skip transcription` | Skip named stages |
| `--no-ai` | Run no model-backed stage; deterministic passes still run |
| `--local-only` | Refuse any stage whose endpoint declares `egress: cloud` |
| `--set stages.ocr.model=...` | Override one resolved key for this run; repeatable |
| `--dry-run` | Print the resolved plan and exit: which stages, which endpoints, which will send bytes off the machine, which keys are set; no calls, no writes |

`drawbridge profile show` prints the resolved profile with secrets redacted; `drawbridge profile check` validates the schema, confirms every referenced endpoint exists and its key variable is set, and optionally probes each endpoint with a no-cost request.

Validation is fail-closed: an unknown key, an endpoint reference that does not resolve, or a stage applied to a media type it cannot act on is an error at load time, not a surprise mid-run.

## Provenance

Every stage that runs appends one entry to the mirror header's `processing` list, in order:

```yaml
processing:
- seq: 1
  method: ocr:vlm:qwen/qwen3-vl-32b-instruct
  endpoint: openrouter
  egress: cloud
  performed_at: 2026-09-15T02:11:04Z
  agent: drawbridge
- seq: 2
  method: structure:annotate:anthropic/claude-sonnet-5
  endpoint: openrouter
  egress: cloud
  preservation: strict
  performed_at: 2026-09-15T02:11:40Z
  agent: drawbridge
```

Artifacts stay separate. The fidelity mirror (`<name>.md`) is what the OCR and transcription stages produce, hashed against the input. A structure pass writes `<name>.semantic.md` with a `derived_from` field carrying the fidelity mirror's content hash and the same `## Page N` sections, so anchors still resolve. Cleaned audio, raw provider responses and searchable PDFs sit beside them under their own names. Pages or turns a model stage could not process fall back to the fidelity text and are listed in `verify`, so a mirror is never silently half-enhanced.

## Costs and caching

```yaml
limits:
  max_pages_per_document: 500
  max_audio_minutes: 240
  cache_dir: ~/.cache/drawbridge
```

Model outputs are cached under `cache_dir` keyed by the input content hash, the page number, the stage, the model and the prompt hash, so a re-run after a local edit does not pay twice. The plan printed by `--dry-run` includes page and minute counts so the user can see the size of a job before it starts. Per-call cost accounting is out of scope for the first version; the raw responses retained beside each artifact make it possible later.

## A complete example

```yaml
# ~/.config/drawbridge/profile.yaml
endpoints:
  openrouter:
    kind: openai-compatible
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    egress: cloud
  scribe:
    kind: elevenlabs
    api_key_env: ELEVENLABS_API_KEY
    egress: cloud
  auphonic:
    kind: auphonic
    api_key_env: AUPHONIC_API_KEY
    egress: cloud

stages:
  ocr:
    engine: tesseract              # keep recognition local; the profile can still add structure on top
  structure:
    endpoint: openrouter
    model: anthropic/claude-sonnet-5
    applies_to: [pdf-scan-page]
    mode: annotate
    preservation: strict
  audio_cleanup:
    provider: auphonic
    endpoint: auphonic
    preset: ~/.config/drawbridge/auphonic/leveling-only.json
  transcription:
    provider: elevenlabs
    endpoint: scribe
    model: scribe_v2
    diarization: {mode: auto, threshold: 0.22}

limits:
  max_pages_per_document: 500
  cache_dir: ~/.cache/drawbridge
```

With this profile, `drawbridge convert scan.pdf` OCRs locally and then restores structure through the cloud model; `drawbridge convert scan.pdf --no-ai` produces today's fidelity mirror; `drawbridge convert call.m4a` levels the audio at Auphonic and transcribes at ElevenLabs; `drawbridge convert call.m4a --local-only` refuses with a plan showing the two cloud stages it would have run.

## Implementation order

1. Profile loading, schema validation, `.env` handling, `--dry-run` plan, `profile show` and `profile check`. No stage yet. This makes the activation and egress rules real before any endpoint exists.
2. `structure` with the deterministic native pass and `mode: annotate` for OCR'd pages through the `openai-compatible` adapter. This establishes the semantic artifact and the preservation gate.
3. `ocr` with `engine: vlm` through the same adapter, then `command`.
4. `transcription` and `audio_cleanup`, porting the `transcribe` project's provider code and presets.
5. `image_description` and `transcript_refinement`.

## Sources for the candidate lists

Retrieved 2026-09-15; the schema does not depend on them.

- Roboflow, "Best Open-Source OCR Models in 2026, Ranked by Benchmark": https://blog.roboflow.com/best-open-source-ocr-models/
- Unstract, "Best Open Source OCR Tools & Models for Developers in 2026": https://unstract.com/blog/best-opensource-ocr-tools/
- LlamaIndex, "Best Vision Language Models & Agentic OCR Tools for Developers": https://www.llamaindex.ai/insights/best-vision-language-models
- HunyuanOCR-1.5 technical report: https://arxiv.org/pdf/2607.04884
- Picovoice, "Voice Isolator Guide 2026": https://picovoice.ai/blog/voice-isolator/
- Picovoice, "Noise Suppression Guide 2026": https://picovoice.ai/blog/complete-guide-to-noise-suppression/
- The `transcribe` project's `analysis/recommendation.md` (2026-08-29) for the Auphonic and Scribe v2 settings.
