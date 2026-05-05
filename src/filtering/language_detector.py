"""
AfriGuard — Filtering: LanguageDetector

Detects the language of generated text and scores confidence.
Uses langdetect as primary, langid as secondary, with an optional
LLM-based fallback for low-resource languages (Yao, Sepedi, Northern Sotho)
where both libraries perform poorly.
"""

from __future__ import annotations

import json
import re
import unicodedata

import structlog

from src.config.filtering import FilteringConfig, load_filtering_config
from src.config.languages import (
    get_language_aliases_map,
    get_language_codes_map,
    get_low_resource_languages,
)

logger = structlog.get_logger(__name__)

# Map AfriGuard language names to ISO codes that langdetect/langid may recognize
_LANG_CODE_MAP = get_language_codes_map()

# Human-readable names that LLMs commonly return for the same target language.
# Sepedi is especially important here: many tools identify it as Northern Sotho
# or Sesotho sa Leboa, and rejecting those aliases wipes out valid candidates.
_LANG_NAME_ALIASES = get_language_aliases_map()

# Languages with poor library support — use LLM check
_LOW_RESOURCE_FALLBACK = get_low_resource_languages()


def _normalize_language_label(label: str | None) -> str:
    if not label:
        return ""
    normalized = unicodedata.normalize("NFKD", str(label)).encode("ascii", "ignore").decode()
    normalized = normalized.lower().replace("_", " ").replace("-", " ")
    normalized = re.sub(r"[^a-z0-9,\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _language_label_matches(detected: str | None, expected_language: str, expected_codes: set[str]) -> bool:
    detected_norm = _normalize_language_label(detected)
    expected_norm = _normalize_language_label(expected_language)
    expected_aliases = {
        _normalize_language_label(alias)
        for alias in _LANG_NAME_ALIASES.get(expected_language.lower(), {expected_language})
    }
    expected_aliases.update(_normalize_language_label(code) for code in expected_codes)
    expected_aliases.add(expected_norm)

    if detected_norm in expected_aliases:
        return True

    # Accept descriptive labels such as "Sepedi (Northern Sotho)" or
    # "Northern Sotho / Sesotho sa Leboa" without accepting very short
    # accidental substring matches like "ha" inside another word.
    descriptive_aliases = {alias for alias in expected_aliases if len(alias) >= 4}
    return any(alias in detected_norm or detected_norm in alias for alias in descriptive_aliases)


def _parse_llm_language_json(text: str) -> dict:
    """Parse strict JSON, fenced JSON, or a JSON object embedded in text."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


class LanguageDetectionResult:
    def __init__(self, detected: str, confidence: float, method: str):
        self.detected = detected       # Detected language code
        self.confidence = confidence   # 0.0 to 1.0
        self.method = method           # "langdetect", "langid", "llm", "heuristic"


class LanguageDetector:
    """
    Detects whether a text is in the expected language.

    Returns a score between 0.0 and 1.0:
      1.0 = certain match
      0.5 = uncertain (low-resource language, accept with caveats)
      0.0 = definite mismatch (text appears to be in a different language)
    """

    def __init__(self, llm_router=None, config: FilteringConfig | None = None):
        """
        Args:
            llm_router: Optional ModelRouter for LLM-based language checking.
                        If None, LLM fallback is disabled.
        """
        self._llm_router = llm_router
        self._config = config or load_filtering_config()
        self._langdetect_available = self._check_langdetect()
        self._langid_available = self._check_langid()

    def _check_langdetect(self) -> bool:
        try:
            import langdetect  # noqa: F401
            return True
        except ImportError:
            logger.warning("language_detector.langdetect_not_installed")
            return False

    def _check_langid(self) -> bool:
        try:
            import langid  # noqa: F401
            return True
        except ImportError:
            logger.warning("language_detector.langid_not_installed")
            return False

    def detect(self, text: str, expected_language: str) -> LanguageDetectionResult:
        """
        Detect the language of text and compare to the expected language.

        Returns:
            LanguageDetectionResult with confidence score.
        """
        text = text.strip()
        if not text or len(text) < self._config.language_detection.min_text_chars:
            return LanguageDetectionResult(detected="unknown", confidence=0.0, method="heuristic")

        expected_codes = _LANG_CODE_MAP.get(expected_language.lower(), set())

        # --- Try langdetect ---
        if self._langdetect_available:
            result = self._try_langdetect(text, expected_codes)
            if result.confidence > self._config.language_detection.library_accept_threshold:
                return result

        # --- Try langid ---
        if self._langid_available:
            result = self._try_langid(text, expected_codes)
            if result.confidence > self._config.language_detection.library_accept_threshold:
                return result

        # --- For low-resource languages, default to moderate confidence ---
        # Libraries fail on Yao, Sepedi, Northern Sotho — use LLM or accept
        if expected_language.lower() in _LOW_RESOURCE_FALLBACK:
            if self._llm_router:
                return self._try_llm(text, expected_language)
            else:
                # Cannot verify — return moderate confidence (will be reviewed by human)
                return LanguageDetectionResult(
                    detected=expected_language,
                    confidence=0.5,
                    method="heuristic",
                )

        # --- Default: low confidence mismatch ---
        return LanguageDetectionResult(
            detected="unknown",
            confidence=0.2,
            method="heuristic",
        )

    def _try_langdetect(self, text: str, expected_codes: set) -> LanguageDetectionResult:
        try:
            from langdetect import detect, detect_langs
            langs = detect_langs(text)
            if not langs:
                return LanguageDetectionResult(detected="unknown", confidence=0.0, method="langdetect")

            top = langs[0]
            detected_code = top.lang
            confidence = top.prob

            # Normalize: if detected code matches any expected code
            is_match = detected_code in expected_codes
            adjusted_confidence = confidence if is_match else confidence * 0.1

            return LanguageDetectionResult(
                detected=detected_code,
                confidence=adjusted_confidence,
                method="langdetect",
            )
        except Exception as e:
            logger.debug("language_detector.langdetect_error", error=str(e))
            return LanguageDetectionResult(detected="unknown", confidence=0.0, method="langdetect")

    def _try_langid(self, text: str, expected_codes: set) -> LanguageDetectionResult:
        try:
            import langid
            lang, confidence_raw = langid.classify(text)
            # langid returns a negative log-likelihood; normalize heuristically
            confidence = min(1.0, max(0.0, (confidence_raw + 100) / 100))
            is_match = lang in expected_codes
            adjusted = confidence if is_match else confidence * 0.1
            return LanguageDetectionResult(
                detected=lang,
                confidence=adjusted,
                method="langid",
            )
        except Exception as e:
            logger.debug("language_detector.langid_error", error=str(e))
            return LanguageDetectionResult(detected="unknown", confidence=0.0, method="langid")

    def _try_llm(self, text: str, expected_language: str) -> LanguageDetectionResult:
        """Use LLM to verify language for low-resource languages."""
        try:
            expected_codes = _LANG_CODE_MAP.get(expected_language.lower(), set())
            system = (
                "You are a language identification expert specializing in African languages. "
                "Answer with ONLY a JSON object: {\"language\": \"<detected_language>\", \"confidence\": <0.0-1.0>}"
            )
            user = f"What language is the following text written in?\n\nText: {text[:300]}"
            resp = self._llm_router.generate(
                model_id="gpt-5.4",
                system_prompt=system,
                user_message=user,
                temperature=0.0,
                max_tokens=50,
            )
            result = _parse_llm_language_json(resp.text)
            detected = (
                result.get("language")
                or result.get("detected_language")
                or result.get("language_name")
                or "unknown"
            )
            conf = float(result.get("confidence", 0.5))
            is_match = _language_label_matches(detected, expected_language, expected_codes)
            adjusted = conf if is_match else conf * 0.1
            return LanguageDetectionResult(
                detected=_normalize_language_label(detected) or "unknown",
                confidence=adjusted,
                method="llm",
            )
        except Exception as e:
            logger.warning("language_detector.llm_fallback_failed", error=str(e))
            return LanguageDetectionResult(
                detected=expected_language,
                confidence=self._config.language_detection.llm_failure_fallback_confidence,
                method="heuristic",
            )

    def is_acceptable(
        self, text: str, expected_language: str, threshold: float | None = None
    ) -> tuple[bool, LanguageDetectionResult]:
        """
        Returns (passes, result). Passes if confidence >= threshold.
        Low-resource languages use a lower effective threshold (0.35).
        """
        effective_threshold = threshold or self._config.language_detection.default_threshold
        if expected_language.lower() in _LOW_RESOURCE_FALLBACK:
            effective_threshold = self._config.language_detection.low_resource_threshold

        result = self.detect(text, expected_language)
        passes = result.confidence >= effective_threshold
        return passes, result
