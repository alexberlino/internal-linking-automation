import re
from urllib.parse import urlparse
from typing import Set, Tuple, Optional, List, Dict, Any

import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


# --------------------------------------------------
# Config
# --------------------------------------------------

MIN_SENTENCE_WORDS = 6
PAGE_SIMILARITY_FLOOR = 0.50
SENTENCE_SIMILARITY_FLOOR = 0.60


# --------------------------------------------------
# Model (lazy-loaded)
# --------------------------------------------------

_MODEL: Optional[SentenceTransformer] = None


def get_model() -> SentenceTransformer:
    global _MODEL
    if _MODEL is None:
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _MODEL


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def first_existing_column(df: pd.DataFrame, candidates: Tuple[str, ...]) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    raise ValueError(f"None of these columns exist: {candidates}")


def normalize_url(u: Any) -> str:
    if not isinstance(u, str):
        u = "" if pd.isna(u) else str(u)
    return u.strip().rstrip("/")


def split_into_sentences(text: Any) -> List[str]:
    if not isinstance(text, str) or pd.isna(text):
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.split()) >= MIN_SENTENCE_WORDS]


def detect_language_from_url(url: str) -> str:
    """
    3-bucket language detection:
      - 'de'   for /de/... or .../de
      - 'en'   for /en/... or .../en
      - 'none' for URLs without a language subfolder
    """
    try:
        path = urlparse(url).path.lower()
    except Exception:
        path = (url or "").lower()

    p = path.strip("/")

    if not p:
        return "none"

    first = p.split("/", 1)[0]

    if first == "de" or p == "de":
        return "de"
    if first == "en" or p == "en":
        return "en"

    return "none"


def is_homepage(url: str) -> bool:
    # keeps your original heuristic
    return url.rstrip("/").count("/") <= 2


def get_best_anchor(target_row: pd.Series) -> Optional[str]:
    anchor = str(target_row.get("best_anchor_text", "")).strip()
    if not anchor or anchor.upper() == "N/A":
        return None
    return anchor


def build_topic_tokens(target_row: pd.Series) -> List[str]:
    text = " ".join([
        str(target_row.get("title", "")),
        str(target_row.get("h1", "")),
        str(target_row.get("meta_description", "")),
        str(target_row.get("best_anchor_text", "")),
    ]).lower()

    return list(set(re.findall(r"[a-z0-9]{4,}", text)))


# --------------------------------------------------
# Target embeddings (Tier A only)
# --------------------------------------------------

def build_target_embeddings(audited_df: pd.DataFrame) -> Dict[str, Any]:
    url_col = first_existing_column(audited_df, ("url", "target_url", "page_url"))
    tier_col = first_existing_column(audited_df, ("priority_tier", "tier"))

    model = get_model()
    vectors: Dict[str, Any] = {}

    for _, row in audited_df.iterrows():
        if str(row[tier_col]).strip().upper() != "A":
            continue

        intent_text = " ".join([
            str(row.get("title", "")),
            str(row.get("h1", "")),
            str(row.get("meta_description", "")),
        ]).strip() or str(row[url_col])

        vectors[normalize_url(row[url_col])] = model.encode(intent_text)

    return vectors


# --------------------------------------------------
# Phase 4 core
# --------------------------------------------------

