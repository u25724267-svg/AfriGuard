"""Unit tests for centralized language configuration."""

from src.config.languages import (
    get_language_aliases_map,
    get_language_code,
    get_language_config,
    get_language_reviewer_map,
    get_low_resource_languages,
    get_reviewer_accounts,
    get_reviewer_language,
    is_supported_language,
    list_language_names,
)
from src.generation.generation_job import GenerationJob
from src.prompt_construction.legal_grounder import LegalGrounder
from src.review.task_assigner import TaskAssigner


def test_language_registry_exposes_existing_languages():
    languages = set(list_language_names())

    assert {"hausa", "sepedi", "chichewa", "northern_sotho", "yao", "yoruba", "shona"}.issubset(languages)
    assert is_supported_language("shona")
    assert get_language_code("shona") == "sn"


def test_language_aliases_and_low_resource_flags_are_config_driven():
    aliases = get_language_aliases_map()

    assert "sesotho sa leboa" in aliases["sepedi"]
    assert "sepedi" in aliases["northern_sotho"]
    assert {"sepedi", "northern_sotho", "yao", "shona"}.issubset(get_low_resource_languages())


def test_generation_and_review_use_language_registry():
    reviewer_map = get_language_reviewer_map()

    assert reviewer_map["shona"] == "reviewer_shona"
    assert TaskAssigner().get_reviewer_id("shona") == "reviewer_shona"
    assert get_reviewer_language("reviewer_shona") == "shona"
    assert GenerationJob._get_lang_code("shona") == "sn"


def test_reviewer_accounts_include_login_metadata():
    accounts = {account["reviewer_id"]: account for account in get_reviewer_accounts()}

    assert accounts["reviewer_sepedi"]["language"] == "sepedi"
    assert accounts["reviewer_sepedi"]["display_name"] == "Sepedi"


def test_prompt_and_legal_context_use_language_registry():
    sepedi = get_language_config("sepedi")

    assert "Sepedi" in sepedi.prompt_instruction
    assert "POPIA" in LegalGrounder().get_legal_context("sepedi", "H03")
