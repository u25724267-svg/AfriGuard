# AfriGuard Methodology Report

**Working title:** PKU-Inspired African Safety Dataset Generation  
**Date:** May 2026  
**Purpose:** Peer discussion before the first OpenAI Batch API submission  
**Status:** Emergency pilot plan plus longer-term governed scale-up

---

## 1. Executive Summary

AfriGuard is building a safety-alignment dataset for African languages. The core problem we are addressing is that most multilingual safety datasets are English-first, translated, or culturally thin. This often produces text that may be technically in the target language but still carries English syntax, Western assumptions, and non-local harm scenarios.

Our approach is to use PKU-SafeRLHF prompts as **safety-intent source material**, not as final text. We then inject African seed context and generate fresh prompts directly in the target language.

The full target is a tiered 40-language African safety dataset. Because our OpenAI credits expire in three days, we are proposing a pragmatic two-track strategy:

1. **Emergency internal pilot batch now**
   - Use currently configured languages.
   - Use existing seed and legal/civic context.
   - Generate raw internal data.
   - Mark all outputs as requiring filtering and human review.

2. **Governed scale-up after the first batch**
   - Add formal seed governance.
   - Build a seed-readiness matrix.
   - Expand toward the 40-language target only where seed coverage and review capacity are adequate.

The guiding principle is:

> Batch now for internal raw generation; govern before public release.

---

## 2. A/B Test At A Glance

The first batch should not only generate data; it should compare generation strategies.

Our primary A/B test compares:

| Method | Strategy | What it tests |
|---|---|---|
| A | PKU + Context Injection Regeneration | Can we preserve PKU safety intent while generating a fresh African-language prompt grounded in local context? |
| B | Seed-Anchored Self-Instruct | Can we generate more native-sounding safety prompts directly from African seed context without PKU wording? |

For tonight, the recommended small A/B pilot is:

| Dimension | Choice |
|---|---|
| Languages | Hausa, Yoruba, Shona |
| Methods | A and B |
| Categories | H01-H06 |
| Severities | S1-S3 |
| Source prompts | 5 per combination |
| Approximate size | 540 requests |

The goal is to quickly learn whether the strongest first-wave strategy is:

- **Method A:** PKU safety intent + African context -> regenerated target-language prompt
- **Method B:** African seed context + harm category -> target-language prompt

We will compare methods by accepted-item yield after language checks, structure checks, category/severity checks, duplicate filtering, and human review.

---

## 3. Dataset Goal

AfriGuard aims to generate three kinds of safety data:

| Output | Purpose |
|---|---|
| African-language safety prompts | Test whether models understand local harm scenarios |
| Safe and unsafe candidate responses | Build QA, SFT, and preference-style data |
| Structured labels and provenance | Support filtering, review, evaluation, and export |

Each generated item should preserve:

- target language
- harm category
- severity
- generation method
- model used
- PKU source prompt ID
- seed sources used
- batch/run ID
- filtering and review status

The final dataset can support safety classification, response generation, refusal evaluation, preference-pair construction, multilingual benchmarking, and African-context safety evaluation.

---

## 4. Methodological Foundation

PKU-SafeRLHF gives us a large bank of safety-relevant source prompts. The paper reports 44.6k refined prompts, 265k question-answer pairs, 19 harm categories, three severity levels, and 166.8k preference annotations.

We are not copying PKU outputs directly. We use PKU prompts as source intent:

| Step | Description |
|---|---|
| Source intent | Take a PKU prompt and identify the safety-testing intent |
| Taxonomy mapping | Map it to AfriGuard harm categories and severity |
| Context injection | Add African seed, legal, entity, and cultural context |
| Native generation | Generate a new prompt directly in the target language |
| Candidate generation | Generate safe and unsafe responses where needed |
| Filtering/review | Validate language, safety labels, quality, and cultural fit |

The crucial distinction is that AfriGuard is **not a translation pipeline**.

We do not want:

> English harmful prompt -> machine translation

We want:

> PKU safety intent -> African seed context -> native target-language prompt

---

## 5. Language Scope