def find_internal_link_opportunities(
    blog_df: pd.DataFrame,
    audited_df: pd.DataFrame,
    existing_links: Set[Tuple[str, str]],
) -> pd.DataFrame:

    blog_url_col = first_existing_column(blog_df, ("url", "source_url"))
    blog_content_col = first_existing_column(blog_df, ("content", "text", "body"))
    traffic_col = next(
        (c for c in ("non_branded_traffic", "traffic", "sessions") if c in blog_df.columns),
        None,
    )
    target_url_col = first_existing_column(audited_df, ("url", "target_url"))

    model = get_model()
    opportunities: List[Dict[str, Any]] = []

    page_embedding_cache: Dict[str, Any] = {}
    sentence_embedding_cache: Dict[str, Any] = {}

    target_vectors = build_target_embeddings(audited_df)

    # Build a fast lookup for target rows (normalized)
    audited_lookup = {
        normalize_url(row[target_url_col]): row
        for _, row in audited_df.iterrows()
        if isinstance(row.get(target_url_col), str) or not pd.isna(row.get(target_url_col))
    }

    for target_url, target_vector in target_vectors.items():

        target_row = audited_lookup.get(target_url)
        if target_row is None:
            continue

        # --- HARD RULES ---
        best_anchor = get_best_anchor(target_row)
        if not best_anchor:
            continue

        if is_homepage(target_url):
            continue

        target_lang = detect_language_from_url(target_url)
        topic_tokens = build_topic_tokens(target_row)

        for _, blog in blog_df.iterrows():
            source_url = normalize_url(blog[blog_url_col])

            if not source_url:
                continue

            # avoid self + duplicates
            if source_url == target_url or (source_url, target_url) in existing_links:
                continue

            source_lang = detect_language_from_url(source_url)

            # Strict rule: only link within same language bucket
            # - de ↔ de
            # - en ↔ en
            # - none ↔ none
            if source_lang != target_lang:
                continue

            content = str(blog[blog_content_col])
            if not content or content.lower() == "nan":
                continue

            source_traffic = (
                int(blog[traffic_col])
                if traffic_col and not pd.isna(blog[traffic_col])
                else 0
            )

            sentences = split_into_sentences(content)
            if not sentences:
                continue

            if source_url not in page_embedding_cache:
                page_embedding_cache[source_url] = model.encode(content)

            page_sim = cosine_similarity(
                [page_embedding_cache[source_url]],
                [target_vector],
            )[0][0]

            if page_sim < PAGE_SIMILARITY_FLOOR:
                continue

            best_score = 0.0

            for sentence in sentences:
                if sentence not in sentence_embedding_cache:
                    sentence_embedding_cache[sentence] = model.encode(sentence)

                sim = cosine_similarity(
                    [sentence_embedding_cache[sentence]],
                    [target_vector],
                )[0][0]

                if sim >= SENTENCE_SIMILARITY_FLOOR:
                    sentence_lc = sentence.lower()
                    if not any(tok in sentence_lc for tok in topic_tokens):
                        continue
                    best_score = max(best_score, sim)

            if best_score == 0.0:
                continue

            opportunities.append({
                "source_url": source_url,
                "target_url": target_url,
                "suggested_anchor": best_anchor,
                "source_non_branded_traffic": source_traffic,
                "confidence": round(best_score, 3),
            })

    return pd.DataFrame(opportunities)


# --------------------------------------------------
# Entry point
# --------------------------------------------------

def run_phase_4_opportunities(*args, **kwargs) -> pd.DataFrame:
    blog_df = kwargs.get("blog_df")
    audited_df = kwargs.get("audited_df") or kwargs.get("meta_df")
    raw_links_list = kwargs.get("raw_links_list")

    if blog_df is None and len(args) > 0:
        blog_df = args[0]
    if audited_df is None and len(args) > 1:
        audited_df = args[1]
    if raw_links_list is None and len(args) > 2:
        raw_links_list = args[2]

    if blog_df is None or audited_df is None or raw_links_list is None:
        raise ValueError("Missing required inputs.")

    assert "best_anchor_text" in audited_df.columns, "Missing best_anchor_text column"

    existing_links: Set[Tuple[str, str]] = set()
    for link in raw_links_list:
        src = normalize_url(link.get("source") or link.get("source_url"))
        dst = normalize_url(link.get("dest") or link.get("target_url"))
        if src and dst:
            existing_links.add((src, dst))

    return find_internal_link_opportunities(
        blog_df=blog_df,
        audited_df=audited_df,
        existing_links=existing_links,
    )
