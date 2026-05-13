# phases/phase_5_reporting.py

from typing import List, Dict, Union, Optional, Any, Callable, Tuple
from pathlib import Path
import re
from urllib.parse import urlparse
import pandas as pd

from phases.phase_4_opportunities import normalize_url


# -------------------------------------------------------------------
# Anchor filters that are NOT client-specific
# -------------------------------------------------------------------

_DATE_ONLY_PATTERNS = [
    r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$",
    r"^\d{4}-\d{2}-\d{2}$",
    r"^\d{4}$",
]


def is_date_only_anchor(anchor: str) -> bool:
    if not isinstance(anchor, str):
        return False
    a = anchor.strip()
    if not a:
        return False
    return any(re.match(p, a) for p in _DATE_ONLY_PATTERNS)


def is_article_title_like_anchor(anchor: str) -> bool:
    """
    Exclude anchors that look like editorial headlines / listicles.
    Covers EN + DE common patterns.
    """
    if not isinstance(anchor, str):
        return False
    a = anchor.strip()
    if not a:
        return False
    a_lc = a.lower()

    if re.match(
        r"^\s*\d{1,3}\s*[-\s]\s*(min|minute|minuten)\s+(read|lesezeit|lesedauer)\b",
        a_lc,
    ):
        return True

    if re.match(
        r"^\s*\d{1,3}\s+(best|beste|top|tipps|tips|gründe|reasons|maßnahmen|measures|steps|schritte)\b",
        a_lc,
    ):
        return True

    if re.search(r"\b(vergleich|test|guide|anleitung|tutorial|checkliste|trends|liste|ranking)\b", a_lc):
        if len(a) >= 35:
            return True

    if len(a) >= 90:
        return True

    return False


def norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def normalize_url_no_query(url: str) -> str:
    if not isinstance(url, str):
        return ""
    p = urlparse(url)
    return p._replace(query="", fragment="").geturl().rstrip("/")


# -------------------------------------------------------------------
# Client-aware URL helpers (built from config at runtime)
# -------------------------------------------------------------------

def _make_is_blog_url(blog_paths: List[str]) -> Callable[[str], bool]:
    bp = [p.rstrip("/").lower() for p in blog_paths if p]

    def is_blog_url(url: str) -> bool:
        if not isinstance(url, str) or not url:
            return False
        path = urlparse(url).path.lower().rstrip("/")
        for prefix in bp:
            if path == prefix or path.startswith(prefix + "/"):
                return True
        return False

    return is_blog_url


def _make_is_homepage_url(homepage_url: str) -> Callable[[str], bool]:
    home_path = urlparse(homepage_url or "").path.rstrip("/").lower()

    def is_homepage_url(url: str) -> bool:
        if not isinstance(url, str) or not url:
            return False
        path = urlparse(url).path.rstrip("/").lower()
        return path == "" or path == home_path

    return is_homepage_url


# -------------------------------------------------------------------
# Destination filters
# -------------------------------------------------------------------

_LISTING_PATH_RE = re.compile(
    r"(?:^|/)(?:category|categories|tag|tags|author|authors|page)(?:/|$)"
)


def is_listing_destination(url: str) -> bool:
    if not isinstance(url, str) or not url:
        return False
    path = urlparse(url).path.lower()
    return bool(_LISTING_PATH_RE.search(path))


# -------------------------------------------------------------------
# Anchor quality gate (config-driven)
# -------------------------------------------------------------------

