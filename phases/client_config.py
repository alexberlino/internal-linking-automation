# phases/client_config.py

from pathlib import Path
from typing import Union, Dict, List, Any
import json
import re
import pandas as pd


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
    # Lowercase patterns once for case-insensitive matching
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


def load_client_config(config_dir: Union[str, Path]) -> Dict[str, Any]:
    """
    Loads per-client configuration from a directory containing:

      settings.json:
        - homepage_url           (str)         e.g. "https://www.proofserve.com/"
        - blog_paths             (list[str])   e.g. ["/blog", "/learn"]
        - languages              (list[str])   e.g. ["en"] or ["en","de","fr","es"]
        - default_language       (str)         e.g. "en"
        - language_url_patterns  (dict)        e.g. {"de": "/de/", "fr": "/fr/"}
                                                Empty {} means single-language site.
        - brand_pattern          (str, opt)    raw regex for bare-brand anchor
        - sitewide_anchors       (list[str])   anchors to ignore (footer/nav)
        - sitewide_min_repeats   (int, opt)    default 30

      rules.csv:
        Required columns: target_url, keywords
        Optional columns: label, language

        - keywords: pipe-separated phrases. Plain phrases get wrapped with \\b...\\b
                    and tolerant whitespace. Prefix with "regex:" to pass through raw.
        - language: which language this rule applies to. If omitted or empty,
                    rule applies to default_language.
        - label:    human-readable name for the rule (shown in rule_triggered).
                    Defaults to the target_url if omitted.

    Returns a dict consumed by phase_5_reporting.py:
      {
        "rules":               [{"kw","pattern","target_url","language"}, ...]
        "homepage_url":        str
        "blog_paths":          list[str]
        "languages":           list[str]
        "default_language":    str
        "detect_language":     callable(url) -> language_code
        "sitewide_anchors":    set[str]
        "sitewide_min_repeats":int
      }
    """
    config_dir = Path(config_dir)
    rules_path = config_dir / "rules.csv"
    settings_path = config_dir / "settings.json"

    if not settings_path.exists():
        raise FileNotFoundError(f"settings.json not found: {settings_path}")
    if not rules_path.exists():
        raise FileNotFoundError(f"rules.csv not found: {rules_path}")

    # ---------------- settings.json ----------------
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
    # Validate every language in patterns is declared in `languages`
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

    brand_pattern = (settings.get("brand_pattern") or "").strip()

    # ---------------- rules.csv ----------------
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

        phrases = [p.strip() for p in keywords_raw.split("|") if p.strip()]
        regex_parts = [r for r in (_phrase_to_regex(p) for p in phrases) if r]
        if not regex_parts:
            continue

        # Validate the compiled pattern early so bad regex fails fast
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
        })

    # Append the brand rule last (lowest priority)
    if brand_pattern and homepage_url:
        try:
            re.compile(brand_pattern, flags=re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"settings.json: invalid brand_pattern - {e}")
        rules.append({
            "kw": "brand",
            "pattern": brand_pattern,
            "target_url": homepage_url + "/",  # preserve trailing slash on homepage
            "language": default_language,
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
    }