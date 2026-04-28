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

# 8. Start review UI (each researcher logs in with their language)
afriguard review-ui
# Open http://127.0.0.1:8000
# If port 8000 is busy:
afriguard review-ui --auto-port

# 9. After review — assemble and export dataset
afriguard assemble --version 0.1.0
afriguard export --version 0.1.0

# 10. Check API costs
afriguard cost-report
```

### Environment Safety

AfriGuard only loads `.env` from the project root: `AfriGuard/.env`.
Do not put secrets in `venv/.env`; if you already created that file, move those values into the project-root `.env`.
Existing shell, CI, or Docker environment variables take precedence over `.env` values, so local files cannot silently override deployed secrets.

For the review UI, set `REVIEW_UI_SECRET_KEY` to a random 32+ character value and set each `PASS_*` reviewer password before sharing the URL. Leaving them blank is allowed for local proof-of-concept work, but AfriGuard will warn you and use temporary/default development values.

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

Each researcher logs in at `http://localhost:8000` with their language-specific credentials (set in `.env`). They see only items in their assigned language and can:
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
afriguard review-ui           Start human review web app
afriguard assemble            Build preference/QA/classification items
afriguard export              Export to JSONL files with dataset card
afriguard run-all             Run full pipeline (stops before review)
afriguard run-all --resume    Resume the latest incomplete run
afriguard resume-status       Show autoresume checkpoint status
afriguard cost-report         Show API cost breakdown
```

## Autoresume

`afriguard run-all` writes durable checkpoints to the database for each stage:
`bootstrap_db`, `ingest_seeds`, `generate`, `filter`, and `assign_review`.

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
| `configs/pipeline.yaml` | Languages, batch sizes, severity distribution |
| `configs/harm_taxonomy.yaml` | Full harm taxonomy with legal references |
| `configs/seed_sources.yaml` | Seed dataset registry |
| `configs/models.yaml` | LLM model configs and costs |
| `configs/prompt_templates/` | Per-category prompt templates |
| `.env` | API keys, database URL, reviewer passwords |

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
