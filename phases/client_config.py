# phases/client_config.py

from pathlib import Path
from typing import Union, Dict, List, Any, Set
import json
import re
import pandas as pd


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _phrase_to_regex(phrase: str) -> str:
    """
    Convert a keyword entry to a regex pattern.
    Two modes:
      1. Plain phrase  -> wrapped with word boundaries and tolerant whitespace.
         "process server pricing"  ->  r"\\bprocess\\s+server\\s+pricing\\b"
      2. Raw regex     -> prefix with "regex:" to pass through unchanged.
         "regex:\\bskip\\s+trac(?:ing|e)\\b"  ->  r"\\bskip\\s+trac(?:ing|e)\\b"
    Empty input returns "".
    """
    phrase = phrase.strip()
    if not phrase:
        return ""
    if phrase.lower().startswith("regex:"):
        return phrase[6:].strip()
    tokens = [t for t in re.split(r"\s+", phrase) if t]
    if not tokens:
        return ""
    return r"\b" + r"\s+".join(re.escape(t) for t in tokens) + r"\b"


def _detect_language_factory(
    language_url_patterns: Dict[str, str],
    default_language: str,
):
    """
    Returns a function url -> language_code.
    First substring match wins (dict iteration order = insertion order in Py 3.7+).
    If no pattern matches, returns default_language.
    """
    patterns = [(lang, pat.lower()) for lang, pat in language_url_patterns.items() if pat]

    def detect_language(url: str) -> str:
        if not isinstance(url, str) or not url:
            return default_language
        url_lc = url.lower()
        for lang, pat in patterns:
            if pat in url_lc:
                return lang
        return default_language

    return detect_language


# -------------------------------------------------------------------
# Anchor config defaults
# Used when settings.json does not define an "anchor" block.
# -------------------------------------------------------------------

_DEFAULT_ANCHOR_CONFIG = {
    "source": "target_keywords",
    "selection": {
        "method": "best_keyword_overlap",
        "min_overlap_tokens": 1,
    },
    "min_words": 1,
    "single_word_rule": "must_exist_in_target_keywords",
    "blocklist": {
        "apply_brand_pattern": True,
        "stopwords": [
            "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
            "been", "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "that", "this", "these",
            "those", "it", "its", "we", "our", "they", "their", "you", "your",
            "how", "what", "which", "who", "when", "where", "why",
        ],
        "reject_if_only_brand_plus_stopword": True,
        "min_char_length": 4,
    },
}

_DEFAULT_CONFIDENCE_CONFIG = {
    "penalties": {
        "anchor_not_in_target_keywords": 0.55,
        "anchor_is_brand_only": 0.50,
        "anchor_is_single_word_not_in_keywords": 0.60,
        "anchor_is_stopword_or_preposition": 0.30,
        "anchor_is_brand_plus_stopword": 0.45,
    },
    "tier_thresholds": {
        "strong": 0.85,
        "moderate": 0.70,
        "weak": 0.55,
    },
    "discard_below": 0.55,
}

_DEFAULT_DEDUPLICATION_CONFIG = {
    "enabled": True,
    "scope": "source_target_pair",
    "keep": "highest_confidence",
    "output_discarded": False,
}

_DEFAULT_SIMILARITY_CONFIG = {
    "page_similarity_floor": 0.65,
    "sentence_similarity_floor": 0.75,
}

_DEFAULT_VOLUME_CONFIG = {
    "max_targets_per_source": 5,
    "_comment_max_targets": "A single source blog post can suggest links to at most this many targets. Only the highest-confidence suggestions survive.",

    "inbound_link_caps": [
        {"min_inbound": 0,  "max_inbound": 0,  "max_suggestions": 10},
        {"min_inbound": 1,  "max_inbound": 5,  "max_suggestions": 7},
        {"min_inbound": 6,  "max_inbound": 15, "max_suggestions": 5},
        {"min_inbound": 16, "max_inbound": 39, "max_suggestions": 2},
        {"min_inbound": 40, "max_inbound": None, "max_suggestions": 0},
    ],
    "_comment_inbound_caps": "Controls how many new link suggestions a target page can receive based on how many inbound links it already has. Pages at 40+ get no new suggestions.",
}


# -------------------------------------------------------------------
# Anchor blocklist compiler
# -------------------------------------------------------------------