def _anchor_passes_quality_gate(
    anchor: str,
    anchor_blocklist: Dict[str, Any],
    target_keyword_phrases: List[str],
) -> Tuple[bool, str]:
    """
    Validate a candidate anchor against the compiled blocklist rules.

    Returns (passes: bool, rejection_reason: str).
    rejection_reason is "" when the anchor passes.

    Rules applied (in order):
      1. Empty / too short
      2. Stopword-only anchor
      3. Brand-only anchor
      4. Brand + stopword combination
      5. Single-word anchor not in target keyword list
      6. Multi-word anchor not in target keyword list (soft — penalised, not rejected)
    """
    if not isinstance(anchor, str) or not anchor.strip():
        return False, "empty"

    a = anchor.strip()
    a_lc = a.lower()

    # 1. Minimum character length
    if len(a) < anchor_blocklist.get("min_char_length", 4):
        return False, "too_short"

    stopwords: set = anchor_blocklist.get("stopwords", set())
    brand_re = anchor_blocklist.get("brand_re")

    # 2. Stopword-only
    if a_lc in stopwords:
        return False, "stopword"

    # 3. Brand-only
    if brand_re and re.fullmatch(brand_re.pattern, a, flags=re.IGNORECASE):
        return False, "brand_only"

    # 4. Brand + stopword (e.g. "with Hygraph", "About Hygraph")
    if anchor_blocklist.get("reject_brand_plus_stopword") and brand_re:
        words = a_lc.split()
        non_stop = [w for w in words if w not in stopwords]
        if non_stop and all(
            re.fullmatch(brand_re.pattern, w, flags=re.IGNORECASE) for w in non_stop
        ):
            return False, "brand_plus_stopword"

    # 5. Single-word rule
    words = a.split()
    if len(words) == 1:
        rule = anchor_blocklist.get("single_word_rule", "must_exist_in_target_keywords")
        if rule == "must_exist_in_target_keywords":
            # The single word must appear as a standalone phrase in the keyword list
            kw_phrases_lc = [p.strip().lower() for p in target_keyword_phrases]
            if a_lc not in kw_phrases_lc:
                return False, "single_word_not_in_keywords"

    return True, ""


def _apply_confidence_penalties(
    raw_confidence: float,
    anchor: str,
    passes_quality: bool,
    rejection_reason: str,
    anchor_in_keyword_list: bool,
    anchor_blocklist: Dict[str, Any],
    penalties: Dict[str, float],
) -> float:
    """
    Apply penalty multipliers to the raw confidence score.
    Penalties stack multiplicatively.
    Returns the penalised score, floored at 0.0.
    """
    score = raw_confidence

    if rejection_reason == "brand_only":
        score *= penalties.get("anchor_is_brand_only", 0.50)
    elif rejection_reason == "stopword":
        score *= penalties.get("anchor_is_stopword_or_preposition", 0.30)
    elif rejection_reason == "brand_plus_stopword":
        score *= penalties.get("anchor_is_brand_plus_stopword", 0.45)
    elif rejection_reason == "single_word_not_in_keywords":
        score *= penalties.get("anchor_is_single_word_not_in_keywords", 0.60)

    if not anchor_in_keyword_list:
        score *= penalties.get("anchor_not_in_target_keywords", 0.55)

    return max(round(score, 3), 0.0)


def _confidence_tier(score: float, thresholds: Dict[str, float]) -> str:
    if score >= thresholds.get("strong", 0.85):
        return "strong"
    if score >= thresholds.get("moderate", 0.70):
        return "moderate"
    if score >= thresholds.get("weak", 0.55):
        return "weak"
    return "discard"


# -------------------------------------------------------------------
# Keyword-list anchor selection (core fix)
# -------------------------------------------------------------------

def _keyword_phrases_for_target(
    target_url: str,
    rules_by_target: Dict[str, List[Dict[str, Any]]],
) -> List[str]:
    """
    Return the pipe-separated keyword phrases for a target URL,
    sourced from rules_by_target (built from rules.csv / targets CSV).
    """
    rules = rules_by_target.get(normalize_url(target_url), [])
    phrases: List[str] = []
    for r in rules:
        raw = r.get("raw_keywords", "") or ""
        if raw.lower().startswith("regex:"):
            continue
        for phrase in raw.split("|"):
            phrase = phrase.strip()
            if phrase:
                phrases.append(phrase)
    return phrases