The full planning target is 40 African languages, organized into tiers. The tiering is meant to prevent us from treating all languages as equally ready.

### Tier 1: First Wave

Swahili, Hausa, Yoruba, Igbo, Amharic, Oromo, Somali, Shona, Kinyarwanda, Tigrinya, Zulu, Xhosa, Nigerian Pidgin, Akan/Twi, Lingala.

### Tier 2: Second Wave

Luganda, Kirundi, Bambara, Wolof, Fulfulde, Moore, Ewe, Kikuyu, Dholuo, Chichewa, Bemba, Sesotho, Setswana, Sepedi/Northern Sotho, Xitsonga.

### Tier 3: Targeted Acquisition

Tshivenda, Malagasy, Kikongo, Tshiluba, Dinka, Kanuri, Tiv, Ibibio/Efik, Mandinka, Yao.

### Emergency Batch Languages

For the first emergency batch, we should use languages already configured in the current pipeline:

- Hausa
- Yoruba
- Shona
- Chichewa
- Sepedi / Northern Sotho
- Yao

This is not because the other languages are unimportant. It is because they do not yet have runtime language instructions, seed coverage, filtering support, and reviewer setup in the repo.

---

## 6. Harm Taxonomy

AfriGuard currently uses 11 harm categories:

| ID | Category |
|---|---|
| H01 | Hate Speech & Discrimination |
| H02 | Gender-Based Violence & Sexual Offenses |
| H03 | Privacy Violations |
| H04 | Disinformation & Electoral Manipulation |
| H05 | Financial Fraud & Exploitation |
| H06 | Child Safety |
| H07 | Mental Health & Emotional Harm |
| H08 | Harmful Medical Misinformation |
| H09 | Violent Extremism |
| H10 | Harmful Instruction |
| H11 | Helpful & Safe / Positive Baseline |

Severity levels are S1 to S4:

| Severity | Meaning |
|---|---|
| S1 | Mild |
| S2 | Moderate |
| S3 | Severe |
| S4 | Critical / highest-risk |

---

## 7. Seed Data Strategy

Seed data is what makes this African-context data rather than translated English data.

We need multiple seed types:

| Seed type | Purpose |
|---|---|
| Native text | Teaches natural language style and register |
| Entity seeds | Names, places, institutions, organizations, currencies |
| Legal/civic context | Local laws, regulators, courts, helplines, rights, enforcement realities |
| Harm-domain context | Local patterns for fraud, extremism, cybercrime, GBV, child safety, misinformation |
| Social/informal register | How people write emotionally, informally, or socially |
| Spoken register | Oral syntax, code-switching, conversational structure |
| Manual lexicons | Human-curated culturally important terms |

Seed data should be ingested before batch generation. The Batch API should receive self-contained requests containing selected excerpts, not links to external sources.

### Current Strongest Coverage

Current repo coverage is strongest for:

- Shona
- Hausa
- Yoruba
- Sepedi / Northern Sotho
- Chichewa
- Yao

Shona is especially strong on Zimbabwe legal/civic context because we have already added several Zimbabwe legal seed files.

### Important Source Families

| Source family | Value | Governance decision |
|---|---|---|
| MasakhaNEWS | African news/context | Useful, but avoid overuse |
| MasakhaNER | Entities | Strong entity source |
| AfriSenti / NaijaSenti | Social/sentiment register | Internal analysis only unless legal clearance exists |
| MAFAND / NLLB / FLORES / HornMT | Translation/parallel corpora | Entity or orthography reference only, not style seeds |
| WURA | Native African-language web/news text | High-value, but validate per language |
| AfricanLII / legal portals | Legal/civic grounding | First-class source layer |
| ACLED / ISS / ECPAT / FATF-type reports | Harm-domain context | Context/entity use, usually English/French |
| SALT / ALFFA | Spoken register | Valuable but requires transcript-quality filtering |
| Wikidata | Structured entities | Useful but requires careful query design |
| Manual lexicons | Low-resource language grounding | Essential for weaker seed languages |

### Seed Governance Rule

Before full release-scale generation, every active seed source should declare:

- permitted uses
- source cluster
- acquisition status
- legal status
- whether selection is allowed
- whether public export is allowed
- validation status