def _compile_anchor_blocklist(
    anchor_cfg: Dict[str, Any],
    brand_pattern: str,
) -> Dict[str, Any]:
    """
    Returns a ready-to-use blocklist dict consumed by phase 5:
      {
        "stopwords":                   set[str],
        "apply_brand_pattern":         bool,
        "brand_re":                    re.Pattern | None,
        "reject_brand_plus_stopword":  bool,
        "min_char_length":             int,
        "min_words":                   int,
        "single_word_rule":            str,
      }
    """
    blocklist_cfg = anchor_cfg.get("blocklist", {})

    stopwords: Set[str] = {
        w.strip().lower()
        for w in blocklist_cfg.get("stopwords", _DEFAULT_ANCHOR_CONFIG["blocklist"]["stopwords"])
        if w.strip()
    }

    apply_brand = blocklist_cfg.get(
        "apply_brand_pattern",
        _DEFAULT_ANCHOR_CONFIG["blocklist"]["apply_brand_pattern"],
    )

    brand_re = None
    if apply_brand and brand_pattern:
        try:
            brand_re = re.compile(brand_pattern, flags=re.IGNORECASE)
        except re.error:
            brand_re = None

    return {
        "stopwords": stopwords,
        "apply_brand_pattern": apply_brand,
        "brand_re": brand_re,
        "reject_brand_plus_stopword": blocklist_cfg.get(
            "reject_if_only_brand_plus_stopword",
            _DEFAULT_ANCHOR_CONFIG["blocklist"]["reject_if_only_brand_plus_stopword"],
        ),
        "min_char_length": int(blocklist_cfg.get(
            "min_char_length",
            _DEFAULT_ANCHOR_CONFIG["blocklist"]["min_char_length"],
        )),
        "min_words": int(anchor_cfg.get("min_words", _DEFAULT_ANCHOR_CONFIG["min_words"])),
        "single_word_rule": anchor_cfg.get(
            "single_word_rule",
            _DEFAULT_ANCHOR_CONFIG["single_word_rule"],
        ),
    }


# -------------------------------------------------------------------
# Main loader
# -------------------------------------------------------------------

