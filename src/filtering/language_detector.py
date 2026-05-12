"""
AfriGuard — Filtering: LanguageDetector

Detects the language of generated text and scores confidence.
Uses GlotLID first when a local model is configured, then falls back to
langdetect/langid and an optional LLM check for explicitly enabled audits.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import structlog

from src.config.filtering import FilteringConfig, load_filtering_config
from src.config.language_id import LanguageIdConfig, load_language_id_config
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


def _clean_glotlid_label(label: str | bytes | None) -> str:
    if label is None:
        return "unknown"
    if isinstance(label, bytes):
        label = label.decode("utf-8", errors="ignore")
    return str(label).replace("__label__", "").strip()


def _token_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


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
    def __init__(
        self,
        detected: str,
        confidence: float,
        method: str,
        details: dict | None = None,
    ):
        self.detected = detected       # Detected language code
        self.confidence = confidence   # 0.0 to 1.0
        self.method = method           # "glotlid", "langdetect", "langid", "llm", "heuristic"
        self.details = details or {}


class LanguageDetector:
    """
    Detects whether a text is in the expected language.

    Returns a score between 0.0 and 1.0:
      1.0 = certain match
      0.5 = uncertain (low-resource language, accept with caveats)
      0.0 = definite mismatch (text appears to be in a different language)
    """

    def __init__(
        self,
        llm_router=None,
        config: FilteringConfig | None = None,
        language_id_config: LanguageIdConfig | None = None,
    ):
        """
        Args:
            llm_router: Optional ModelRouter for LLM-based language checking.
                        If None, LLM fallback is disabled.
        """
        self._llm_router = llm_router
        self._config = config or load_filtering_config()
        self._language_id_config = language_id_config or load_language_id_config()
        self._glotlid_model = None
        self._glotlid_error: str | None = None
        self._glotlid_available = self._check_glotlid()
        self._langdetect_available = self._check_langdetect()
        self._langid_available = self._check_langid()

    def _check_glotlid(self) -> bool:
        glotlid_config = self._language_id_config.glotlid
        if not glotlid_config.enabled:
            return False

        model_path = glotlid_config.resolved_model_path
        if not model_path:
            self._glotlid_error = (
                f"{glotlid_config.model_env_var} is not set and no model_path is configured"
            )
            logger.warning("language_detector.glotlid_model_not_configured")
            if glotlid_config.fail_on_missing_model:
                raise RuntimeError(self._glotlid_error)
            return False

        path = Path(model_path).expanduser()
        if not path.exists():
            self._glotlid_error = f"GlotLID model not found: {path}"
            logger.warning("language_detector.glotlid_model_missing", path=str(path))
            if glotlid_config.fail_on_missing_model:
                raise FileNotFoundError(self._glotlid_error)
            return False

        try:
            import fasttext  # noqa: F401
        except ImportError:
            self._glotlid_error = "fasttext is not installed; install fasttext-wheel"
            logger.warning("language_detector.fasttext_not_installed")
            if glotlid_config.fail_on_missing_model:
                raise RuntimeError(self._glotlid_error)
            return False

        return True

    def _load_glotlid_model(self):
        if self._glotlid_model is not None:
            return self._glotlid_model

        model_path = self._language_id_config.glotlid.resolved_model_path
        if not model_path:
            raise RuntimeError("GlotLID model path is not configured")

        import fasttext

        self._glotlid_model = fasttext.load_model(str(Path(model_path).expanduser()))
        return self._glotlid_model

    @property
    def glotlid_available(self) -> bool:
        return self._glotlid_available

    @property
    def glotlid_error(self) -> str | None:
        return self._glotlid_error

    def glotlid_threshold_for(self, text: str, expected_language: str) -> float:
        return self._language_id_config.threshold_for(expected_language, _token_count(text))

    def detect_glotlid_only(self, text: str, expected_language: str) -> LanguageDetectionResult:
        """Run only GlotLID, with no langdetect/langid/LLM fallback."""
        if not self._glotlid_available:
            raise RuntimeError(self._glotlid_error or "GlotLID is not available")

        text = text.strip()
        min_chars = self._language_id_config.min_chars_for(expected_language)
        if not text or len(text) < min_chars:
            return LanguageDetectionResult(
                detected="unknown",
                confidence=0.0,
                method="glotlid",
                details={"error": "text_too_short", "min_chars": min_chars},
            )

        return self._try_glotlid(text, expected_language)

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
        min_chars = max(
            self._config.language_detection.min_text_chars,
            self._language_id_config.min_chars_for(expected_language),
        )
        if not text or len(text) < min_chars:
            return LanguageDetectionResult(detected="unknown", confidence=0.0, method="heuristic")

        expected_codes = _LANG_CODE_MAP.get(expected_language.lower(), set())

        # --- Try GlotLID first when the local fastText model is configured ---
        if self._glotlid_available:
            result = self._try_glotlid(text, expected_language)
            if result.confidence > 0.0 or not self._language_id_config.glotlid.fallback_to_legacy:
                return result

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
            if self._llm_router and self._config.language_detection.llm_fallback_enabled:
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

    def _try_glotlid(self, text: str, expected_language: str) -> LanguageDetectionResult:
        try:
            entry = self._language_id_config.get_language(expected_language)
            if not entry:
                return LanguageDetectionResult(
                    detected="unknown",
                    confidence=0.0,
                    method="glotlid",
                    details={"error": f"no language_id config for {expected_language}"},
                )

            model = self._load_glotlid_model()
            compact_text = re.sub(r"\s+", " ", text.strip())
            labels, probabilities = model.predict(
                compact_text,
                k=max(1, self._language_id_config.glotlid.top_k),
            )
            predictions = [
                (_clean_glotlid_label(label), float(prob))
                for label, prob in zip(labels, probabilities)
            ]
            if not predictions:
                return LanguageDetectionResult(
                    detected="unknown",
                    confidence=0.0,
                    method="glotlid",
                    details={"predictions": []},
                )

            accepted = entry.accepted_label_set
            related = entry.related_label_set
            contaminants = entry.contaminant_label_set
            top_label, top_probability = predictions[0]
            accepted_prediction = next(
                ((label, prob) for label, prob in predictions if label in accepted),
                None,
            )
            contaminant_prediction = next(
                ((label, prob) for label, prob in predictions if label in contaminants),
                None,
            )

            if accepted_prediction:
                detected_label, confidence = accepted_prediction
                detected = detected_label
            elif top_label in related:
                detected = top_label
                confidence = (
                    top_probability * self._language_id_config.thresholds.related_label_multiplier
                )
            else:
                detected = top_label
                confidence = top_probability * self._language_id_config.thresholds.mismatch_multiplier

            details = {
                "predictions": predictions,
                "top_label": top_label,
                "top_probability": top_probability,
                "accepted_labels": sorted(accepted),
                "related_labels": sorted(related),
                "contaminant_labels": sorted(contaminants),
            }
            if contaminant_prediction:
                label, probability = contaminant_prediction
                if probability >= self._language_id_config.thresholds.contaminant_warning:
                    details["contaminant_warning"] = {"label": label, "probability": probability}
                if accepted_prediction:
                    margin = accepted_prediction[1] - probability
                    if margin < self._language_id_config.thresholds.code_switch_margin:
                        details["code_switch_suspect"] = {
                            "accepted_label": accepted_prediction[0],
                            "accepted_probability": accepted_prediction[1],
                            "contaminant_label": label,
                            "contaminant_probability": probability,
                            "margin": margin,
                        }

            return LanguageDetectionResult(
                detected=detected,
                confidence=max(0.0, min(1.0, confidence)),
                method="glotlid",
                details=details,
            )
        except Exception as e:
            logger.warning("language_detector.glotlid_error", error=str(e))
            return LanguageDetectionResult(
                detected="unknown",
                confidence=0.0,
                method="glotlid",
                details={"error": str(e)},
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
        result = self.detect(text, expected_language)
        if threshold is not None:
            effective_threshold = threshold
        elif result.method == "glotlid":
            effective_threshold = self._language_id_config.threshold_for(
                expected_language,
                _token_count(text),
            )
        else:
            effective_threshold = self._config.language_detection.default_threshold
            if expected_language.lower() in _LOW_RESOURCE_FALLBACK:
                effective_threshold = self._config.language_detection.low_resource_threshold

        result.details["threshold"] = effective_threshold
        passes = result.confidence >= effective_threshold
        return passes, result
