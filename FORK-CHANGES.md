# Fork Changes

Documentation of changes in this fork relative to upstream `ptmrio/autorename-pdf`.

Every measurement in this document was taken on the machine this fork was
developed on: an RTX 3060 (12 GB) running Ollama 0.32.9 with `qwen3.5:9B`
(Q4_K_M). Example filenames and document contents have been genericised.

| Commit | Change |
|--------|--------|
| `4dc7886` | Fix Ollama reasoning models exhausting context before emitting JSON |
| `1ab58b1` | Make the output filename layout configurable |
| `4926060` | Normalize extracted person names and document Ollama's context ceiling |

---

## 1. Ollama reasoning models never produced output

### Symptom

Every PDF failed with a message that pointed in entirely the wrong direction:

```
[1/1] receipt.pdf
  ✓ Text extracted quality 0.99
  ✓ PaddleOCR
  ERROR - Error processing receipt.pdf: The output is incomplete due to a max_tokens length limit.
  ✗ The output is incomplete due to a max_tokens length limit.
```

Text extraction and OCR both succeeded. The failure was entirely in the AI step.

### Root cause

The message is `instructor`'s `IncompleteOutputException`, raised whenever the
provider returns `finish_reason == "length"`. Nothing in the codebase sets
`max_tokens` for Ollama — `_ai_processing.py` only set it for Anthropic, whose
API requires it. The real limit was Ollama's context window.

Reproduced against the raw endpoint:

```
finish_reason: length
usage: {prompt_tokens: 1229, completion_tokens: 2867, total_tokens: 4096}
content len: 0
reasoning_content len: 0
```

`1229 + 2867 = 4096` exactly, with **zero** characters of content produced.

`qwen3.5:9B` is a hybrid-reasoning model (`capabilities: [completion, vision,
tools, thinking]`). Ollama loads every model with a **4096-token default
context**, irrespective of what the model supports — this model declares
`qwen35.context_length: 262144`, i.e. 256K, so it was running at 1/64th of its
capacity. The prompt consumed 1,229 tokens and the model spent every one of the
remaining ~2,867 on `<think>` tokens, getting truncated mid-reasoning before it
emitted a single character of JSON.

Verified the 4096 figure is a runtime default rather than a model limit:

| Evidence | Value |
|---|---|
| Model's declared capacity (`qwen35.context_length`) | 262144 |
| `num_ctx` in the model's own Modelfile parameters | absent |
| `OLLAMA_*` environment variables set on the host | none |
| Loaded with defaults, then `/api/ps` | `context_length: 4096` |

### Why the obvious fixes don't work

- **Raising `num_ctx` per request.** Ollama's OpenAI-compatible endpoint
  silently ignores it — tested both as a top-level key and nested under
  `options`, still capped at exactly 4096. Only the native `/api/chat` endpoint
  honours it. Since every non-Anthropic provider in this codebase routes through
  the OpenAI SDK, this lever is unavailable from here.
- **`chat_template_kwargs: {enable_thinking: false}`.** Ignored by this model;
  the request still returned 2,867 completion tokens and `finish_reason: length`.
- **Reducing the reasoning budget.** `reasoning_effort` of `low` and `medium`
  both still fail with the identical exception, at ~63s per attempt. The setting
  is effectively binary at this context size.

### Fix

Added an `ai.reasoning_effort` config key, applied only to the `ollama`
provider, defaulting to `"none"`:

```yaml
ai:
  reasoning_effort: "none"    # "" re-enables thinking
```

Result on the same document: **26 completion tokens, `finish_reason: stop`**,
correct extraction, effectively instant.

The three duplicated `if provider == "anthropic": kwargs["max_tokens"] = 1024`
blocks were folded into a single `_apply_provider_kwargs()` helper that now
handles both provider quirks in one place.

### Compatibility

Only affects `ollama`. Other providers are untouched. Setting
`reasoning_effort: ""` restores the previous behaviour for anyone running a
model that needs to think.

---

## 2. The output filename layout is now configurable

### Problem

The filename was produced by a single hardcoded f-string in
`_document_processing.py`:

```python
base_name = f'{document_date.strftime(date_format)} {company_name} {document_type}'
```

