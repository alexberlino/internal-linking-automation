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
# PAGE_SIMILARITY_FLOOR and SENTENCE_SIMILARITY_FLOOR are now read from
# client_config["similarity"] at runtime. These fallback constants are only
# used if find_internal_link_opportunities is called without a client_config
# that contains a "similarity" block (e.g. in unit tests).
_DEFAULT_PAGE_SIMILARITY_FLOOR = 0.5
_DEFAULT_SENTENCE_SIMILARITY_FLOOR = 0.65


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

    if path in {"", "/"}:
        return False

    if "/category/" in path or "/tag/" in path or "/author/" in path:
        return False

    if query:
        return False

    return True


def build_topic_tokens(target_row: pd.Series) -> List[str]:
    """
    Build a vocabulary of content tokens for a target page.

    Sources (in priority order):
      1. The target's pipe-separated keyword list (rules.csv / targets CSV) —
         most reliable signal since these are the exact phrases we want anchors
         drawn from.
      2. title, h1, meta_description — fallback when keyword list is absent.

    All tokens are lowercased and deduplicated. Tokens shorter than 4 chars
    are excluded to avoid matching stopwords and prepositions.
    """
    tokens: set = set()

    # 1. Keyword list — split on pipe, then tokenise each phrase
    raw_keywords = target_row.get("keywords", "") or target_row.get("raw_keywords", "")
    if isinstance(raw_keywords, str) and raw_keywords.strip():
        for phrase in raw_keywords.split("|"):
            for tok in re.findall(r"[a-z0-9]{4,}", phrase.lower()):
                tokens.add(tok)

    # 2. Title / h1 / meta fallback
    text = " ".join([
        str(target_row.get("title", "")),
        str(target_row.get("h1", "")),
        str(target_row.get("meta_description", "")),
    ]).lower()
    for tok in re.findall(r"[a-z0-9]{4,}", text):
        tokens.add(tok)

    return list(tokens)


# --------------------------------------------------
# Volume cap helpers
# --------------------------------------------------

def _max_suggestions_for_target(
    current_inbound: int,
    inbound_link_caps: list,
) -> int:
    """
    Return the maximum number of new link suggestions allowed for a target
    page based on how many inbound links it already has.

    The caps list is ordered from most-deprived to best-linked:
      [{"min_inbound": 0,  "max_inbound": 0,    "max_suggestions": 10},
       {"min_inbound": 1,  "max_inbound": 5,    "max_suggestions": 7},
       {"min_inbound": 6,  "max_inbound": 15,   "max_suggestions": 5},
       {"min_inbound": 16, "max_inbound": 39,   "max_suggestions": 2},
       {"min_inbound": 40, "max_inbound": None, "max_suggestions": 0}]

    Pages at 40+ inbound links get 0 new suggestions — they are well-linked
    enough that additional suggestions add no meaningful value.
    """
    for band in inbound_link_caps:
        min_ib = band.get("min_inbound", 0)
        max_ib = band.get("max_inbound")  # None means no upper bound
        if current_inbound >= min_ib and (max_ib is None or current_inbound <= max_ib):
            return int(band.get("max_suggestions", 0))
    return 0


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

    # Read similarity floors from config; fall back to module-level defaults
    # so existing call sites without a "similarity" block keep working.
    similarity_cfg = client_config.get("similarity", {})
    page_similarity_floor = float(
        similarity_cfg.get("page_similarity_floor", _DEFAULT_PAGE_SIMILARITY_FLOOR)
    )
    sentence_similarity_floor = float(
        similarity_cfg.get("sentence_similarity_floor", _DEFAULT_SENTENCE_SIMILARITY_FLOOR)
    )

    # Volume caps
    volume_cfg = client_config.get("volume", {})
    max_targets_per_source = int(volume_cfg.get("max_targets_per_source", 5))
    inbound_link_caps = volume_cfg.get("inbound_link_caps", [
        {"min_inbound": 0,  "max_inbound": 0,    "max_suggestions": 10},
        {"min_inbound": 1,  "max_inbound": 5,    "max_suggestions": 7},
        {"min_inbound": 6,  "max_inbound": 15,   "max_suggestions": 5},
        {"min_inbound": 16, "max_inbound": 39,   "max_suggestions": 2},
        {"min_inbound": 40, "max_inbound": None, "max_suggestions": 0},
    ])

    # Pre-build inbound link count map from audited_df
    inbound_count_map: Dict[str, int] = {}
    for _, row in audited_df.iterrows():
        url_key = normalize_url(row.get(target_url_col, ""))
        if url_key:
            inbound_count_map[url_key] = int(row.get("receiving_links", 0))

    # Track how many suggestions have already been made per target
    suggestions_per_target: Dict[str, int] = {}

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

            if page_sim < page_similarity_floor:
                continue

            best_score = 0.0
            best_sentence = ""

            for sentence in sentences:
                if sentence not in sentence_embedding_cache:
                    sentence_embedding_cache[sentence] = model.encode(sentence)

                sim = cosine_similarity(
                    [sentence_embedding_cache[sentence]],
                    [target_vector],
                )[0][0]

                if sim >= sentence_similarity_floor:
                    sentence_lc = sentence.lower()
                    sentence_tokens = set(re.findall(r"[a-z0-9]{4,}", sentence_lc))
                    token_overlap = len(sentence_tokens.intersection(set(topic_tokens)))
                    if token_overlap < 1:
                        continue
                    if sim > best_score:
                        best_score = sim
                        best_sentence = sentence

            if best_score == 0.0:
                continue

            # Inbound link cap: skip if target already has enough suggestions
            current_inbound = inbound_count_map.get(target_url, 0)
            allowed = _max_suggestions_for_target(current_inbound, inbound_link_caps)
            already_suggested = suggestions_per_target.get(target_url, 0)
            if allowed == 0 or already_suggested >= allowed:
                continue

            opportunities.append({
                "source_url": source_url,
                "target_url": target_url,
                "target_priority_tier": tier_map.get(target_url, ""),
                "confidence": round(best_score, 3),
                "matched_sentence": best_sentence,
            })
            suggestions_per_target[target_url] = already_suggested + 1

    out = pd.DataFrame(opportunities)
    if out.empty:
        return out

    # Cap: each source can suggest links to at most max_targets_per_source targets.
    # Within each source, keep the highest-confidence suggestions.
    out = (
        out.sort_values("confidence", ascending=False)
        .groupby("source_url", group_keys=False)
        .head(max_targets_per_source)
    )

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