This prevents risky or inappropriate sources from silently entering public dataset lineage.

Examples:

- Social-media-derived datasets should not be injected as raw prompt context without legal clearance.
- Parallel translation corpora should not be used as style seeds.
- Legal/civic sources should be structured and reviewed, not treated as generic prose.

---

## 8. Seed Readiness Matrix

Before scaling to all 40 languages, we need a seed-readiness matrix.

Rows are languages. Columns are seed types:

- native text
- entity
- legal/civic
- harm context
- social/informal register
- spoken register
- manual lexicon

Each cell should be:

| Status | Meaning |
|---|---|
| Green | Source exists, acquired, validated, selectable |
| Yellow | Partial coverage or English-only context |
| Red | No usable source |
| Internal | Useful internally but cannot enter public lineage |

This matrix should decide which languages are ready, partial, or blocked.

| Readiness | Requirement | Action |
|---|---|---|
| Ready | Native text + entity + legal/civic or harm context | Full generation allowed |
| Partial | Native text exists but legal/civic or review coverage is weak | Reduced generation, extra review |
| Blocked | No native text or only translation-derived text | No generation until more seed work |

---

## 9. Generation A/B Testing Methodology

We should not bet on one generation strategy. We will compare multiple methods.

### Method A: PKU + Context Injection Regeneration

This is the primary operating mode.

The model receives a PKU prompt as safety intent, African seed/legal/entity context, and target-language instructions. It then generates a new prompt directly in the target language.

This is not translation. It is regeneration from safety intent plus African grounding.

Strengths:

- preserves PKU safety intent
- supports cross-language comparison
- uses local context
- easiest to operationalize quickly

Risks:

- may still become too close to the PKU source
- may inherit non-African assumptions
- needs copying/translation filters

### Method B: Seed-Anchored Self-Instruct

The model receives African seed context and harm-category requirements, but no PKU wording. It generates a safety prompt directly from local context.

Strengths:

- may sound more native
- lower translationese risk
- useful when PKU prompts are culturally distant

Risks:

- weaker comparability to PKU
- harm intent may drift
- requires stronger category checks

### Method C: Entity / Legal Scenario Generation

The model generates prompts from structured entities, institutions, laws, and harm-domain facts.

Strengths:

- strong provenance
- good for privacy, fraud, elections, child safety, GBV, and legal/civic categories
- easier to audit than vague context

Risks:

- can feel templated
- depends on accurate legal/civic summaries
- requires legal review

### Method D: Pivot / Code-Switch Controlled

The model uses a regional or high-resource pivot only as scaffolding, then produces final output in the target language with controlled natural code-switching where appropriate.

Strengths:

- useful for low-resource languages
- handles modern technical/legal terms
- reflects real multilingual communication

Risks:

- may overuse English or pivot-language structure
- needs language-specific code-switching rules
- requires heavier human review

### Emergency A/B Recommendation

For tonight, a small but meaningful A/B test should use:

| Dimension | Choice |
|---|---|
| Languages | Hausa, Yoruba, Shona |
| Methods | Method A and Method B |
| Categories | H01-H06 |
| Severities | S1-S3 |
| Source prompts | 5 per combination |

This gives roughly 540 requests. It is small enough to submit quickly and large enough to tell us whether PKU-context regeneration or seed-anchored generation is the better first-wave strategy.

Success should be judged by accepted-item yield, not raw generation count. We care about how many items survive language checks, structure checks, category/severity checks, duplicate filtering, and human review.

---

## 10. Batch Strategy

The long-term architecture should be batch-first:

1. ingest seeds
2. ingest PKU prompts
3. prepare JSONL batch requests
4. submit batch
5. sync results
6. filter and review
7. export

Each batch item needs a stable custom ID so results can be matched back to language, category, severity, source prompt, seed context, generation method, and model.

### Emergency Batch

Because credits expire soon, the first batch should be internal and raw. We should not wait for perfect governance.

Recommended first-batch options:

