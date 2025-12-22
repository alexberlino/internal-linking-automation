# phases/phase_5_reporting.py

from typing import List, Dict, Union
from pathlib import Path
import pandas as pd


# -------------------------------------------------------------------
# Tab 1: Page Summary Report
# -------------------------------------------------------------------

def build_page_summary_report(audited_df: pd.DataFrame) -> pd.DataFrame:
    """
    High-level overview of page status, sorted by priority.
    """

    columns = [
        "url",
        "priority_tier",
        "priority_score",
        "gap_status",
        "receiving_links",
        "link_equity_score",
    ]

    report = audited_df.copy()
    report = report[columns].sort_values(
        by=["priority_tier", "priority_score"],
        ascending=[True, False],
    )

    return report


# -------------------------------------------------------------------
# Tab 2: Actionable Opportunities
# -------------------------------------------------------------------

def build_actionable_opportunities(
    opportunities: pd.DataFrame,
    audited_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Builds the main 'to-do list' of internal links to create.
    """

    if opportunities is None or opportunities.empty:
        return pd.DataFrame()

    opp_df = opportunities.copy()

    # Map target priority from audited_df
    priority_map = (
        audited_df[["url", "priority_tier"]]
        .set_index("url")["priority_tier"]
        .to_dict()
    )

    opp_df["target_priority"] = opp_df["target_url"].map(priority_map)

    # Normalise / rename columns for reporting
    opp_df = opp_df.rename(
        columns={
            "suggested_anchor": "suggested_anchor",
            "source_traffic": "source_non_branded_traffic",
        }
    )

    # Order columns explicitly (only columns we KNOW exist)
    opp_df = opp_df[
        [
            "target_url",
            "target_priority",
            "source_url",
            "suggested_anchor",
            "source_non_branded_traffic",
        ]
    ]

    # Sort: most important targets first, then strongest sources
    opp_df = opp_df.sort_values(
        by=["target_priority", "source_non_branded_traffic"],
        ascending=[True, False],
    )

    return opp_df


# -------------------------------------------------------------------
# Tab 3: Anchor Text Optimization
# -------------------------------------------------------------------

def build_anchor_optimization_report(
    raw_links_list: List[Dict],
    audited_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Identifies existing links with generic anchors pointing to important pages.
    """

    GENERIC_ANCHORS = {
        "click here",
        "read more",
        "learn more",
        "more",
        "here",
    }

    links_df = pd.DataFrame(raw_links_list)

    if links_df.empty:
        return pd.DataFrame()

    links_df["anchor_clean"] = links_df["anchor"].str.lower().str.strip()

    # Only generic anchors
    links_df = links_df[
        links_df["anchor_clean"].isin(GENERIC_ANCHORS)
    ]

    # Only important targets
    important_urls = set(
        audited_df[
            audited_df["priority_tier"].isin(["A", "B"])
        ]["url"]
    )

    links_df = links_df[
        links_df["dest"].isin(important_urls)
    ]

    # Suggest better anchor (fallback: URL slug)
    def suggest_anchor(url: str) -> str:
        return url.rstrip("/").split("/")[-1].replace("-", " ")

    links_df["suggested_anchor"] = links_df["dest"].apply(suggest_anchor)

    return links_df[
        [
            "source",
            "dest",
            "anchor",
            "suggested_anchor",
        ]
    ].rename(
        columns={
            "source": "page_to_edit",
            "dest": "destination_page",
            "anchor": "current_junk_anchor",
        }
    )


# -------------------------------------------------------------------
# Phase 5 Entry Point
# -------------------------------------------------------------------

def export_internal_linking_report(
    audited_df: pd.DataFrame,
    opportunities: pd.DataFrame,
    raw_links_list: List[Dict],
    output_path: Union[str, Path],
) -> None:
    """
    Writes the final multi-tab Excel report.
    """

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:

        build_page_summary_report(audited_df).to_excel(
            writer,
            sheet_name="Page_Summary_Report",
            index=False,
        )

        build_actionable_opportunities(
            opportunities,
            audited_df,
        ).to_excel(
            writer,
            sheet_name="Actionable_Opportunities",
            index=False,
        )

        build_anchor_optimization_report(
            raw_links_list,
            audited_df,
        ).to_excel(
            writer,
            sheet_name="Anchor_Text_Optimization",
            index=False,
        )