Field order, the single-space separator, and which three fields appeared were
all fixed. `output.date_format` was the only configurable part.

### Design

Added `output.filename_template` with six placeholders:

| Placeholder | Source |
|---|---|
| `{date}` | parsed document date, formatted with `date_format` |
| `{company}` | the counterparty (your own company is deliberately excluded) |
| `{type}` | `ER` / `AR` for invoices, otherwise a short description |
| `{recipient}` | the party the document is addressed to |
| `{sender}` | the party that issued the document |
| `{amount}` | total including currency |

The default is `"{date} {company} {type}"`, which reproduces the previous
layout exactly. **Existing setups are unaffected.**

### Extended fields are requested on demand

`{recipient}`, `{sender}` and `{amount}` are new AI-extracted fields. Asking for
them costs tokens on every call and gives a small model more ways to fail, so
they are only added to the response model and the prompt when the configured
template actually references them. `get_metadata_model()` returns either
`DocumentMetadata` (3 fields) or `DocumentMetadataExtended` (6 fields)
accordingly. Anyone on the default template pays nothing.

### Prompt ordering matters more than expected

The extended-field instructions must be emitted **before** the trailing
`"If a value is not found, leave it empty."` sentence. Placed after it, smaller
local models read that sentence as permission to skip the new fields and return
them empty every time. Moving three paragraphs above one sentence took
`sender` and `amount` from never populating to populating reliably.

This is not hypothetical. A bisection of the system prompt found two
independent triggers that each, alone, caused `company_name` to come back empty
on a model with thinking disabled:

- the `ER`/`AR` block inside the `document_type` instructions
- the trailing `"If a value is not found, leave it empty."`

Removing either one restored extraction. The interaction only appears when
`company.name` is set; with it blank, extraction worked regardless.

### Behaviours

- **Empty fields collapse their separators.** A template of
  `"{date} - {recipient} - {sender} - {amount}"` with no recipient and no
  amount yields `20260326 - Example Airlines.pdf`, not
  `20260326 -  - Example Airlines - .pdf`.
- **Truncation is generalised.** The 244-character budget (255 max, less
  `.pdf`, less a `_(999)` disambiguator) previously assumed `company_name` was
  the field to shorten. It now shortens whichever field is longest, repeatedly,
  and never trims `{date}` — a partial date is worse than a partial name.
- **Unknown placeholders render empty rather than raising**, so a typo degrades
  one filename instead of failing an entire batch.
- **`config validate` reports template problems:**
  ```
  "Unknown placeholder(s) ['bogus'] will render empty.
   Available: ['date', 'company', 'type', 'recipient', 'sender', 'amount']"
  ```
  A template with no placeholders at all is a hard **error**, since every file
  would collide on a single name.

### Blast radius

`rename_invoice()` gained three keyword-only parameters (`recipient`, `sender`,
`amount`), all defaulting to `""`, so existing call sites are unaffected. The
CLI's JSON output gained three matching optional fields, and
`gui/src/lib/sidecar.ts` declares them as optional so the Tauri GUI type-checks
against the richer payload.

---

## 3. Person-name normalization

Documents name people in whatever form the source uses — airline receipts use
`LASTNAME/FIRSTNAME`. `sanitize_filename()` then strips the forbidden `/`,
producing `LASTNAMEFIRSTNAME` in the filename. The `recipient` instruction now
asks for `"First Last"` in normal capitalisation.

This mostly matters for non-reasoning models; with thinking enabled the model
already produced the normalised form unprompted.

---

## Configuration and runtime setup

These live outside git (`config.yaml` is gitignored) but are needed to
reproduce the results above.

### Ollama's context ceiling

`num_ctx` cannot be raised through the OpenAI-compatible endpoint, and the
`OLLAMA_CONTEXT_LENGTH` environment variable changes the default for *every*
model on the host and requires restarting the Ollama app. A derived model is
narrower in scope and needs no restart:

```
printf 'FROM qwen3.5:9B\nPARAMETER num_ctx 16384\n' > Modelfile
ollama create mymodel-16k -f Modelfile
```

