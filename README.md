# AfriGuard — Afrocentric Safety-Alignment Data Generation Pipeline

> **From-scratch multilingual safety data for African languages, grounded in African legal context, cultural entities, and Afrocentric seed corpora.**

## Overview

AfriGuard generates culturally authentic safety-alignment datasets for seven African languages:
**Hausa · Sepedi · Chichewa · Northern Sotho · Yao · Yoruba · Shona**

Unlike translation-based approaches, AfriGuard generates data **from scratch** using:
- Afrocentric harm taxonomy grounded in African law (POPIA, VAPP, Sexual Offences Act, Malawi Penal Code)
- Seed datasets from authentic African corpora (AfriSenti, MasakhaNER, MASAKHANEWS, etc.)
- Cultural entity injection (authentic names, places, organizations per language)
- LLM generation with legal + cultural conditioning
- Human review by native-language researchers (one per language)

Methodologically inspired by [PKU-SafeRLHF](https://github.com/PKU-Alignment/safe-rlhf), but adapted for African contexts.

## Quick Start

```bash
# 1. Clone and set up
git clone <repo>
cd AfriGuard
pip install -r requirements.txt

# For contributors running tests/linting:
pip install -r requirements-dev.txt

# 2. Configure
cp .env.example .env
# Edit .env — set OPENAI_API_KEY at minimum

# 3. Initialize database
afriguard bootstrap-db

# 4. Ingest seed data (auto-fetches from HuggingFace)
afriguard ingest-seeds --max-samples 200

# 5. Generate prompts and candidates (PoC: 5 prompts per combination)
afriguard generate --n-prompts 5

# 6. Filter candidates
afriguard filter

# 7. Assign review tasks (auto-escalates S4 items)
afriguard assign-review

# 8. Select the subset researchers will review
afriguard sample-for-review --n-per-language 50

# 9. Start review UI (each researcher logs in with their language)
afriguard review-ui
# Open http://127.0.0.1:8000
# If port 8000 is busy:
afriguard review-ui --auto-port

# 9. After review — assemble and export dataset
afriguard assemble --version 0.1.0
afriguard export --version 0.1.0

# 11. Check API costs
afriguard cost-report
```

### Environment Safety

AfriGuard only loads `.env` from the project root: `AfriGuard/.env`.
Do not put secrets in `venv/.env`; if you already created that file, move those values into the project-root `.env`.
Existing shell, CI, or Docker environment variables take precedence over `.env` values, so local files cannot silently override deployed secrets.

For the review UI, set `REVIEW_UI_SECRET_KEY` to a random 32+ character value before sharing the URL. Language reviewers do not need passwords; they select the language they want to review and are signed in automatically. The `admin` account still requires `PASS_ADMIN`.

For local development, use `REVIEW_UI_HOST=127.0.0.1`. `0.0.0.0` means "listen on all network interfaces" and is not the browser URL; if you bind to `0.0.0.0`, open `http://127.0.0.1:<port>` locally.

### Smoke Test

Windows PowerShell:

```powershell
.\scripts\smoke-test.ps1 -Language shona
```

macOS/Linux:

```bash
bash scripts/smoke-test.sh shona
```

The smoke test installs dependencies, creates `.env` if needed, initializes the database, and runs a dry generation check without calling an LLM API.

## Pipeline Architecture

```
Seeds (HuggingFace + Legal Docs)
    ↓
[Ingestion] → Normalize → Store
    ↓
[Taxonomy] → Harm Categories + Severity + Legal Context + Cultural Entities
    ↓
[Prompt Construction] → System Prompt + User Message (per language/category/severity)
    ↓
[LLM Generation] → N candidate responses (safe + unsafe) per prompt
    ↓
[Filtering] → Language Detection → Quality Score → Similarity → Deduplication
    ↓
[Human Review UI] → Approve / Reject / Flag / Escalate (per language researcher)
    ↓
[Assembly] → Preference Pairs + QA Pairs + Classification Labels
    ↓
[Export] → JSONL + Dataset Card (per language + all-languages)
```

## Harm Taxonomy

11 Afrocentric harm categories (H01–H11):

| ID | Category | Legal Grounding |
|----|----------|-----------------|
| H01 | Hate Speech & Discrimination | PEPUDA (SA), Criminal Code (NG), Malawi Penal Code |
| H02 | Gender-Based Violence & Sexual Offenses | VAPP (NG), Sexual Offences Act (SA), Gender Equality Act (MW) |
| H03 | Privacy Violations | POPIA (SA), NDPA (NG) |
| H04 | Disinformation & Electoral Manipulation | Electoral Acts (NG, SA, MW) |
| H05 | Financial Fraud & Exploitation | EFCC Act (NG), POCA (SA) |
| H06 | Child Safety | Child Rights Act (NG), Children's Act (SA), Child Care Act (MW) |
| H07 | Mental Health & Emotional Harm | — |
| H08 | Harmful Medical Misinformation | — |
| H09 | Violent Extremism | Terrorism Acts (NG, SA, MW) |
| H10 | Harmful Instruction | — |
| H11 | Helpful & Safe (Positive Baseline) | — |

Severity: **S1** (mild) → **S2** (moderate) → **S3** (severe) → **S4** (critical, auto-escalated)

## Review UI

Each researcher opens `http://localhost:8000`, selects the language they want to review, and is signed in automatically. They see only items in their assigned language and can:
- **Approve** — accept the candidate
- **Reject** — remove it from the dataset
- **Flag** — needs discussion
- **Escalate** — send to senior researcher (required for S4)
- Correct harm labels and severity ratings
- Add notes and suggest response edits
- Rank candidates for preference pair creation

## Output Formats

All outputs in `data/releases/<version>/`:

```
releases/0.1.0/
├── all_languages/
│   ├── preference_pairs.jsonl   ← RLHF (chosen/rejected pairs)
│   ├── qa_safe.jsonl            ← SFT safe responses
│   ├── qa_unsafe.jsonl          ← SFT unsafe responses
│   └── classification.jsonl    ← Harm category + severity labels
├── hausa/
│   └── ...
├── yoruba/
│   └── ...
└── dataset_card.json
```

## CLI Reference

```
afriguard bootstrap-db        Initialize database
afriguard ingest-seeds        Fetch seed datasets from HuggingFace + local
afriguard generate            Generate prompts and candidate responses
afriguard filter              Run all filtering stages
afriguard assign-review       Auto-escalate S4 items, print review summary
afriguard sample-for-review   Select subset for researcher review
afriguard review-ui           Start human review web app
afriguard assemble            Build preference/QA/classification items
afriguard export              Export to JSONL files with dataset card
afriguard run-all             Run full pipeline (stops before review)
afriguard run-all --resume    Resume the latest incomplete run
afriguard resume-status       Show autoresume checkpoint status
afriguard cost-report         Show API cost breakdown
```

## Adding Languages

AfriGuard keeps language-specific runtime metadata in `configs/languages.yaml`.
To add another language, add one entry there with:

- `name`, `display_name`, `code`, and `iso_639_3`
- `countries` for legal grounding
- `reviewer_id`
- language aliases for filtering and LLM language checks
- prompt and response language instructions
- low-resource detection flags, if needed

Then add matching seed sources in `configs/seed_sources.yaml`, cultural names and
places in `data/seeds/custom/afriguard_lexicon.json`, and an annotation guideline
file for the reviewer. Most runtime behavior now reads
from `configs/languages.yaml`, so adding a language no longer requires editing
prompt construction, filtering, generation, or review-assignment code.

## Editing Prompts

Frequently changed prompt wording lives in
`configs/prompt_templates/prompt_templates.yaml`.

Use that file to tune:

- severity wording for `S1` through `S4`
- the prompt-generation system template
- the prompt-generation user message
- safe response instructions
- unsafe response instructions
- response-generation formatting rules

Keep placeholder names such as `{language_instruction}`, `{harm_category_name}`,
`{severity_frame}`, `{legal_context}`, `{seed_context}`, and
`{role_instruction}` unchanged unless you also update the renderer in
`src/prompt_construction/prompt_builder.py`. Every rendered system prompt is
content-hashed and stored with the generated data for reproducibility.

## Editing Filtering Policy

Frequently tuned filtering thresholds live in `configs/filtering.yaml`.

Use that file to change:

- minimum candidate quality score
- within-prompt similarity threshold
- cross-batch deduplication threshold
- ordinary language-detection threshold
- low-resource language-detection threshold
- language detector minimum text length

Environment variables in `.env` can still override these defaults for a
particular deployment, but the project-level policy should be changed in
`configs/filtering.yaml`.

## Editing Review Sampling

Frequently tuned human-review sampling settings live in
`configs/review_sampling.yaml`.

Use that file to change:

- number of candidates sampled per language
- fraction of the review quota reserved for borderline cases
- quality-score margin used to decide what counts as borderline

The CLI can still override these values for one-off runs:

```bash
afriguard sample-for-review --language shona --n-per-language 10 --borderline-fraction 0.3
```

## Editing Generation Policy

Generation defaults live in `configs/generation.yaml`.

By default, each generated prompt gets an even mix of safe/helpful and
unsafe/contrast candidate responses. Change `candidate_mix.safe_fraction` if
you want more safe responses for QA-style data or more unsafe responses for
preference-pair contrast.

Use the same file to change the default model, candidates per prompt, and
prompt/response generation temperature and token limits.

## Editing Legal Grounding

Legal grounding policy lives in `configs/legal_grounding.yaml`.

Use that file to turn legal context on or off, control fallback behavior, and
cap how much legal context is injected into prompts. The legal content itself
still comes from `src/prompt_construction/legal_grounder.py`,
`configs/harm_taxonomy.yaml`, and legal seed sources in `configs/seed_sources.yaml`.

## Editing Seed Context

Seed-context injection policy lives in `configs/seed_context.yaml`.

Use that file to change how many seed documents are injected per prompt, how
long each excerpt can be, whether seed order is shuffled, and whether generation
can fall back to general same-language seeds when category-specific seeds are
missing.

## Editing Export Policy

Export policy lives in `configs/export.yaml`.

Use that file to choose whether releases include AfriGuard-native JSONL files,
PKU-style compatibility files, all-language combined files, and the dataset
card. The default remains to export all supported formats.

## Editing Review UI Text

Reviewer-facing UI labels and instructions live in `configs/review_ui.yaml`.

Use that file to change login text, queue labels, empty-state messaging,
review-session instructions, and the number of prompt groups shown per page.

## Autoresume

`afriguard run-all` writes durable checkpoints to the database for each stage:
`bootstrap_db`, `ingest_seeds`, `generate`, `filter`, `assign_review`, and
`sample_for_review`.

If a run fails, resume it with:

```bash
afriguard run-all --resume --run-id <RUN_ID>
```

If you omit `--run-id`, AfriGuard resumes the latest incomplete run:

```bash
afriguard run-all --resume
```

Check progress with:

```bash
afriguard resume-status --run-id <RUN_ID>
```

## Running Tests

```bash
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest --cov=src --cov-report=term-missing
```

## Configuration

| File | Purpose |
|------|---------|
| `configs/pipeline.yaml` | Batch sizes, active harm categories, severity distribution |
| `configs/languages.yaml` | Central language metadata, reviewer IDs, aliases, legal countries, language instructions |
| `configs/prompt_templates/prompt_templates.yaml` | Prompt-generation and response-generation templates |
| `configs/generation.yaml` | Default model, generation parameters, and safe/unsafe candidate response mix |
| `configs/filtering.yaml` | Quality, similarity, deduplication, and language-detection thresholds |
| `configs/legal_grounding.yaml` | Legal context injection and fallback policy |
| `configs/seed_context.yaml` | Seed excerpt count, length, fallback, and shuffle policy |
| `configs/export.yaml` | Native, PKU-style, all-language, and dataset-card export policy |
| `configs/review_ui.yaml` | Reviewer UI labels, instructions, and task page size |
| `configs/review_sampling.yaml` | Human-review sample size and borderline sampling policy |
| `configs/harm_taxonomy.yaml` | Full harm taxonomy with legal references |
| `configs/seed_sources.yaml` | Seed dataset registry |
| `configs/models.yaml` | LLM model configs and costs |
| `configs/prompt_templates/` | Per-category prompt templates |
| `.env` | API keys, database URL, review UI secret, admin password |

## Repository Structure

```
AfriGuard/
├── src/
│   ├── schemas/           Pydantic data models
│   ├── storage/           SQLAlchemy ORM + object store
│   ├── ingestion/         Seed dataset fetching + normalization
│   ├── taxonomy/          Harm registry + cultural entity sampler
│   ├── prompt_construction/ System prompt assembly
│   ├── generation/        LLM generation + cost tracking
│   ├── filtering/         Language detection, quality, similarity, dedup
│   ├── review/            FastAPI review UI + task assignment
│   ├── assembly/          Dataset item building + export
│   ├── pipeline/          CLI DAG (afriguard command)
│   └── observability/     Structured logging + metrics
├── configs/               YAML configuration files
├── tests/                 Unit + integration tests
├── data/                  Seed data + generated outputs (DVC tracked)
└── docs/                  Architecture + annotation guidelines
```

## Citation

If you use AfriGuard data in your research, please cite:

```bibtex
@dataset{afriguard2024,
  title={AfriGuard: Afrocentric Safety-Alignment Dataset},
  author={AfriGuard Research Team, DSFSI},
  year={2024},
  note={Multilingual safety-alignment data for African languages}
}
```

## License

Code: MIT  
Dataset: CC BY 4.0