def _score_phrase_against_sentence(phrase: str, sentence: str) -> int:
    """
    Count how many tokens from phrase appear in sentence (case-insensitive).
    Tokens shorter than 4 chars are ignored to avoid stopword noise.
    """
    phrase_tokens = {t for t in re.findall(r"[a-z0-9]{4,}", phrase.lower())}
    sentence_tokens = set(re.findall(r"[a-z0-9]{4,}", sentence.lower()))
    return len(phrase_tokens & sentence_tokens)


def _select_anchor_from_keyword_list(
    sentence: str,
    keyword_phrases: List[str],
    anchor_blocklist: Dict[str, Any],
    min_overlap_tokens: int = 1,
) -> Tuple[str, bool]:
    """
    Pick the best anchor phrase from the target's keyword list.

    Strategy:
      - Score each phrase by token overlap with the sentence.
      - Among phrases that meet min_overlap_tokens, prefer the longest
        (most specific) phrase.
      - Skip phrases that fail the quality gate.

    Returns (anchor, anchor_in_keyword_list).
    anchor_in_keyword_list is always True here since we're selecting
    directly from the list; it's False only for fallback anchors.
    """
    candidates: List[Tuple[int, int, str]] = []  # (overlap, length, phrase)

    for phrase in keyword_phrases:
        overlap = _score_phrase_against_sentence(phrase, sentence)
        if overlap < min_overlap_tokens:
            continue
        passes, _ = _anchor_passes_quality_gate(phrase, anchor_blocklist, keyword_phrases)
        if not passes:
            continue
        candidates.append((overlap, len(phrase.split()), phrase))

    if not candidates:
        return "", False

    # Sort: highest overlap first, then longest phrase as tiebreaker
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][2], True


# -------------------------------------------------------------------
# Legacy helpers (title/h1 fallback — kept for anchor_basis tracking)
# -------------------------------------------------------------------

