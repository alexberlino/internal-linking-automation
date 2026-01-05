# phases/phase_5_reporting.py

from typing import List, Dict, Union, Optional
from pathlib import Path
import pandas as pd


# -------------------------------------------------------------------
# GLOBAL CONFIG
# -------------------------------------------------------------------

BAD_ANCHORS = {
    "click here",
    "read more",
    "learn more",
    "more",
    "here",
    "this",
    "this page",
    "mehr erfahren",
    "hier",
    "weiterlesen",
}


def is_bad_anchor(anchor: str) -> bool:
    if not isinstance(anchor, str):
        return True
    a = anchor.lower().strip()
    return not a or a in BAD_ANCHORS or len(a.split()) < 2


# -------------------------------------------------------------------
# Tab 1: Page Summary Report
# -------------------------------------------------------------------

def build_page_summary_report(
    audited_df: pd.DataFrame,
    anchor_optimization_df: Optional[pd.DataFrame] = None,
    opportunities_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Page summary with meaningful before / after.
    Only Tier A & B.
    """

    # --------------------------------------------------
    # FILTER: only A & B
    # --------------------------------------------------
    report = audited_df[
        audited_df["priority_tier"].isin(["A", "B"])
    ].copy()

    # --------------------------------------------------
    # BEFORE: based on gap_status
    # --------------------------------------------------
    report["before"] = report["gap_status"].map({
        "Medium: Poor Anchors": "Uses generic or non-descriptive anchor text",
        "High: Under-Linked": "Receives insufficient internal links",
    }).fillna("No major internal linking issues detected")

    # --------------------------------------------------
    # AFTER: default
    # --------------------------------------------------
    report["after"] = "No change required"

    # --------------------------------------------------
    # APPLY OPPORTUNITY IMPACT (targets)
    # --------------------------------------------------
    if opportunities_df is not None and not opportunities_df.empty:
        affected_targets = set(opportunities_df["target_url"])
        report.loc[
            report["url"].isin(affected_targets),
            "after"
        ] = (
            "Adding contextual internal links will strengthen topical relevance "
            "and improve problem-to-solution navigation"
        )

    # --------------------------------------------------
    # APPLY ANCHOR OPTIMIZATION IMPACT (source pages)
    # --------------------------------------------------
    if anchor_optimization_df is not None and not anchor_optimization_df.empty:
        affected_pages = set(anchor_optimization_df["page_to_edit"])
        report.loc[
            report["url"].isin(affected_pages),
            "after"
        ] = (
            "Replacing generic anchors with descriptive anchors will improve "
            "internal relevance signals"
        )

    return report[
        [
            "url",
            "priority_tier",
            "priority_score",
            "gap_status",
            "receiving_links",
            "link_equity_score",
            "before",
            "after",
        ]
    ].sort_values(
        by=["priority_tier", "priority_score"],
        ascending=[True, False],
    )


# -------------------------------------------------------------------
# Tab 2: Actionable Opportunities
# -------------------------------------------------------------------

def build_actionable_opportunities(
    opportunities: pd.DataFrame,
    audited_df: pd.DataFrame,
) -> pd.DataFrame:

    if opportunities is None or opportunities.empty:
        return pd.DataFrame()

    opp_df = opportunities.copy()

    priority_map = (
        audited_df[["url", "priority_tier"]]
        .set_index("url")["priority_tier"]
        .to_dict()
    )

    opp_df["target_priority"] = opp_df["target_url"].map(priority_map)

    opp_df = opp_df[
        [
            "target_url",
            "target_priority",
            "source_url",
            "suggested_anchor",
            "source_non_branded_traffic",
        ]
    ]

    return opp_df.sort_values(
        by=["target_priority", "source_non_branded_traffic"],
        ascending=[True, False],
    )


# -------------------------------------------------------------------
# Tab 3: Anchor Text Optimization
# -------------------------------------------------------------------

def build_anchor_optimization_report(
    raw_links_list: List[Dict],
    audited_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Flags EXISTING links with bad anchor text and suggests replacement.
    """

    links_df = pd.DataFrame(raw_links_list)
    if links_df.empty:
        return pd.DataFrame()

    links_df["anchor_clean"] = links_df["anchor"].astype(str).str.lower().str.strip()
    links_df["is_bad_anchor"] = links_df["anchor_clean"].apply(is_bad_anchor)
    links_df = links_df[links_df["is_bad_anchor"]]

    best_anchor_map = {
        row["url"]: (
            row.get("best_anchor_text")
            or row.get("h1")
            or row.get("title")
            or "N/A"
        )
        for _, row in audited_df.iterrows()
        if isinstance(row.get("url"), str)
    }

    links_df["suggested_anchor"] = links_df["dest"].map(best_anchor_map).fillna("N/A")

    return links_df[
        ["source", "dest", "anchor", "suggested_anchor"]
    ].rename(
        columns={
            "source": "page_to_edit",
            "dest": "destination_page",
            "anchor": "current_junk_anchor",
        }
    )


# -------------------------------------------------------------------
# Phase 5 Entry Point (THIS WAS BROKEN)
# -------------------------------------------------------------------

def export_internal_linking_report(
    audited_df: pd.DataFrame,
    opportunities: pd.DataFrame,
    raw_links_list: List[Dict],
    output_path: Union[str, Path],
) -> None:

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # BUILD DEPENDENT TABLES FIRST
    anchor_optimization_df = build_anchor_optimization_report(
        raw_links_list,
        audited_df,
    )

    page_summary_df = build_page_summary_report(
        audited_df=audited_df,
        anchor_optimization_df=anchor_optimization_df,
        opportunities_df=opportunities,
    )

    actionable_df = build_actionable_opportunities(
        opportunities,
        audited_df,
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        page_summary_df.to_excel(
            writer,
            sheet_name="Page_Summary_Report",
            index=False,
        )

        actionable_df.to_excel(
            writer,
            sheet_name="Actionable_Opportunities",
            index=False,
        )

        anchor_optimization_df.to_excel(
            writer,
            sheet_name="Anchor_Text_Optimization",
            index=False,
        )