This reuses the existing weights — no re-download. Confirm it took effect by
loading the model and checking `/api/ps` for `context_length: 16384`. The
derived model inherits all capabilities of its parent, including vision.

Then:

```yaml
ai:
  model: "mymodel-16k"
  reasoning_effort: ""      # thinking ON
```

### Recommended: `pdf.ocr: "auto"`

Upstream's `ocr: true` means *always*, so PaddleOCR runs even on a PDF whose
text layer scores 0.99 quality. Both texts are then concatenated and the model
receives the same document twice. Switching to `"auto"` (run only when text
quality falls below `text_quality_threshold`) cut the prompt from **1,229 to
789 tokens** on a one-page receipt and removed a 2-5s pass per page.

Note the tradeoff in principle: text quality measures the text layer's
*legibility*, not its *completeness*, so a document could score well while
still omitting something only OCR would recover. That did not occur in testing
here — the fields being extracted were present in the text layer — but the
distinction is worth keeping in mind before setting `"auto"` on a corpus of
scanned documents.

---

## Performance

Same one-page receipt, warm model, `num_ctx 16384`:

| Phase | thinking OFF | thinking ON |
|---|---|---|
| model load | 0.2s | 0.2s |
| prompt processing | 0.2s (789 tok) | 1.6s (3,473 tok) |
| answer generation | 1.4s (69 tok) | 1.5s (77 tok) |
| unaccounted (reasoning) | — | ~51s |
| **total** | **1.8s** | **54.1s** |

Answer generation is essentially identical — 69 vs 77 tokens. The entire
difference is the reasoning pass, which is **invisible in Ollama's counters**.
Two clues expose it: the response carried 10,654 characters of `thinking`
(~2,700 tokens, roughly 35x the size of the answer), and `prompt_eval_count`
jumped from 789 to 3,473 — the original prompt plus that reasoning fed back in.

Structured output with thinking is therefore a **two-pass operation**: the model
reasons freely, then the reasoning is appended to the prompt and re-processed to
generate the schema-constrained JSON. `eval_count` only covers the second pass,
which is why the reported timings never add up.

Expect roughly **55-120s per file** with thinking enabled — reasoning length
varies by document — against ~2-5s with it disabled.

---

## Known limitations

- **`{recipient}` reliability depends on the model.** With thinking disabled,
  `qwen3.5:9B` returns it empty even when the document plainly contains the
  data. Curiously, the *smaller* `qwen3:4b` fills it under the same conditions,
  so this is not a model-capacity problem — parameter count is not the axis that
  matters here, reasoning is.
- **Formatting consistency degrades without reasoning.** Across four receipts
  with thinking off, a person's name came back in three different forms and the
  legal form (`, Inc.`) was stripped inconsistently. With thinking on, all four
  were identical and correct.
- **`harmonized-company-names.yaml` only normalises `company_name`.** It does
  not apply to `{sender}` or `{recipient}`.
- **The default `presence_penalty 1.5`** inherited from qwen3.5's Modelfile is
  aggressive and may lengthen reasoning. Untested.

---

## Testing

```
330 passed, 36 skipped
```

12 new tests cover template rendering, separator collapsing, the length budget,
unknown placeholders, missing dates, and forbidden-character sanitisation of the
new fields.

Test fixtures are gitignored (`*.pdf`) and must be generated before the
extraction fixture tests will pass — without them 30 tests fail on missing
files:

```
python tests/generate_test_pdfs.py
```

---

## Files changed

| File | Change |
|---|---|
| `_utils.py` | Template constants, placeholder inspection, `render_filename_template()` |
| `_ai_processing.py` | `_apply_provider_kwargs()`, `DocumentMetadataExtended`, `get_metadata_model()`, conditional prompt sections |
| `_document_processing.py` | Templated filename construction, generalised `_fit_to_budget()` |
| `_config_loader.py` | `ai.reasoning_effort` and `output.filename_template` defaults |
| `autorename-pdf.py` | New result fields, template validation in `config validate` |
| `config.yaml.example` | Documents both new keys and the Ollama context ceiling |
| `gui/src/lib/sidecar.ts` | Optional `recipient` / `sender` / `amount` on the result type |
| `tests/test_document_processing.py` | 12 new tests |
