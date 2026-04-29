"""Unit tests for low-resource language detection."""

from src.filtering.language_detector import LanguageDetector


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeRouter:
    def __init__(self, response_text: str):
        self.response_text = response_text

    def generate(self, **kwargs):
        return _FakeResponse(self.response_text)


def _detector(response_text: str) -> LanguageDetector:
    detector = LanguageDetector(llm_router=_FakeRouter(response_text))
    detector._langdetect_available = False
    detector._langid_available = False
    return detector


def test_sepedi_accepts_northern_sotho_alias_from_llm():
    detector = _detector('{"language": "Northern Sotho", "confidence": 0.92}')

    ok, result = detector.is_acceptable("Dintlha tsa sephiri ga di a swanela go phatlalatswa.", "sepedi")

    assert ok is True
    assert result.detected == "northern sotho"
    assert result.confidence == 0.92


def test_sepedi_accepts_sesotho_sa_leboa_in_fenced_json():
    detector = _detector('```json\n{"language": "Sesotho sa Leboa", "confidence": 0.88}\n```')

    ok, result = detector.is_acceptable("Motho o swanetse go sireletsa tshedimosetso ya gagwe.", "sepedi")

    assert ok is True
    assert result.detected == "sesotho sa leboa"
    assert result.confidence == 0.88


def test_sepedi_rejects_confident_english_detection():
    detector = _detector('{"language": "English", "confidence": 0.95}')

    ok, result = detector.is_acceptable("This text is clearly written in English.", "sepedi")

    assert ok is False
    assert result.detected == "english"
    assert result.confidence == 0.095
