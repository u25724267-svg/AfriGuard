"""Unit tests - Shona language support."""

from src.filtering.language_detector import _LANG_CODE_MAP
from src.generation.generation_job import GenerationJob
from src.prompt_construction.legal_grounder import LegalGrounder
from src.prompt_construction.prompt_builder import PromptBuilder
from src.review.task_assigner import TaskAssigner
from src.schemas.seed import SeedDocument
from src.taxonomy.entity_sampler import EntitySampler


def test_seed_schema_accepts_shona(sample_seed_texts):
    doc = SeedDocument(
        id="seed-shona",
        source_id="test",
        source_name="Test",
        language="shona",
        language_code="sn",
        text="Shona seed text long enough to validate correctly.",
        original_text="Shona seed text long enough to validate correctly.",
        fetched_at="2024-01-01T00:00:00",
    )
    assert doc.language == "shona"
    assert len(doc.provenance_hash) == 64


def test_shona_prompt_builder_has_language_instruction():
    prompt = PromptBuilder().build_system_prompt(
        language="shona",
        harm_category="H03",
        severity="S2",
        seed_context="Muenzaniso wechinyorwa cheShona.",
    )
    assert "chiShona" in prompt
    assert "Zimbabwe" in prompt


def test_shona_review_assignment():
    assert TaskAssigner().get_reviewer_id("shona") == "reviewer_shona"


def test_shona_language_codes_and_generation_code():
    assert "sn" in _LANG_CODE_MAP["shona"]
    assert GenerationJob._get_lang_code("shona") == "sn"


def test_shona_legal_grounding_and_entities():
    assert "Cyber and Data Protection Act" in LegalGrounder().get_legal_context("shona", "H03")
    entities = EntitySampler().sample_all("shona")
    assert entities["names"]
    assert entities["places"]
    assert entities["organizations"]
