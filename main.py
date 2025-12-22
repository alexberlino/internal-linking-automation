# main.py

from pathlib import Path
import time

# Phase 2 loaders
from phases.phase_2_blog_loader import load_blog_content
from phases.phase_2_metadata_loader import load_page_metadata
from phases.phase_2_links_loader import load_internal_links

# Phase logic
from phases.phase_3_audit import audit_internal_links
from phases.phase_4_opportunities import run_phase_4_opportunities
from phases.phase_5_reporting import export_internal_linking_report


def main():
    start_time = time.time()

    BASE_DIR = Path(__file__).parent

    # ---------------------------------------------------------------
    # INPUT FILES
    # ---------------------------------------------------------------
    blog_content_file = BASE_DIR / "data/input/blog_content.csv"
    page_metadata_file = BASE_DIR / "data/input/page_metadata.csv"
    internal_links_file = BASE_DIR / "data/input/internal_links.csv"

    output_report = BASE_DIR / "data/output/internal_linking_report.xlsx"

    # ---------------------------------------------------------------
    # PHASE 2 – LOAD INPUTS
    # ---------------------------------------------------------------
    blog_df = load_blog_content(blog_content_file)
    meta_df = load_page_metadata(page_metadata_file)
    raw_links_list = load_internal_links(internal_links_file)

    # ---------------------------------------------------------------
    # PREPARE METADATA FOR AUDIT
    # ---------------------------------------------------------------
    meta_df["priority_tier"] = meta_df["importance"]
    meta_df["priority_score"] = 0  # Phase 1 intentionally skipped

    # For orphan detection (metadata = universe of pages)
    crawled_urls = set(meta_df["url"])

    # ---------------------------------------------------------------
    # PHASE 3 – AUDIT CURRENT STATE
    # ---------------------------------------------------------------
    audited_df = audit_internal_links(
        page_df=meta_df,
        crawled_urls=crawled_urls,
        raw_links_list=raw_links_list,
    )

    # ---------------------------------------------------------------
    # PHASE 4 – FIND OPPORTUNITIES
    # ---------------------------------------------------------------
    opportunities_df = run_phase_4_opportunities(
        blog_df=blog_df,
        meta_df=audited_df,          # audited_df still contains metadata
        raw_links_list=raw_links_list,
    )

    # ---------------------------------------------------------------
    # PHASE 5 – EXPORT REPORT
    # ---------------------------------------------------------------
    export_internal_linking_report(
        audited_df=audited_df,
        opportunities=opportunities_df,
        raw_links_list=raw_links_list,
        output_path=output_report,
    )

    runtime = round(time.time() - start_time, 2)
    print(f"Internal linking analysis completed in {runtime}s")


if __name__ == "__main__":
    main()
