# Hausa Annotation Guidelines

## Overview

These guidelines are for the **Hausa language reviewer** of the AfriGuard safety-alignment dataset.
You are reviewing AI-generated prompts and responses for cultural accuracy, harm classification,
and quality before they enter the training dataset.

---

## Your Role

For each prompt you see:
1. Read the **user prompt** (written in Hausa)
2. Read each **candidate response** (safe and unsafe variants)
3. Make a decision: **Approve / Reject / Flag / Escalate**
4. Correct the harm label or severity if needed
5. Rank candidates if multiple are shown (1 = best)

---

## Language Quality Checks

Approve a response only if it:
- Is written in **genuine Hausa** (not Pidgin, not romanized gibberish)
- Uses natural vocabulary and sentence structure as spoken in **northern Nigeria**
- References names, places, and social contexts authentic to Hausa speakers
- Does not switch to English mid-sentence unless quoting something

Reject if:
- The text is mostly English with Hausa words inserted
- The Hausa is machine-garbled or unnatural
- It uses exclusively Ajami (Arabic script) where Latin script is expected, or vice versa

---

## Harm Category Reference (Hausa context)

### H01 — Ƙiyayya da Wariya (Hate Speech)
- Includes content targeting Hausas, Igbos, Yorubas, or other ethnic groups in Nigeria
- Religious intolerance between Muslims and Christians is **S2 minimum**
- Any content referencing Boko Haram or ISWAP as positive is **S4 — Escalate immediately**
- Tribal insults using common derogatory terms are **S2**

### H02 — Cin zarafin mata da laifukan jima'i (GBV)
- Nigeria's VAPP Act (2015) is the legal reference
- Content normalizing early marriage for girls under 18 is **S3** (contested by Child Rights Act)
- Sexual coercion language is **S3**
- Grooming of minors is **S4 — Escalate**

### H03 — Keta sirri (Privacy violations)
- Nigeria Data Protection Act 2023 and NDPR 2019 apply
- Mobile money (OPay, PalmPay) data exposure is **S2**
- NIN (National Identity Number) exposure is **S3**

### H05 — Zamba (Fraud)
- "Yahoo Yahoo" and 419 fraud are culturally specific — mark as H05
- Mobile money scams targeting market traders are common — use local context

---

## Severity Guide (Hausa)

| Severity | Hausa term | When to use |
|----------|-----------|-------------|
| S1 | Laifi kaɗan | Offhand comment, not directly harmful |
| S2 | Laifi matsakaici | Likely harmful to a person or group |
| S3 | Laifi mai tsanani | Directly illegal under VAPP, Child Rights Act, etc. |
| S4 | Laifi mai hadari sosai | Catastrophic — escalate immediately |

---

## Notes on Safe Responses

A **safe response** in Hausa should:
- Refuse politely and clearly in Hausa
- Explain *why* the request is problematic (in cultural terms when possible)
- Offer an alternative or referral: e.g., *"Ka tuntubi asibitin gida"* (Contact the local hospital)
- NOT be preachy or excessively long

A **useful local referral** for Hausa reviewers:
- Mental health: *Asibitin Kano* (Kano State Hospital), *MHPSS hotline*
- GBV: *NAPTIP hotline 0800-CALL-NTP*
- Legal: *Nigerian Legal Aid Council*

---

## Red Flags — Always Escalate (S4)

- Any content that positively frames Boko Haram, ISWAP, Ansaru
- Content instructing on weapon-making using locally available materials
- Child sexual abuse material (CSAM) — even implied
- Content calling for mass ethnic violence

---

## Contact

If you are unsure about a label, use **Flag** and add a note explaining your uncertainty.
Escalated items will be reviewed by the senior researcher.
