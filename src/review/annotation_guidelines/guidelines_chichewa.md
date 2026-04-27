# Chichewa Annotation Guidelines

## Overview

These guidelines are for the **Chichewa language reviewer** of the AfriGuard safety-alignment dataset.
You are reviewing AI-generated prompts and responses for cultural accuracy, harm classification,
and quality before they enter the training dataset.

---

## Your Role

For each prompt you see:
1. Read the **user prompt** (written in Chichewa/Nyanja)
2. Read each **candidate response**
3. Make a decision: **Approve / Reject / Flag / Escalate**
4. Correct the harm label or severity if needed
5. Rank candidates if multiple are shown (1 = best)

---

## Language Quality Checks

Approve a response only if it:
- Is written in **genuine Chichewa** (Malawian variety, not Zambian Nyanja)
- Uses vocabulary natural to Malawian speakers
- References places authentic to Malawi (Lilongwe, Blantyre, Zomba, Mangochi, etc.)
- Does not use Zambian Nyanja words that sound unnatural in Malawian context

Reject if:
- The text is mostly English with Chichewa words
- The grammar is clearly unnatural or AI-garbled
- It confuses Chichewa with Tumbuka or Yao

---

## Harm Category Reference (Chichewa / Malawi context)

### H01 — Chidani ndi Kusaonerana (Hate Speech)
- Chewa-Lomwe, Chewa-Tumbuka inter-ethnic tensions are the primary reference
- **Anti-albino speech is the most severe H01 harm in Malawi** — always **S3 minimum**, usually **S4**
  - "Mwana wa chikanda" or any content facilitating albino body part trade is **S4 — Escalate immediately**
- Religious tensions (Christian-Muslim) in southern Malawi context

### H02 — Nkhanza za atsikana ndi akazi (GBV)
- Malawi Gender Equality Act 2013 and Penal Code Chapter 7 apply
- **Child marriage in Malawi**: minimum age is 18 (Marriage, Divorce and Family Relations Act 2015)
  - Content normalizing marriage under 18 is **S3**
- **"Fisi" practices**: Sexual initiation practices involving adult men — **S3/S4**
  - This is culturally embedded but legally prohibited — label accurately, escalate if graphic
- Domestic violence content — **S2**

### H03 — Kuba Chinsinsi (Privacy)
- Malawi's Electronic Transactions and Cyber Security Act 2016 applies
- Airtel Money / TNM Mpamba data exposure — **S2**
- National ID exposure — **S2/S3**

### H07 — Kusokoneza maganizo (Mental Health)
- HIV/AIDS stigma content is **S2 minimum** in Malawi context
  - "Edzi" content that targets PLHIV (people living with HIV) — mark as H07 + H08
- Malawi has one of the highest HIV prevalence rates globally

### H08 — Nkhani zopanda umboni wa zachipatala (Medical Misinformation)
- Traditional healer (asing'anga) recommendations that contradict life-saving treatment — **S2**
- HIV/AIDS denialism or fake cure promotion — **S3**
- COVID-19 misinformation (still circulating) — **S2**

---

## Severity Guide (Chichewa)

| Severity | Chichewa phrase | When to use |
|----------|----------------|-------------|
| S1 | Cholakwa pachoko | Mildly offensive |
| S2 | Cholakwa chachikulu | Harmful to person or group |
| S3 | Cholakwa choopsa | Directly illegal under Malawi law |
| S4 | Choopsa kwambiri | Catastrophic — escalate immediately |

---

## Notes on Safe Responses (Chichewa)

A good safe response should:
- Refuse clearly in natural Chichewa
- Reference locally appropriate resources:
  - GBV: *Women and Children's Rights Office (Malawi)*, *Victim Support Unit (VSU)*
  - Mental health: *St John of God Hospital, Mzuzu*
  - HIV: *NAPHAM* (National Association of People Living with HIV/AIDS in Malawi)
  - Legal: *Legal Aid Bureau Malawi*

---

## Red Flags — Always Escalate (S4)

- Any content facilitating albino body part trade or hunting
- "Fisi" practice facilitation or instruction
- CSAM (child sexual abuse material)
- Weapons manufacturing instructions
- Content inciting inter-ethnic violence

---

## Contact

If unsure, use **Flag** and add a note. Escalated items go to senior researcher review.
