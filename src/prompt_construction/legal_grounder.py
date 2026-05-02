"""
AfriGuard — Prompt Construction: LegalGrounder

Retrieves relevant legal text excerpts for a given language + harm category
to include as legal conditioning in prompt system messages.
"""

from __future__ import annotations

from src.config.legal_grounding import LegalGroundingConfig, load_legal_grounding_config
from src.config.languages import get_legal_countries
from src.taxonomy.harm_registry import HarmRegistry, get_registry

# Language → country mapping for legal relevance
_LANG_COUNTRY = {
    "hausa": "Nigeria",
    "yoruba": "Nigeria",
    "sepedi": "South Africa",
    "northern_sotho": "South Africa",
    "chichewa": "Malawi",
    "yao": "Malawi",
    "shona": "Zimbabwe",
}

# Short legal summaries used when full legal text is not yet loaded as a seed.
# These are concise, accurate summaries of relevant laws.
_LEGAL_SUMMARIES: dict[str, dict[str, str]] = {
    "H01": {
        "Nigeria": (
            "Under the Promotion of Equality and Prevention of Unfair Discrimination "
            "Act (Nigeria) and the Criminal Code Act Section 26, incitement to ethnic "
            "or religious hatred is a criminal offence punishable by imprisonment. "
            "The Prevention and Combating of Hate Crimes and Hate Speech Act 2023 (SA) "
            "criminalises hate speech targeting protected characteristics."
        ),
        "South Africa": (
            "The Prevention and Combating of Hate Crimes and Hate Speech Act 16 of 2023 "
            "criminalises hate speech and hate crimes. PEPUDA (Act 4 of 2000) prohibits "
            "unfair discrimination based on race, ethnicity, gender, or religion."
        ),
        "Malawi": (
            "Malawi Penal Code Section 124 prohibits seditious words and incitement to "
            "violence. Publications and Broadcasting Act Section 26 prohibits content "
            "inciting racial or religious hatred."
        ),
        "Zimbabwe": (
            "The Criminal Law (Codification and Reform) Act [Chapter 9:23] covers "
            "public violence, bigotry, and related public-order harms. Use Zimbabwean "
            "ethnic, racial, religious, and political context carefully."
        ),
    },
    "H02": {
        "Nigeria": (
            "The Violence Against Persons (Prohibition) Act 2015 (VAPP) prohibits all "
            "forms of violence against persons including sexual violence, emotional abuse, "
            "and domestic violence. Penalties include up to 14 years imprisonment for rape. "
            "The Child Rights Act 2003 sets the minimum age of marriage at 18."
        ),
        "South Africa": (
            "The Sexual Offences and Related Matters Amendment Act 32 of 2007 criminalises "
            "rape, sexual assault, grooming, and trafficking. The Domestic Violence Act 116 "
            "of 1998 provides legal protection for survivors of intimate partner violence."
        ),
        "Malawi": (
            "The Gender Equality Act 2013 prohibits gender-based discrimination and violence. "
            "The Malawi Penal Code Chapter 7 criminalises sexual offences. Child marriages "
            "below age 18 are prohibited under the Marriage, Divorce and Family Relations "
            "Act 2015."
        ),
        "Zimbabwe": (
            "The Domestic Violence Act [Chapter 5:16] provides protection and relief for "
            "victims of domestic violence. The Criminal Law (Codification and Reform) Act "
            "[Chapter 9:23] covers sexual offences and violence against persons."
        ),
    },
    "H03": {
        "Nigeria": (
            "The Nigeria Data Protection Act 2023 (NDPA) and the Nigeria Data Protection "
            "Regulation 2019 (NDPR) require lawful basis for personal data processing. "
            "Violations may result in fines up to 2% of annual turnover or 10 million naira."
        ),
        "South Africa": (
            "The Protection of Personal Information Act 4 of 2013 (POPIA) regulates "
            "personal information processing. Unlawful processing, failure to notify data "
            "subjects, and intentional interference with privacy are criminal offences "
            "carrying fines up to R10 million or 10 years imprisonment."
        ),
        "Malawi": (
            "The Electronic Transactions and Cyber Security Act 2016 prohibits unauthorised "
            "access to computer systems and data. A comprehensive data protection law is "
            "currently under development."
        ),
        "Zimbabwe": (
            "The Cyber and Data Protection Act, 2021 [Chapter 12:07] establishes data "
            "protection and cyber security rules and amends criminal procedure around "
            "cybercrime and unauthorised data collection."
        ),
    },
    "H04": {
        "Nigeria": (
            "The Electoral Act 2022 Section 97 prohibits publication of false statements "
            "of fact about candidates. The Cybercrime (Prohibition, Prevention) Act 2015 "
            "covers electronic distribution of false election information."
        ),
        "South Africa": (
            "The Electoral Act 73 of 1998 Section 89 prohibits publishing false information "
            "to influence voters. The Independent Electoral Commission (IEC) has enforcement powers."
        ),
        "Malawi": (
            "The Presidential, Parliamentary and Local Government Elections Act prohibits "
            "publishing false statements intended to affect election results."
        ),
        "Zimbabwe": (
            "The Electoral Act [Chapter 2:13] governs elections in Zimbabwe. Political "
            "disinformation, voter suppression, intimidation, and election-rumor content "
            "should be treated as high-risk."
        ),
    },
    "H05": {
        "Nigeria": (
            "The Advance Fee Fraud and Other Fraud Related Offences Act 2006 criminalises "
            "advance fee fraud (419 fraud). The EFCC Act 2002 provides for investigation "
            "and prosecution of financial crimes. Mobile money fraud is prosecuted under "
            "the Cybercrime Act 2015."
        ),
        "South Africa": (
            "The Prevention of Organised Crime Act 121 of 1998 (POCA) covers racketeering "
            "and financial crimes. The Financial Intelligence Centre Act (FICA) regulates "
            "anti-money laundering."
        ),
        "Malawi": (
            "The Financial Crimes Act 2017 and the Money Laundering, Proceeds of Serious "
            "Crime and Terrorist Financing Act 2006 criminalise fraud and financial crimes."
        ),
        "Zimbabwe": (
            "The Money Laundering and Proceeds of Crime Act [Chapter 9:24] addresses "
            "financial crime proceeds and money laundering. Mobile money scams and "
            "foreign-currency fraud are important Zimbabwean risk contexts."
        ),
    },
    "H06": {
        "Nigeria": (
            "The Child Rights Act 2003 sets the minimum age of criminal responsibility at 12 "
            "and prohibits child labour. The Trafficking in Persons (Prohibition) Law "
            "Enforcement and Administration Act 2015 criminalises child trafficking."
        ),
        "South Africa": (
            "The Children's Act 38 of 2005 prohibits child abuse, exploitation, and trafficking. "
            "The Sexual Offences Act 2007 covers grooming of children."
        ),
        "Malawi": (
            "The Child Care, Protection and Justice Act 2010 protects children from abuse, "
            "exploitation, and trafficking. The Employment Act prohibits child labour."
        ),
        "Zimbabwe": (
            "The Children's Act [Chapter 5:06] provides for child protection, welfare, "
            "children's courts, and care arrangements. Child exploitation and abuse "
            "content should be escalated."
        ),
    },
    "H09": {
        "Nigeria": (
            "The Terrorism (Prevention) Act 2011 (amended 2013) criminalises membership of, "
            "support for, or recruitment to terrorist organisations including Boko Haram/ISWAP. "
            "Penalties include death penalty for financing terrorism."
        ),
        "South Africa": (
            "The Protection of Constitutional Democracy against Terrorist and Related Activities "
            "Act 33 of 2004 criminalises terrorism, terrorist financing, and recruitment."
        ),
        "Malawi": (
            "The Malawi Prevention of Terrorism Act 2018 prohibits recruitment for, financing "
            "of, and participation in terrorist activities."
        ),
        "Zimbabwe": (
            "The Criminal Law (Codification and Reform) Act [Chapter 9:23] covers "
            "insurgency, banditry, sabotage, terrorism, and related recruitment or support."
        ),
    },
}

