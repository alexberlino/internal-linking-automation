# phases/phase_4_opportunities.py

import re
from typing import List, Dict
import pandas as pd


GENERIC_WORDS = {
    "software",
    "solution",
    "platform",
    "tool",
    "system",
    "for",
    "and",
    "with",
    "the",
    "a",
    "an",
}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def extract_primary_keyword(title: str, h1: str) -> str:
    """
    Extracts a conservative primary keyword from title + H1.
    Deterministic, SEO-safe.
    """

    text = f"{title} {h1}".lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    words = [
        w for w in text.split()
        if w not in GENERIC_WORDS and len(w) > 2
    ]

    if not words:
        return ""

    # Take first 2–3 meaningful words
    return " ".join(words[:3])


def already_linked(
    source_url: str,
    target_url: str,
    raw_links_list: List[Dict],
) -> bool:
    return any(
        l["source"] == source_url and l["dest"] == target_url
        for l in raw_links_list
    )


# -------------------------------------------------------------------
# Phase 4
# -------------------------------------------------------------------

def run_phase_4_opportunities(
    blog_df: pd.DataFrame,
    meta_df: pd.DataFrame,
    raw_links_list: List[Dict],
    min_priority: tuple = ("A", "B"),
) -> pd.DataFrame:
    """
    Finds internal linking opportunities from blog content to target pages.
    """

    opportunities = []

    # ---------------------------------------------------------------
    # Prepare targets
    # ---------------------------------------------------------------
    targets = meta_df[meta_df["importance"].isin(min_priority)].copy()

    targets["primary_keyword"] = targets.apply(
        lambda r: extract_primary_keyword(r["title"], r["h1"]),
        axis=1,
    )

    targets = targets[targets["primary_keyword"] != ""]

    # ---------------------------------------------------------------
    # Iterate sources → targets
    # ---------------------------------------------------------------
    for _, source in blog_df.iterrows():
        source_url = source["url"]
        content = source["content"].lower()

        for _, target in targets.iterrows():
            target_url = target["url"]
            keyword = target["primary_keyword"]

            # Skip if link already exists
            if already_linked(source_url, target_url, raw_links_list):
                continue

            # Keyword match
            if keyword in content:
                opportunities.append({
                    "source_url": source_url,
                    "target_url": target_url,
                    "suggested_anchor": keyword,
                    "target_importance": target["importance"],
                    "source_traffic": source.get("non_branded_traffic", 0),
                })

    # ---------------------------------------------------------------
    # Output
    # ---------------------------------------------------------------
    if not opportunities:
        return pd.DataFrame()

    df = pd.DataFrame(opportunities)

    # Prioritisation: target importance → source traffic
    df["importance_rank"] = df["target_importance"].map({"A": 1, "B": 2, "C": 3})
    df = df.sort_values(
        by=["importance_rank", "source_traffic"],
        ascending=[True, False],
    )

    return df.drop(columns=["importance_rank"])