def _build_rules_by_target(rules: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group rules by normalized target_url, with patterns pre-compiled."""
    by_target: Dict[str, List[Dict[str, Any]]] = {}
    for r in rules:
        key = normalize_url(r.get("target_url", ""))
        if not key:
            continue
        try:
            compiled = re.compile(r["pattern"], flags=re.IGNORECASE)
        except re.error:
            continue
        by_target.setdefault(key, []).append({
            "pattern": compiled,
            "language": r.get("language", ""),
            "raw_keywords": r.get("raw_keywords", ""),
        })
    return by_target


def _longest_contiguous_run(sentence: str, vocab: set) -> str:
    """Longest contiguous run of vocab words in the sentence."""
    if not sentence or not vocab:
        return ""
    word_matches = list(re.finditer(r"\w+", sentence))
    if not word_matches:
        return ""
    in_set = [m.group().lower() in vocab for m in word_matches]

    best_start = best_end = -1
    best_len = 0
    i = 0
    while i < len(in_set):
        if in_set[i]:
            j = i
            while j < len(in_set) and in_set[j]:
                j += 1
            if (j - i) > best_len:
                best_len = j - i
                best_start, best_end = i, j - 1
            i = j
        else:
            i += 1

    if best_len == 0:
        return ""
    return sentence[word_matches[best_start].start():word_matches[best_end].end()]


def _anchor_from_title_overlap(sentence: str, title: str, h1: str = "") -> str:
    """Bag-of-words match using title + h1 content words as vocabulary."""
    if not sentence:
        return ""
    vocab = {
        t for t in re.findall(r"[a-z0-9]+", f"{title} {h1}".lower())
        if len(t) >= 4
    }
    return _longest_contiguous_run(sentence, vocab)


# -------------------------------------------------------------------
# Anchor derivation — new priority chain
# -------------------------------------------------------------------

def _derive_anchor(
    sentence: str,
    target_url: str,
    title: str,
    h1: str,
    rules_by_target: Dict[str, List[Dict[str, Any]]],
    anchor_blocklist: Dict[str, Any],
    min_overlap_tokens: int = 1,
) -> Tuple[str, str, bool]:
    """
    Tiered anchor selection:
      1. keyword_list_match    — best phrase from target keyword list with
                                 sentence overlap (PRIMARY, fixes the core bug)
      2. title_overlap         — bag-of-words from title/h1 (fallback)
      3. rejected_no_valid_anchor — nothing usable found

    Returns (anchor, anchor_basis, anchor_in_keyword_list).
    """
    keyword_phrases = _keyword_phrases_for_target(target_url, rules_by_target)

    # Tier 1: keyword list match
    if keyword_phrases:
        anchor, in_kw_list = _select_anchor_from_keyword_list(
            sentence, keyword_phrases, anchor_blocklist, min_overlap_tokens
        )
        if anchor:
            return anchor, "keyword_list_match", True

    # Tier 2: title/h1 fallback
    anchor = _anchor_from_title_overlap(sentence, title, h1)
    if anchor:
        passes, _ = _anchor_passes_quality_gate(anchor, anchor_blocklist, keyword_phrases)
        if passes:
            return anchor, "keyword_list_fallback", False

    return "", "rejected_no_valid_anchor", False


# -------------------------------------------------------------------
# Deduplication (one row per source-target pair)
# -------------------------------------------------------------------

def _deduplicate_opportunities(
    df: pd.DataFrame,
    dedup_cfg: Dict[str, Any],
) -> pd.DataFrame:
    """
    Keep one row per (source_url, target_url) pair.
    Default strategy: keep the row with the highest penalised confidence.
    """
    if not dedup_cfg.get("enabled", True):
        return df
    if df.empty:
        return df
    if dedup_cfg.get("scope") != "source_target_pair":
        return df

    keep = dedup_cfg.get("keep", "highest_confidence")
    if keep == "highest_confidence":
        df = df.sort_values("confidence", ascending=False)
        df = df.drop_duplicates(subset=["source_url", "target_url"], keep="first")

    return df.reset_index(drop=True)


# -------------------------------------------------------------------
# Tab 3: Anchor Text Optimization (unchanged logic, config-driven)
# -------------------------------------------------------------------

def build_anchor_optimization_report(
    raw_links_list: List[Dict],
    audited_df: pd.DataFrame,
    client_config: Dict[str, Any],
) -> pd.DataFrame:
    rules = client_config["rules"]
    sitewide_anchors = client_config["sitewide_anchors"]
    sitewide_min_repeats = client_config["sitewide_min_repeats"]
    detect_language = client_config["detect_language"]

    is_blog_url = _make_is_blog_url(client_config["blog_paths"])
    is_homepage_url = _make_is_homepage_url(client_config["homepage_url"])

    links_df = pd.DataFrame(raw_links_list)
    if links_df.empty:
        return pd.DataFrame()

    for col in ("source", "dest", "anchor"):
        if col not in links_df.columns:
            return pd.DataFrame()

    links_df["source"] = links_df["source"].fillna("").astype(str)
    links_df["dest"] = links_df["dest"].fillna("").astype(str)
    links_df["anchor"] = links_df["anchor"].fillna("").astype(str)

    pair_counts = (
        links_df.groupby(["anchor", "dest"])["source"]
        .nunique()
        .rename("source_pages")
        .reset_index()
    )
    repeated_pairs = set(
        zip(
            pair_counts.loc[pair_counts["source_pages"] >= sitewide_min_repeats, "anchor"],
            pair_counts.loc[pair_counts["source_pages"] >= sitewide_min_repeats, "dest"],
        )
    )

    anchor_series_lc = links_df["anchor"].str.strip().str.lower()
    is_sitewide_anchor = anchor_series_lc.isin(sitewide_anchors)
    is_repeated_mask = pd.Series(
        [(a, d) in repeated_pairs for a, d in zip(links_df["anchor"], links_df["dest"])],
        index=links_df.index,
    )
    links_df = links_df.loc[~(is_sitewide_anchor | is_repeated_mask)].copy()

    compiled_rules_by_lang: Dict[str, List] = {}
    for rule in rules:
        compiled = (
            rule["kw"],
            re.compile(rule["pattern"], flags=re.IGNORECASE),
            rule["target_url"],
        )
        compiled_rules_by_lang.setdefault(rule["language"], []).append(compiled)

    dest_titles: Dict[str, Dict[str, str]] = {}
    if audited_df is not None and not audited_df.empty:
        title_col = "title" if "title" in audited_df.columns else None
        h1_col = "h1" if "h1" in audited_df.columns else None
        for _, ar in audited_df.iterrows():
            key = normalize_url(ar.get("url", ""))
            if not key:
                continue
            dest_titles[key] = {
                "title": norm(ar.get(title_col, "")) if title_col else "",
                "h1": norm(ar.get(h1_col, "")) if h1_col else "",
            }

    rows: List[Dict[str, Any]] = []

    for _, r in links_df.iterrows():
        src = r["source"].strip()
        dst = r["dest"].strip()
        anchor = r["anchor"].strip()

        if not anchor:
            continue
        if is_date_only_anchor(anchor):
            continue
        if is_article_title_like_anchor(anchor):
            continue
        if not (is_blog_url(dst) or is_homepage_url(dst)):
            continue
        if is_listing_destination(dst):
            continue

        anchor_norm = norm(anchor)
        dest_meta = dest_titles.get(normalize_url(dst))
        if dest_meta is not None:
            if anchor_norm == dest_meta["title"] or anchor_norm == dest_meta["h1"]:
                continue

        src_lang = detect_language(src)
        rules_for_lang = compiled_rules_by_lang.get(src_lang, [])
        if not rules_for_lang:
            continue

        anchor_lc = norm(anchor)
        matched = None
        for kw, pattern, target_url in rules_for_lang:
            if pattern.search(anchor_lc):
                matched = (kw, target_url)
                break
        if matched is None:
            continue

        kw, target_url = matched
        if normalize_url(dst) == normalize_url(target_url):
            continue

        rows.append({
            "page_to_edit": src,
            "destination_page": dst,
            "current_anchor": anchor,
            "suggested_destination": target_url,
            "rule_triggered": f"commercial_mapping: {kw}",
        })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).drop_duplicates(
        subset=["page_to_edit", "destination_page", "current_anchor", "suggested_destination"]
    )


# -------------------------------------------------------------------
# Tab 1: Page Summary Report
# -------------------------------------------------------------------

def build_page_summary_report(
    audited_df: pd.DataFrame,
    anchor_optimization_df: Optional[pd.DataFrame] = None,
    opportunities_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    report = audited_df[audited_df["priority_tier"].isin(["A", "B"])].copy()

    if opportunities_df is not None and not opportunities_df.empty and "target_url" in opportunities_df.columns:
        opp_counts = opportunities_df.groupby("target_url").size()
        report["new_link_opportunities"] = report["url"].map(opp_counts).fillna(0).astype(int)
    else:
        report["new_link_opportunities"] = 0

    if anchor_optimization_df is not None and not anchor_optimization_df.empty:
        targets_norm = anchor_optimization_df["suggested_destination"].str.rstrip("/")
        anchor_counts = targets_norm.value_counts()
        report["incoming_redirects"] = (
            report["url"].str.rstrip("/").map(anchor_counts).fillna(0).astype(int)
        )
    else:
        report["incoming_redirects"] = 0

    return report[
        ["url", "priority_tier", "gap_status", "receiving_links",
         "has_generic_anchors", "new_link_opportunities", "incoming_redirects"]
    ].sort_values(
        by=["priority_tier", "receiving_links"],
        ascending=[True, True],
    )


# -------------------------------------------------------------------
# Tab 2: Actionable Opportunities (rewritten anchor logic)
# -------------------------------------------------------------------

def build_actionable_opportunities(
    opportunities: pd.DataFrame,
    audited_df: pd.DataFrame,
    client_config: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    if opportunities is None or opportunities.empty or "target_url" not in opportunities.columns:
        return pd.DataFrame()

    opp_df = opportunities.copy()

    priority_map = {
        normalize_url(u): t
        for u, t in zip(audited_df["url"], audited_df["priority_tier"])
    }
    inbound_map = {
        normalize_url(u): n
        for u, n in zip(audited_df["url"], audited_df["receiving_links"])
    }
    title_map = {
        normalize_url(u): t
        for u, t in zip(audited_df["url"], audited_df["title"])
    }
    h1_series = audited_df["h1"] if "h1" in audited_df.columns else pd.Series([""] * len(audited_df))
    h1_map = {
        normalize_url(u): h
        for u, h in zip(audited_df["url"], h1_series)
    }

    opp_df["target_priority"] = opp_df["target_url"].map(priority_map)
    opp_df["current_inbound_links"] = (
        opp_df["target_url"].map(inbound_map).fillna(0).astype(int)
    )
    opp_df["target_title"] = opp_df["target_url"].map(title_map).fillna("")

    # ------------------------------------------------------------------
    # Anchor derivation + quality gating + confidence penalties
    # ------------------------------------------------------------------
    suggested_anchors: List[str] = []
    anchor_bases: List[str] = []
    penalised_confidences: List[float] = []

    if client_config is not None and "matched_sentence" in opp_df.columns:
        rules_by_target = _build_rules_by_target(client_config.get("rules", []))
        anchor_blocklist = client_config.get("anchor_blocklist", {})
        confidence_cfg = client_config.get("confidence", {})
        penalties = confidence_cfg.get("penalties", {})
        anchor_cfg = client_config.get("anchor", {})
        min_overlap_tokens = (
            anchor_cfg.get("selection", {}).get("min_overlap_tokens", 1)
        )
        discard_below = float(confidence_cfg.get("discard_below", 0.55))

        for _, row in opp_df.iterrows():
            target_url = row.get("target_url", "") or ""
            tu_norm = normalize_url(target_url)
            sentence = row.get("matched_sentence", "") or ""
            raw_conf = float(row.get("confidence", 0.0))

            anchor, basis, in_kw_list = _derive_anchor(
                sentence=sentence,
                target_url=target_url,
                title=title_map.get(tu_norm, "") or "",
                h1=h1_map.get(tu_norm, "") or "",
                rules_by_target=rules_by_target,
                anchor_blocklist=anchor_blocklist,
                min_overlap_tokens=min_overlap_tokens,
            )

            # Quality gate: if no valid anchor found, mark for discard
            if not anchor:
                suggested_anchors.append("")
                anchor_bases.append("rejected_no_valid_anchor")
                penalised_confidences.append(0.0)
                continue

            # Re-check quality (for fallback anchors)
            keyword_phrases = _keyword_phrases_for_target(target_url, rules_by_target)
            passes, rejection_reason = _anchor_passes_quality_gate(
                anchor, anchor_blocklist, keyword_phrases
            )

            penalised = _apply_confidence_penalties(
                raw_confidence=raw_conf,
                anchor=anchor,
                passes_quality=passes,
                rejection_reason=rejection_reason,
                anchor_in_keyword_list=in_kw_list,
                anchor_blocklist=anchor_blocklist,
                penalties=penalties,
            )

            suggested_anchors.append(anchor if passes else "")
            anchor_bases.append(basis if passes else "rejected_no_valid_anchor")
            penalised_confidences.append(penalised if passes else 0.0)
    else:
        suggested_anchors = [""] * len(opp_df)
        anchor_bases = [""] * len(opp_df)
        penalised_confidences = list(opp_df.get("confidence", [0.0] * len(opp_df)))

    opp_df["suggested_anchor"] = suggested_anchors
    opp_df["anchor_basis"] = anchor_bases
    opp_df["confidence"] = penalised_confidences

    # ------------------------------------------------------------------
    # Discard rows below threshold
    # ------------------------------------------------------------------
    discard_below = 0.55
    if client_config:
        discard_below = float(
            client_config.get("confidence", {}).get("discard_below", 0.55)
        )
    opp_df = opp_df[opp_df["confidence"] >= discard_below].copy()

    # ------------------------------------------------------------------
    # Confidence tier (from config thresholds, not hardcoded)
    # ------------------------------------------------------------------
    tier_thresholds = {}
    if client_config:
        tier_thresholds = client_config.get("confidence", {}).get("tier_thresholds", {})

    opp_df["confidence_tier"] = opp_df["confidence"].apply(
        lambda c: _confidence_tier(c, tier_thresholds)
    )

    # ------------------------------------------------------------------
    # Deduplication: one row per (source_url, target_url)
    # ------------------------------------------------------------------
    dedup_cfg = client_config.get("deduplication", {}) if client_config else {}
    opp_df = _deduplicate_opportunities(opp_df, dedup_cfg)

    # ------------------------------------------------------------------
    # Final column order
    # ------------------------------------------------------------------
    columns = [
        "target_url", "target_title", "target_priority",
        "current_inbound_links", "source_url", "confidence",
        "confidence_tier", "suggested_anchor", "anchor_basis",
    ]
    if "matched_sentence" in opp_df.columns:
        columns.append("matched_sentence")

    opp_df = opp_df[columns]

    return opp_df.sort_values(
        by=["target_priority", "confidence"],
        ascending=[True, False],
    )


# -------------------------------------------------------------------
# Bold anchor in Excel output
# -------------------------------------------------------------------

def _bold_anchors_in_actionable_sheet(writer, actionable_df: pd.DataFrame) -> None:
    if actionable_df is None or actionable_df.empty:
        return
    if "matched_sentence" not in actionable_df.columns or "suggested_anchor" not in actionable_df.columns:
        return
    try:
        from openpyxl.cell.rich_text import CellRichText, TextBlock
        from openpyxl.cell.text import InlineFont
    except ImportError:
        return

    ws = writer.sheets.get("Actionable_Opportunities")
    if ws is None:
        return

    cols = list(actionable_df.columns)
    sentence_col_idx = cols.index("matched_sentence") + 1
    bold_font = InlineFont(b=True)

    for row_offset, (_, row) in enumerate(actionable_df.iterrows()):
        sentence = row.get("matched_sentence") or ""
        anchor = row.get("suggested_anchor") or ""
        if not sentence or not anchor:
            continue
        idx = sentence.find(anchor)
        if idx == -1:
            continue
        parts = []
        if idx > 0:
            parts.append(sentence[:idx])
        parts.append(TextBlock(bold_font, anchor))
        end = idx + len(anchor)
        if end < len(sentence):
            parts.append(sentence[end:])
        try:
            ws.cell(row=row_offset + 2, column=sentence_col_idx).value = CellRichText(parts)
        except Exception:
            continue


# -------------------------------------------------------------------
# Phase 5 Entry Point
# -------------------------------------------------------------------

def export_internal_linking_report(
    audited_df: pd.DataFrame,
    opportunities: pd.DataFrame,
    raw_links_list: List[Dict],
    output_path: Union[str, Path],
    client_config: Dict[str, Any],
) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    anchor_optimization_df = build_anchor_optimization_report(
        raw_links_list, audited_df, client_config,
    )
    page_summary_df = build_page_summary_report(
        audited_df=audited_df,
        anchor_optimization_df=anchor_optimization_df,
        opportunities_df=opportunities,
    )
    actionable_df = build_actionable_opportunities(opportunities, audited_df, client_config)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        page_summary_df.to_excel(writer, sheet_name="Page_Summary_Report", index=False)
        actionable_df.to_excel(writer, sheet_name="Actionable_Opportunities", index=False)
        anchor_optimization_df.to_excel(writer, sheet_name="Anchor_Text_Optimization", index=False)
        try:
            _bold_anchors_in_actionable_sheet(writer, actionable_df)
        except Exception:
            pass