| Scope | Size |
|---|---|
| Conservative | 3 languages x 11 categories x 4 severities x 10 prompts = 1,320 requests |
| A/B pilot | 3 languages x 6 categories x 3 severities x 5 prompts x 2 methods = 540 requests |
| Broader configured-language batch | 6 language targets x 11 categories x 4 severities x 10 prompts = 2,640 requests |

For tonight, the A/B pilot is the cleanest scientific option. The broader batch is better if the immediate goal is to maximize raw generation volume before credit expiry.

All emergency outputs should be marked:

- internal raw
- requires filtering
- requires human review
- not eligible for public release yet

---

## 11. Filtering and Review

Automated filtering should check:

- target language correctness
- valid output structure
- category and severity consistency
- English leakage
- direct copying from PKU source
- duplicate or near-duplicate prompts
- malformed or generic outputs
- seed context use
- obvious legal/civic errors

Human reviewers should check:

- fluency
- authenticity
- cultural plausibility
- legal/civic accuracy
- harm-category fit
- severity fit
- whether the prompt sounds like something a real speaker might ask
- safe-response quality
- unsafe-response harmfulness where applicable

Review should be stratified by language, harm category, severity, and generation method. Higher-risk items, S4 items, and legal/civic-sensitive outputs should receive heavier review.

---

## 12. Provenance and Export Rules

Every generated item should retain:

- generation method
- model
- source PKU prompt ID
- target language
- harm category
- severity
- seed document IDs
- source IDs
- batch ID
- run ID
- prompt template version
- filtering status
- review status

Public export should be blocked if the item's lineage includes sources that are internal-only, legally unresolved, or not permitted for public release.

This is important because reviewers and future users must be able to ask:

- Which PKU prompt inspired this item?
- Which seed context influenced it?
- Was any social-media-derived or internal-only source used?
- Which generation method produced it?
- Which model produced it?
- Did it pass human review?

---

## 13. Immediate Three-Day Plan

### Tonight

- Finalize emergency batch scope.
- Prepare batch requests.
- Estimate token/cost budget.
- Submit first batch.
- Record batch and run metadata.

### Tomorrow

- Sync or download outputs.
- Run structural validation and language checks.
- Inspect dashboard and sample outputs.
- Decide whether Method A or Method B is performing better.

### Day 2

- Submit a second batch based on first-batch results.
- Optionally add more languages, more categories, or candidate responses.
- Start seed governance implementation.

### Day 3

- Submit final batch before credit expiry.
- Freeze raw outputs.
- Begin filtering and review triage.
- Keep all data internal until governance and review are complete.

---

## 14. Decisions Needed Today

Peers should decide:

1. Should tonight's batch prioritize scientific A/B testing or raw generation volume?
2. Which languages are included tonight: 3, 6, or all configured runtime entries?
3. Should Sepedi and Northern Sotho be separate targets or collapsed?
4. Should the emergency batch produce prompts only, or prompts plus safe/unsafe responses?
5. Should S4 be included now or delayed until stronger review procedures are ready?
6. Are social-media-derived sources internal-only by default?
7. Is `gpt-5.4` the right generation model for the emergency batch?
8. What is the minimum human review commitment after the first batch?

---

## 15. Recommended Position

The defensible position is:

> AfriGuard will use the expiring OpenAI credits for internal raw generation, not final public release. The emergency batch will generate African-language safety data from PKU-inspired safety intent and existing seed context. All outputs will retain provenance and remain internal until filtering, governance, and human review are complete.

This keeps us moving fast without pretending the release-quality governance problem is already solved.

---

## 16. Key References

- PKU-SafeRLHF: https://huggingface.co/datasets/PKU-Alignment/PKU-SafeRLHF
- PKU-SafeRLHF paper: https://aclanthology.org/2025.acl-long.1544/
- MasakhaNEWS: https://huggingface.co/datasets/masakhane/masakhanews
- MasakhaNER 2.0: https://huggingface.co/datasets/masakhane/masakhaner2
- AfriSenti: https://huggingface.co/datasets/masakhane/afrisenti
- OpenAI Batch API: https://platform.openai.com/docs/api-reference/batch
- OpenAI Batch guide: https://platform.openai.com/docs/guides/batch/getting-started
