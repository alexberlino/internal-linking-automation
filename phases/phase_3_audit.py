# phases/phase_3_audit.py

from typing import Dict, List, Set
import pandas as pd


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

GENERIC_ANCHORS = {
    "click here",
    "read more",
    "learn more",
    "more",
    "here",
}


def is_generic_anchor(anchor: str) -> bool:
    if not isinstance(anchor, str):
        return False
    return anchor.strip().lower() in GENERIC_ANCHORS


# -------------------------------------------------------------------
# Phase 3: Audit
# -------------------------------------------------------------------

def audit_internal_links(
    page_df: pd.DataFrame,
    crawled_urls: Set[str],
    raw_links_list: List[Dict],
    url_column: str = "url",
    priority_column: str = "priority_tier",
    score_column: str = "priority_score",
) -> pd.DataFrame:
    """
    Enriches page_df with internal linking audit metrics.
    """

    data = page_df.copy()

    # Ensure columns exist
    for col in [priority_column, score_column]:
        if col not in data.columns:
            raise ValueError(f"Missing column '{col}' in page_df.")

    # ---------------------------------------------------------------
    # Orphan check
    # ---------------------------------------------------------------
    data["is_orphan"] = ~data[url_column].isin(crawled_urls)

    # ---------------------------------------------------------------
    # Receiving link aggregation
    # ---------------------------------------------------------------
    links_df = pd.DataFrame(raw_links_list)

    if links_df.empty:
        data["receiving_links"] = 0
        data["link_equity_score"] = 0.0
        data["has_generic_anchors"] = False
        data["gap_status"] = "No internal links found"
        return data

    # Count receiving links
    receiving_counts = (
        links_df.groupby("dest")
        .size()
        .rename("receiving_links")
    )

    data = data.merge(
        receiving_counts,
        left_on=url_column,
        right_index=True,
        how="left",
    )

    data["receiving_links"] = data["receiving_links"].fillna(0).astype(int)

    # ---------------------------------------------------------------
    # Link equity score (weighted by source priority score)
    # ---------------------------------------------------------------
    source_scores = (
        data[[url_column, score_column]]
        .set_index(url_column)[score_column]
        .to_dict()
    )

    def equity_for_url(url: str) -> float:
        incoming = links_df[links_df["dest"] == url]
        return sum(
            source_scores.get(src, 0)
            for src in incoming["source"]
        )

    data["link_equity_score"] = data[url_column].apply(equity_for_url)

    # ---------------------------------------------------------------
    # Generic anchor check (important pages only)
    # ---------------------------------------------------------------
    generic_anchor_targets = (
        links_df[links_df["anchor"].apply(is_generic_anchor)]
        .groupby("dest")
        .size()
        .index
    )

    data["has_generic_anchors"] = data[url_column].isin(generic_anchor_targets)

    # ---------------------------------------------------------------
    # Gap status assignment
    # ---------------------------------------------------------------
    def gap_status(row):
        if row["is_orphan"]:
            return "CRITICAL: Orphan Page"
        if row[priority_column] in ("A", "B") and row["receiving_links"] == 0:
            return "High: Under-Linked"
        if row[priority_column] in ("A", "B") and row["has_generic_anchors"]:
            return "Medium: Poor Anchors"
        return "Healthy"

    data["gap_status"] = data.apply(gap_status, axis=1)

    return data
