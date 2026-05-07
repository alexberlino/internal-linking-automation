# phases/phase_5_reporting.py

from typing import List, Dict, Union, Optional, Any, Callable
from pathlib import Path
import re
from urllib.parse import urlparse
import pandas as pd


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
    Covers EN + DE common patterns. Add languages here if needed later.
    """
    if not isinstance(anchor, str):
        return False
    a = anchor.strip()
    if not a:
        return False
    a_lc = a.lower()

    # Read-time prefix: "9 min Lesezeit ...", "5 min read ...", "10-minute read ..."
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
    """
    Returns a function that says whether a URL points to a blog page.
    A URL is a blog URL if its path equals or starts-with any configured blog_path.
    """
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
    """
    Returns a function that says whether a URL is the homepage.
    Treats '', '/', and the configured homepage path as homepage.
    """
    home_path = urlparse(homepage_url or "").path.rstrip("/").lower()

    def is_homepage_url(url: str) -> bool:
        if not isinstance(url, str) or not url:
            return False
        path = urlparse(url).path.rstrip("/").lower()
        return path == "" or path == home_path

    return is_homepage_url


# -------------------------------------------------------------------
# Tab 3: Anchor Text Optimization (config-driven)
# -------------------------------------------------------------------

def build_anchor_optimization_report(
    raw_links_list: List[Dict],
    audited_df: pd.DataFrame,
    client_config: Dict[str, Any],
) -> pd.DataFrame:
    """
    Flag existing links where:
      - the anchor matches a commercial intent rule for the source's language, AND
      - the current destination is a blog URL or the homepage.
    Suggest the proper commercial destination instead.
    """
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

    # ------------------------------------------------------------------
    # Pre-filter: drop sitewide / footer / nav links.
    # A link is sitewide if either:
    #   (a) anchor text is in the configured sitewide set, OR
    #   (b) the (anchor, dest) pair appears on >= sitewide_min_repeats source pages.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Pre-compile rule patterns once, grouped by language.
    # ------------------------------------------------------------------
    compiled_rules_by_lang: Dict[str, List] = {}
    for rule in rules:
        compiled = (
            rule["kw"],
            re.compile(rule["pattern"], flags=re.IGNORECASE),
            rule["target_url"],
        )
        compiled_rules_by_lang.setdefault(rule["language"], []).append(compiled)

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

        # Pick the rule set matching the source page's language.
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

        # Skip if the link is already pointing where we'd suggest.
        if normalize_url_no_query(dst) == normalize_url_no_query(target_url):
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
# Tab 1: Page Summary Report (unchanged)
# -------------------------------------------------------------------

def build_page_summary_report(
    audited_df: pd.DataFrame,
    anchor_optimization_df: Optional[pd.DataFrame] = None,
    opportunities_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Per-page snapshot for tier A and B pages: how many internal links each
    page currently receives, plus counts of suggested fixes. Sorted so the
    most under-linked priority pages surface first.
    """
    report = audited_df[audited_df["priority_tier"].isin(["A", "B"])].copy()

    # Number of new-link opportunities pointing at each target.
    if opportunities_df is not None and not opportunities_df.empty and "target_url" in opportunities_df.columns:
        opp_counts = opportunities_df.groupby("target_url").size()
        report["new_link_opportunities"] = report["url"].map(opp_counts).fillna(0).astype(int)
    else:
        report["new_link_opportunities"] = 0

    # How many existing links currently point at the wrong place but, after
    # redirect, will land on this page. For a commercial page this is the
    # signal "X new inbound links coming my way once the anchor cleanup is done."
    if anchor_optimization_df is not None and not anchor_optimization_df.empty:
        # Normalize trailing slashes on both sides so URLs match consistently.
        targets_norm = anchor_optimization_df["suggested_destination"].str.rstrip("/")
        anchor_counts = targets_norm.value_counts()
        report["incoming_redirects"] = (
            report["url"].str.rstrip("/").map(anchor_counts).fillna(0).astype(int)
        )
    else:
        report["incoming_redirects"] = 0

    return report[
        ["url", "priority_tier", "receiving_links",
         "has_generic_anchors", "new_link_opportunities", "incoming_redirects"]
    ].sort_values(
        by=["priority_tier", "receiving_links"],
        ascending=[True, True],   # priority A first, fewest existing links first
    )
# -------------------------------------------------------------------
# Tab 2: Actionable Opportunities (unchanged)
# -------------------------------------------------------------------

def build_actionable_opportunities(
    opportunities: pd.DataFrame,
    audited_df: pd.DataFrame,
) -> pd.DataFrame:
    if opportunities is None or opportunities.empty or "target_url" not in opportunities.columns:
        return pd.DataFrame()

    opp_df = opportunities.copy()
    priority_map = {
        str(u).strip().rstrip("/"): t
        for u, t in zip(audited_df["url"], audited_df["priority_tier"])
    }
    opp_df["target_priority"] = opp_df["target_url"].map(priority_map)

    opp_df = opp_df[
        ["target_url", "target_priority", "source_url", "confidence"]
    ]


    return opp_df.sort_values(
        by=["target_priority", "confidence"],
        ascending=[True, False],
    )


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
    actionable_df = build_actionable_opportunities(opportunities, audited_df)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        page_summary_df.to_excel(writer, sheet_name="Page_Summary_Report", index=False)
        actionable_df.to_excel(writer, sheet_name="Actionable_Opportunities", index=False)
        anchor_optimization_df.to_excel(writer, sheet_name="Anchor_Text_Optimization", index=False)