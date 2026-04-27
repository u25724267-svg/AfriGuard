# Yoruba Annotation Guidelines

## Overview

These guidelines are for the **Yorùbá language reviewer** of the AfriGuard safety-alignment dataset.
You are reviewing AI-generated prompts and responses for cultural accuracy, harm classification,
and quality before they enter the training dataset.

---

## Your Role

For each prompt you see:
1. Read the **user prompt** (written in Yorùbá)
2. Read each **candidate response**
3. Make a decision: **Approve / Reject / Flag / Escalate**
4. Correct the harm label or severity if needed
5. Rank candidates if multiple are shown (1 = best)

---

## Language Quality Checks

Approve a response only if it:
- Is written in **genuine Yorùbá** as spoken in southwestern Nigeria
- Uses correct **tonal diacritics** where possible (ẹ, ọ, s̩, n̩) — absence is acceptable but not preferred
- References names and places authentic to Yoruba speakers (Lagos, Ibadan, Abeokuta, etc.)
- Sounds natural — not a word-for-word English translation

Reject if:
- The text is mostly English with Yorùbá words
- The Yorùbá grammar is clearly AI-garbled
- Tonal marks are systematically wrong in a way that changes meaning

---

## Harm Category Reference (Yorùbá context)

### H01 — Ìkorìíta àti Ìyàtọ̀ (Hate Speech)
- Yoruba-Igbo-Hausa inter-ethnic dynamics are the primary reference
- Historical civil war references ("Biafra") require careful handling — mark as **S2 minimum**
- Religious framing (Muslim vs Christian) in a political context — **S2**
- Explicit ethnic slurs targeting any group — **S2**

### H02 — Ìwa Ipá Ìbálọpọ̀ (GBV)
- Nigeria's VAPP Act (2015) applies
- "Corrective rape" targeting LGBTQ+ individuals: **S3**
- Same-Sex Marriage Prohibition Act 2014 provides legal context for Nigeria
- Grooming of minors is **S4 — Escalate**

### H03 — Ilokulo Asiri (Privacy)
- NDPR 2019 and Nigeria Data Protection Act 2023 apply
- BVN (Bank Verification Number) data exposure — **S3**
- Social media account hacking assistance — **S2**

### H04 — Àbájáde ìròyìn (Disinformation)
- Lagos State is a key reference for electoral content
- INEC-related fake news — **S2**

### H05 — Jibiti (Fraud)
- "Yahoo Yahoo" / G+ fraud culture is Yorùbá-specific — label as H05
- Advance fee fraud scenarios using Lagos/Abuja settings

---

## Severity Guide (Yorùbá)

| Severity | Yorùbá phrase | When to use |
|----------|--------------|-------------|
| S1 | Ìbàjẹ́ kékèké | Mildly offensive, low risk |
| S2 | Ìbàjẹ́ alágbára | Harmful to person or group |
| S3 | Ìbàjẹ́ tó le | Directly illegal under VAPP, etc. |
| S4 | Ewu tó le gan-an | Catastrophic — escalate immediately |

---

## Notes on Safe Responses (Yorùbá)

A good safe response in Yorùbá should:
- Refuse clearly in natural Yorùbá
- Reference culturally appropriate help resources:
  - GBV: *WARIF* (Women at Risk International Foundation), Lagos
  - Mental health: *LASUTH*, *Neuropsychiatric Hospital Yaba*
  - Legal: *NBA Lagos Branch Legal Aid*

---

## Red Flags — Always Escalate (S4)

- Content facilitating weapons or explosive manufacture
- CSAM (child sexual abuse material) — any form
- Content calling for ethnic violence in specific named communities
- Terrorism recruitment language

---

## Contact

If unsure, use **Flag** and add a note. Escalated items go to senior researcher review.
