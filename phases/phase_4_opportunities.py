# phases/phase_4_opportunities.py

import re
from urllib.parse import urlparse
from typing import Set, Tuple, Optional, List, Dict, Any, Callable

import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


# --------------------------------------------------
# Config
# --------------------------------------------------

MIN_SENTENCE_WORDS = 6
PAGE_SIMILARITY_FLOOR = 0.5      # blog→target page-level cosine threshold
SENTENCE_SIMILARITY_FLOOR = 0.65   # individual sentence cosine threshold


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
    """
    Normalize a URL for equality comparison:
      - lowercase scheme + host (path stays case-sensitive)
      - drop query and fragment
      - strip trailing slash
    Matches phase_5_reporting.normalize_url_no_query for cross-phase consistency.
    """
    if not isinstance(u, str):
        u = "" if pd.isna(u) else str(u)
    u = u.strip()
    if not u:
        return ""
    try:
        p = urlparse(u)
        normalized = p._replace(
            scheme=p.scheme.lower(),
            netloc=p.netloc.lower(),
            query="",
            fragment="",
        ).geturl()
        return normalized.rstrip("/")
    except Exception:
        return u.rstrip("/")


def split_into_sentences(text: Any) -> List[str]:
    if not isinstance(text, str) or pd.isna(text):
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.split()) >= MIN_SENTENCE_WORDS]


def _make_is_homepage(homepage_url: str) -> Callable[[str], bool]:
    """Compare a URL against the configured homepage, after normalization."""
    home_norm = normalize_url(homepage_url)

    def is_homepage(url: str) -> bool:
        return normalize_url(url) == home_norm

    return is_homepage


def _pad_url_for_lang_detect(url: str) -> str:
    """
    Ensure the URL ends with '/' so a config pattern like '/de/' can match
    URLs whose path ends exactly at the language code (e.g. '/de'). After
    normalize_url we have stripped the trailing slash, so we re-add one
    here only for the purpose of language detection.
    """
    if not isinstance(url, str) or not url:
        return url or ""
    return url.rstrip("/") + "/"


def is_valid_source_url(url: str) -> bool:
    if not isinstance(url, str) or not url:
        return False

    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()

    # exclude index/root
    if path in {"", "/"}:
        return False

    # exclude category, tag, author, pagination
    if "/category/" in path or "/tag/" in path or "/author/" in path:
        return False

    # exclude query strings
    if query:
        return False

    return True


def build_topic_tokens(target_row: pd.Series) -> List[str]:
    text = " ".join([
        str(target_row.get("title", "")),
        str(target_row.get("h1", "")),
        str(target_row.get("meta_description", "")),
    ]).lower()

    return list(set(re.findall(r"[a-z0-9]{4,}", text)))


# --------------------------------------------------
# Target embeddings (ALL tiers)
# --------------------------------------------------

def build_target_embeddings(audited_df: pd.DataFrame) -> Dict[str, Any]:
    url_col = first_existing_column(audited_df, ("url", "target_url", "page_url"))

    model = get_model()
    vectors: Dict[str, Any] = {}

    for _, row in audited_df.iterrows():
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
    client_config: Dict[str, Any],
) -> pd.DataFrame:

    blog_url_col = first_existing_column(blog_df, ("url", "source_url"))
    blog_content_col = first_existing_column(blog_df, ("content", "text", "body"))
    target_url_col = first_existing_column(audited_df, ("url", "target_url"))
    tier_col = first_existing_column(audited_df, ("priority_tier", "tier"))
    detect_language = client_config["detect_language"]
    is_homepage = _make_is_homepage(client_config["homepage_url"])

    model = get_model()
    opportunities: List[Dict[str, Any]] = []
    page_embedding_cache: Dict[str, Any] = {}
    sentence_embedding_cache: Dict[str, Any] = {}

    target_vectors = build_target_embeddings(audited_df)

    audited_lookup = {
        normalize_url(row[target_url_col]): row
        for _, row in audited_df.iterrows()
        if isinstance(row.get(target_url_col), str) or not pd.isna(row.get(target_url_col))
    }

    # Kept for output enrichment: each opportunity gets the target's tier
    # so downstream consumers (Phase 5, manual review) can sort/filter on it.
    tier_map = {
        normalize_url(row[target_url_col]): str(row[tier_col]).strip().upper()
        for _, row in audited_df.iterrows()
    }

    for target_url, target_vector in target_vectors.items():

        target_row = audited_lookup.get(target_url)
        if target_row is None:
            continue

        if is_homepage(target_url):
            continue
        # Use the original (un-normalized) URL for language detection so
        # config patterns like "/de/" still match URLs that ended at "/de/".
        target_url_raw = str(target_row[target_url_col])
        target_lang = detect_language(_pad_url_for_lang_detect(target_url_raw))
        topic_tokens = build_topic_tokens(target_row)

        for _, blog in blog_df.iterrows():
            source_url = normalize_url(blog[blog_url_col])

            if not source_url:
                continue
            if not is_valid_source_url(source_url):
                continue
            if source_url == target_url or (source_url, target_url) in existing_links:
                continue

            source_url_raw = str(blog[blog_url_col])
            source_lang = detect_language(_pad_url_for_lang_detect(source_url_raw))
            if source_lang != target_lang:
                continue

            content = str(blog[blog_content_col])
            if not content or content.lower() == "nan":
                continue

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
                    sentence_tokens = set(re.findall(r"[a-z0-9]{4,}", sentence_lc))
                    token_overlap = len(sentence_tokens.intersection(set(topic_tokens)))
                    if token_overlap < 1:
                        continue
                    best_score = max(best_score, sim)

            if best_score == 0.0:
                continue

            opportunities.append({
                "source_url": source_url,
                "target_url": target_url,
                "target_priority_tier": tier_map.get(target_url, ""),
                "confidence": round(best_score, 3),
            })

    out = pd.DataFrame(opportunities)
    if out.empty:
        return out

    out = out.sort_values(
        by=["target_url", "confidence"],
        ascending=[True, False],
    )

    return out.reset_index(drop=True)


# --------------------------------------------------
# Entry point
# --------------------------------------------------

def run_phase_4_opportunities(*args, **kwargs) -> pd.DataFrame:
    blog_df = kwargs.get("blog_df")
    audited_df = kwargs.get("audited_df") or kwargs.get("meta_df")
    raw_links_list = kwargs.get("raw_links_list")
    client_config = kwargs.get("client_config")

    if blog_df is None and len(args) > 0:
        blog_df = args[0]
    if audited_df is None and len(args) > 1:
        audited_df = args[1]
    if raw_links_list is None and len(args) > 2:
        raw_links_list = args[2]
    if client_config is None and len(args) > 3:
        client_config = args[3]

    if blog_df is None or audited_df is None or raw_links_list is None or client_config is None:
        raise ValueError(
            "Missing required inputs (blog_df, audited_df, raw_links_list, client_config)."
        )

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
        client_config=client_config,
    )