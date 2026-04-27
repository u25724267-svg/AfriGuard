"""
AfriGuard — Taxonomy: EntitySampler

Provides culturally authentic names, places, and organizations for
injection into generated prompts. Prevents the default English/Western
naming bias in LLM outputs.

Sources:
  1. MasakhaNER 2.0 (parsed from DB seed documents)
  2. Hand-curated AfriGuard lexicon (data/seeds/custom/afriguard_lexicon.json)
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_LEXICON_PATH = (
    Path(__file__).parent.parent.parent / "data" / "seeds" / "custom" / "afriguard_lexicon.json"
)

# Fallback lexicon embedded in code — used when the JSON file is not yet present.
# Research team should expand this file with community input.
_FALLBACK_LEXICON: dict[str, dict[str, list[str]]] = {
    "hausa": {
        "person_names": [
            "Aminu", "Fatima", "Ibrahim", "Hauwa", "Musa", "Zainab",
            "Abdullahi", "Aisha", "Garba", "Bilkisu", "Sani", "Ramatu",
            "Yakubu", "Hafsat", "Usman", "Maryam", "Lawal", "Hasiya",
        ],
        "place_names": [
            "Kano", "Kaduna", "Zaria", "Sokoto", "Katsina", "Daura",
            "Zamfara", "Gusau", "Bauchi", "Maiduguri", "Gombe", "Dutse",
        ],
        "organizations": [
            "Hisbah Board", "INEC Kano", "Arewa Consultative Forum",
            "Dan Agundi Market Association",
        ],
    },
    "yoruba": {
        "person_names": [
            "Adebayo", "Funmilayo", "Oluwaseun", "Bukola", "Taiwo",
            "Kehinde", "Babatunde", "Omowunmi", "Rotimi", "Titilayo",
            "Emeka", "Ngozi", "Chukwuemeka", "Chiamaka", "Obiora",
        ],
        "place_names": [
            "Lagos", "Ibadan", "Abeokuta", "Ogbomosho", "Ilorin",
            "Oshogbo", "Ile-Ife", "Akure", "Ondo", "Oyo",
        ],
        "organizations": [
            "Oodua Peoples Congress", "Afenifere", "Lagos Chamber of Commerce",
            "LUTH", "University of Ibadan",
        ],
    },
    "sepedi": {
        "person_names": [
            "Thabo", "Lerato", "Kgomotso", "Refilwe", "Sello",
            "Dimakatso", "Mpho", "Kedibone", "Lesego", "Tshepiso",
            "Mokoena", "Mashishi", "Nkosi", "Dlamini", "Molefe",
        ],
        "place_names": [
            "Polokwane", "Tzaneen", "Thohoyandou", "Mokopane",
            "Bela-Bela", "Groblersdal", "Burgersfort", "Lephalale",
        ],
        "organizations": [
            "Limpopo House of Traditional Leaders", "SADAG",
            "University of Limpopo", "Polokwane Municipality",
        ],
    },
    "northern_sotho": {
        "person_names": [
            "Tšhepiso", "Mamatle", "Lehlohonolo", "Kelebogile",
            "Motshidisi", "Phuti", "Tshepo", "Matlhodi", "Nthabiseng",
        ],
        "place_names": [
            "Polokwane", "Seshego", "Mankweng", "Lebowakgomo",
            "Marble Hall", "Giyani", "Bushbuckridge",
        ],
        "organizations": [
            "University of Limpopo", "Limpopo Department of Education",
            "Greater Tzaneen Municipality",
        ],
    },
    "chichewa": {
        "person_names": [
            "Chimwemwe", "Tadala", "Kondwani", "Thandeka", "Mphatso",
            "Chisomo", "Limbani", "Thandiwe", "Yankho", "Naomi",
            "Bright", "Stella", "Gift", "Mercy", "Precious",
        ],
        "place_names": [
            "Lilongwe", "Blantyre", "Mzuzu", "Zomba", "Mangochi",
            "Kasungu", "Salima", "Dedza", "Ntchisi", "Ntcheu",
        ],
        "organizations": [
            "Malawi Human Rights Commission", "MACOHA",
            "Chancellor College", "Bunda College",
        ],
    },
    "yao": {
        "person_names": [
            "Alimu", "Fatuma", "Hamisi", "Mariam", "Saidi",
            "Zainabu", "Juma", "Hadija", "Rashidi", "Mwanajuma",
            "Atupele", "Maulidi", "Zuwena", "Nassoro",
        ],
        "place_names": [
            "Mangochi", "Machinga", "Balaka", "Zomba", "Chiradzulu",
            "Phalombe", "Thyolo", "Mulanje",
        ],
        "organizations": [
            "Islamic Information Bureau Malawi", "Muslim Association of Malawi",
            "Mangochi District Council",
        ],
    },
    "shona": {
        "person_names": [
            "Tendai", "Rudo", "Tawanda", "Nyasha", "Kudzai", "Farai",
            "Tatenda", "Chipo", "Munyaradzi", "Vimbai", "Simbarashe", "Memory",
            "Blessing", "Munashe", "Tafadzwa", "Tsitsi",
        ],
        "place_names": [
            "Harare", "Chitungwiza", "Mutare", "Masvingo", "Gweru", "Bindura",
            "Marondera", "Murewa", "Chinhoyi", "Rusape", "Buhera", "Mbare",
        ],
        "organizations": [
            "Zimbabwe Electoral Commission", "Legal Resources Foundation",
            "Musasa Project", "Zimbabwe Republic Police Victim Friendly Unit",
            "Harare City Council",
        ],
    },
}


class EntitySampler:
    """
    Samples culturally authentic entities for injection into prompts.

    Attempts to load from the curated JSON lexicon first; falls back
    to the embedded _FALLBACK_LEXICON.
    """

    def __init__(self, lexicon_path: Path = _LEXICON_PATH):
        self._lexicon: dict[str, dict[str, list[str]]] = {}
        self._load(lexicon_path)

    def _load(self, path: Path) -> None:
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    self._lexicon = json.load(f)
                logger.info("entity_sampler.loaded_custom_lexicon", path=str(path))
                return
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("entity_sampler.lexicon_load_failed", error=str(e))
        logger.info("entity_sampler.using_fallback_lexicon")
        self._lexicon = _FALLBACK_LEXICON

    def sample_names(self, language: str, n: int = 2) -> list[str]:
        """Return n random person names for the given language."""
        names = self._lexicon.get(language.lower(), {}).get("person_names", [])
        if not names:
            return [f"Person_{i+1}" for i in range(n)]
        return random.sample(names, min(n, len(names)))

    def sample_places(self, language: str, n: int = 1) -> list[str]:
        """Return n random place names for the given language."""
        places = self._lexicon.get(language.lower(), {}).get("place_names", [])
        if not places:
            return ["[Local Area]"]
        return random.sample(places, min(n, len(places)))

    def sample_organizations(self, language: str, n: int = 1) -> list[str]:
        """Return n random organizations for the given language."""
        orgs = self._lexicon.get(language.lower(), {}).get("organizations", [])
        if not orgs:
            return ["[Local Organization]"]
        return random.sample(orgs, min(n, len(orgs)))

    def sample_all(self, language: str) -> dict[str, list[str]]:
        """Return a combined sample of names, places, and organizations."""
        return {
            "names": self.sample_names(language, n=2),
            "places": self.sample_places(language, n=1),
            "organizations": self.sample_organizations(language, n=1),
        }

    def get_entity_string(self, language: str) -> str:
        """
        Return a formatted string of sampled entities for prompt injection.

        Example output:
            Names: Aminu, Fatima | Place: Kano | Org: Hisbah Board
        """
        entities = self.sample_all(language)
        parts = [
            f"Names: {', '.join(entities['names'])}",
            f"Place: {entities['places'][0]}",
            f"Org: {entities['organizations'][0]}",
        ]
        return " | ".join(parts)