def load_client_config(config_dir: Union[str, Path]) -> Dict[str, Any]:
    """
    Loads per-client configuration from a directory containing:

      settings.json:
        - homepage_url              (str)
        - blog_paths                (list[str])
        - languages                 (list[str])
        - default_language          (str)
        - language_url_patterns     (dict)
        - brand_pattern             (str, opt)   raw regex for bare-brand anchor
        - sitewide_anchors          (list[str])
        - sitewide_min_repeats      (int, opt)   default 30
        - anchor                    (dict, opt)  anchor quality rules
        - confidence                (dict, opt)  scoring penalties + tier thresholds
        - deduplication             (dict, opt)  per source-target pair dedup rules
        - similarity                (dict, opt)  page + sentence floor overrides

      rules.csv:
        Required columns: target_url, keywords
        Optional columns: label, language

    Returns a dict consumed by phase_4 and phase_5:
      {
        "rules":                   list[dict]
        "homepage_url":            str
        "blog_paths":              list[str]
        "languages":               list[str]
        "default_language":        str
        "detect_language":         callable(url) -> str
        "sitewide_anchors":        set[str]
        "sitewide_min_repeats":    int
        "brand_pattern":           str          raw regex string, "" if not set
        "anchor":                  dict         full anchor config block
        "anchor_blocklist":        dict         compiled blocklist ready for phase 5
        "confidence":              dict         penalties + tier thresholds
        "deduplication":           dict         dedup rules
        "similarity":              dict         page + sentence floor values
      }
    """
    config_dir = Path(config_dir)
    rules_path = config_dir / "rules.csv"
    settings_path = config_dir / "settings.json"

    if not settings_path.exists():
        raise FileNotFoundError(f"settings.json not found: {settings_path}")
    if not rules_path.exists():
        raise FileNotFoundError(f"rules.csv not found: {rules_path}")

    # ----------------------------------------------------------------
    # settings.json
    # ----------------------------------------------------------------
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)

    homepage_url = (settings.get("homepage_url") or "").strip().rstrip("/")
    blog_paths = [p.lower().rstrip("/") for p in settings.get("blog_paths", []) if p]
    languages = settings.get("languages", ["en"])
    default_language = (settings.get("default_language") or "en").strip().lower()

    if default_language not in languages:
        raise ValueError(
            f"default_language '{default_language}' not in languages {languages}"
        )

    language_url_patterns = settings.get("language_url_patterns", {}) or {}
    for lang in language_url_patterns:
        if lang not in languages:
            raise ValueError(
                f"language_url_patterns has '{lang}' but it's not in languages {languages}"
            )

    detect_language = _detect_language_factory(language_url_patterns, default_language)

    sitewide_anchors = {
        a.strip().lower()
        for a in settings.get("sitewide_anchors", [])
        if a and a.strip()
    }
    sitewide_min_repeats = int(settings.get("sitewide_min_repeats", 30))

    # brand_pattern: validated, returned raw for phase 5 anchor filtering
    brand_pattern = (settings.get("brand_pattern") or "").strip()
    if brand_pattern:
        try:
            re.compile(brand_pattern, flags=re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"settings.json: invalid brand_pattern - {e}")

    # ----------------------------------------------------------------
    # Anchor quality config
    # ----------------------------------------------------------------
    anchor_cfg = settings.get("anchor", _DEFAULT_ANCHOR_CONFIG)

    # Back-fill any missing keys from defaults so phase 5 can always
    # read these keys without defensive get() calls everywhere.
    for key, default_val in _DEFAULT_ANCHOR_CONFIG.items():
        anchor_cfg.setdefault(key, default_val)
    anchor_cfg.setdefault("selection", _DEFAULT_ANCHOR_CONFIG["selection"])
    anchor_cfg["selection"].setdefault(
        "method", _DEFAULT_ANCHOR_CONFIG["selection"]["method"]
    )
    anchor_cfg["selection"].setdefault(
        "min_overlap_tokens", _DEFAULT_ANCHOR_CONFIG["selection"]["min_overlap_tokens"]
    )

    anchor_blocklist = _compile_anchor_blocklist(anchor_cfg, brand_pattern)

    # ----------------------------------------------------------------
    # Confidence penalties + tier thresholds
    # ----------------------------------------------------------------
    confidence_cfg = settings.get("confidence", _DEFAULT_CONFIDENCE_CONFIG)
    for key, default_val in _DEFAULT_CONFIDENCE_CONFIG.items():
        confidence_cfg.setdefault(key, default_val)

    # Validate tier thresholds are present and numeric
    tier_thresholds = confidence_cfg.get("tier_thresholds", {})
    for tier in ("strong", "moderate", "weak"):
        if tier not in tier_thresholds:
            tier_thresholds[tier] = _DEFAULT_CONFIDENCE_CONFIG["tier_thresholds"][tier]
    confidence_cfg["tier_thresholds"] = tier_thresholds

    # ----------------------------------------------------------------
    # Deduplication
    # ----------------------------------------------------------------
    dedup_cfg = settings.get("deduplication", _DEFAULT_DEDUPLICATION_CONFIG)
    for key, default_val in _DEFAULT_DEDUPLICATION_CONFIG.items():
        dedup_cfg.setdefault(key, default_val)

    # ----------------------------------------------------------------
    # Similarity floors (used by phase 4)
    # ----------------------------------------------------------------
    similarity_cfg = settings.get("similarity", _DEFAULT_SIMILARITY_CONFIG)
    for key, default_val in _DEFAULT_SIMILARITY_CONFIG.items():
        similarity_cfg.setdefault(key, default_val)

    # ----------------------------------------------------------------
    # Volume caps (used by phase 4)
    # ----------------------------------------------------------------
    volume_cfg = settings.get("volume", _DEFAULT_VOLUME_CONFIG)
    for key, default_val in _DEFAULT_VOLUME_CONFIG.items():
        volume_cfg.setdefault(key, default_val)

    # ----------------------------------------------------------------
    # rules.csv
    # ----------------------------------------------------------------
    rules_df = pd.read_csv(rules_path)
    rules_df.columns = [c.strip().lower() for c in rules_df.columns]

    required = {"target_url", "keywords"}
    missing = required - set(rules_df.columns)
    if missing:
        raise ValueError(f"rules.csv missing required columns: {missing}")

    has_label = "label" in rules_df.columns
    has_language = "language" in rules_df.columns

    rules: List[Dict[str, str]] = []

    for idx, row in rules_df.iterrows():
        target_url = str(row["target_url"]).strip()
        keywords_raw = str(row["keywords"]).strip()

        if not target_url or target_url.lower() == "nan":
            continue
        if not keywords_raw or keywords_raw.lower() == "nan":
            continue

        label = ""
        if has_label:
            label_val = str(row["label"]).strip()
            if label_val and label_val.lower() != "nan":
                label = label_val
        if not label:
            label = target_url

        rule_lang = default_language
        if has_language:
            lang_val = str(row["language"]).strip().lower()
            if lang_val and lang_val != "nan":
                if lang_val not in languages:
                    raise ValueError(
                        f"rules.csv row {idx}: language '{lang_val}' not in {languages}"
                    )
                rule_lang = lang_val

        keywords_stripped = keywords_raw.strip()
        if keywords_stripped.lower().startswith("regex:"):
            raw = keywords_stripped[6:].strip()
            if not raw:
                continue
            combined_pattern = raw
        else:
            phrases = [p.strip() for p in keywords_stripped.split("|") if p.strip()]
            regex_parts = [r for r in (_phrase_to_regex(p) for p in phrases) if r]
            if not regex_parts:
                continue
            combined_pattern = "|".join(regex_parts)

        try:
            re.compile(combined_pattern, flags=re.IGNORECASE)
        except re.error as e:
            raise ValueError(
                f"rules.csv row {idx} for {target_url}: invalid regex - {e}"
            )

        rules.append({
            "kw": label,
            "pattern": combined_pattern,
            "target_url": target_url,
            "language": rule_lang,
            "raw_keywords": keywords_stripped,
        })

    # Brand rule appended last (lowest priority in rule matching)
    if brand_pattern and homepage_url:
        rules.append({
            "kw": "brand",
            "pattern": brand_pattern,
            "target_url": homepage_url + "/",
            "language": default_language,
            "raw_keywords": "",
        })

    return {
        "rules": rules,
        "homepage_url": homepage_url,
        "blog_paths": blog_paths,
        "languages": languages,
        "default_language": default_language,
        "detect_language": detect_language,
        "sitewide_anchors": sitewide_anchors,
        "sitewide_min_repeats": sitewide_min_repeats,
        # New — available to all phases
        "brand_pattern": brand_pattern,
        "anchor": anchor_cfg,
        "anchor_blocklist": anchor_blocklist,
        "confidence": confidence_cfg,
        "deduplication": dedup_cfg,
        "similarity": similarity_cfg,
        "volume": volume_cfg,
    }