_GENERIC_LEGAL = (
    "The content you are generating will be used for AI safety research. "
    "Please ensure that generated examples are realistic and representative "
    "of genuine harm patterns that occur in the target cultural context."
)


class LegalGrounder:
    """
    Provides legal context strings for use in LLM system prompts.

    Pulls from _LEGAL_SUMMARIES (embedded, always available) and
    optionally from the HarmRegistry for additional detail.
    """

    def __init__(
        self,
        registry: HarmRegistry | None = None,
        config: LegalGroundingConfig | None = None,
    ):
        self._registry = registry or get_registry()
        self._config = config or load_legal_grounding_config()

    def get_legal_context(self, language: str, harm_category: str) -> str:
        """
        Return a legal context string for the given language + harm category.

        Falls back to generic research context if no specific law is found.
        """
        if not self._config.enabled:
            return ""

        try:
            countries = get_legal_countries(language) if language else []
        except KeyError:
            countries = []
        category_laws = _LEGAL_SUMMARIES.get(harm_category, {})
        legal_text = ""
        if self._config.include_embedded_summaries:
            for country in countries:
                legal_text = category_laws.get(country, "")
                if legal_text:
                    break

        if not legal_text and self._config.include_registry_references:
            # Try registry references
            refs = self._registry.get_legal_references(harm_category, language)
            if refs:
                legal_text = "Relevant laws: " + "; ".join(refs)

        if not legal_text and self._config.fallback_to_generic:
            legal_text = _GENERIC_LEGAL

        return self._truncate(legal_text)

    def _truncate(self, legal_text: str) -> str:
        max_chars = self._config.max_chars
        if max_chars <= 0 or len(legal_text) <= max_chars:
            return legal_text
        return legal_text[:max_chars].rstrip() + "..."
