# main.py

import argparse
from pathlib import Path
import time
from urllib.parse import urlparse

# Phase 2 loaders
from phases.phase_2_blog_loader import load_blog_content
from phases.phase_2_metadata_loader import load_page_metadata
from phases.phase_2_links_loader import load_internal_links

# Phase logic
from phases.phase_3_audit import audit_internal_links
from phases.phase_4_opportunities import is_valid_source_url, run_phase_4_opportunities
from phases.phase_5_reporting import export_internal_linking_report

# Client config loader
from phases.client_config import load_client_config


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the internal linking analysis for a given client."
    )
    parser.add_argument(
        "--client",
        default="proofserve",
        help="Client config folder name under config/ (default: proofserve)",
    )
    return parser.parse_args()


def classify_source_url(url: str) -> str:
    if not isinstance(url, str) or not url:
        return "empty"

    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()

    if path in {"/blog", "/en/blog", "/learn", "/en/learn"}:
        return "blog_index"

    if "/category/" in path or "/tag/" in path or "/author/" in path:
        return "blog_listing_or_filtered"

    if (path.startswith("/learn/") or path.startswith("/blog/")) and not query:
        return "blog_article"

    return "non_blog"

def print_summary(
    *,
    client: str,
    client_config: dict,
    blog_df,
    meta_df,
    raw_links_list,
    audited_df,
    opportunities_df,
    output_path: Path,
    runtime_seconds: float,
) -> None:
    """Structured end-of-run summary."""
    def section(title: str):
        print()
        print(title)
        print("-" * 60)

    print()
    print("=" * 60)
    print(f" Internal Linking Analysis — {client}")
    print("=" * 60)
    print(f"Languages:     {', '.join(client_config['languages'])}")
    print(f"Rules loaded:  {len(client_config['rules'])}")

    section("INPUT")
    print(f"  Blog sources:     {len(blog_df):>7,}  (after URL filtering)")
    print(f"  Target pages:     {len(meta_df):>7,}")
    print(f"  Existing links:   {len(raw_links_list):>7,}")

    section("AUDIT")
    print(f"  {'Tier':<6}{'Pages':>7}{'No links':>11}{'<=2 links':>11}{'Median':>10}{'Generic anchors':>18}")
    for tier in ("A", "B", "C"):
        sub = audited_df[audited_df["priority_tier"] == tier]
        if sub.empty:
            continue
        n = len(sub)
        zero = int((sub["receiving_links"] == 0).sum())
        thin = int((sub["receiving_links"] <= 2).sum())
        median_links = int(sub["receiving_links"].median())
        generic = int(sub["has_generic_anchors"].sum())
        print(f"  {tier:<6}{n:>7,}{zero:>11,}{thin:>11,}{median_links:>10}{generic:>18,}")

    section("OPPORTUNITIES")
    if opportunities_df.empty:
        print("  (none found — try lowering SENTENCE_SIMILARITY_FLOOR)")
    else:
        n = len(opportunities_df)
        print(f"  Total found:      {n:,}")

        tier_counts = opportunities_df["target_priority_tier"].value_counts()
        tier_str = " | ".join(
            f"{t}: {int(tier_counts.get(t, 0))}" for t in ("A", "B", "C")
        )
        print(f"  By target tier:   {tier_str}")

        c = opportunities_df["confidence"]
        strong = int((c >= 0.80).sum())
        solid = int(((c >= 0.75) & (c < 0.80)).sum())
        borderline = int((c < 0.75).sum())
        print(
            f"  By confidence:    strong (>=0.80): {strong} | "
            f"solid (0.75-0.80): {solid} | "
            f"borderline (<0.75): {borderline}"
        )

        n_targets = opportunities_df["target_url"].nunique()
        n_sources = opportunities_df["source_url"].nunique()
        print(f"  Coverage:         {n_targets} distinct targets, {n_sources} distinct sources")

        print()
        print("  Top targets receiving suggestions:")
        top = opportunities_df["target_url"].value_counts().head(10)
        for url, count in top.items():
            path = urlparse(url).path or "/"
            print(f"    {count:>5}  {path}")

    section("OUTPUT")
    print(f"  Report:   {output_path}")
    print(f"  Runtime:  {runtime_seconds:.1f}s")
    print()







def main():
    start_time = time.time()
    args = parse_args()

    BASE_DIR = Path(__file__).parent

    # ---------------------------------------------------------------
    # CLIENT CONFIG
    # ---------------------------------------------------------------
    config_path = BASE_DIR / "config" / args.client
    if not config_path.exists():
        config_root = BASE_DIR / "config"
        if config_root.exists():
            available = sorted(p.name for p in config_root.iterdir() if p.is_dir())
        else:
            available = []
        raise SystemExit(
            f"Unknown client: '{args.client}'. "
            f"Available: {', '.join(available) if available else '(none configured)'}"
        )

    client_config = load_client_config(config_path)
    print(f"Analyzing {args.client} ({', '.join(client_config['languages'])})...")

    # ---------------------------------------------------------------
    # INPUT / OUTPUT FILES (per-client)
    # ---------------------------------------------------------------
    DATA_DIR = BASE_DIR / "data" / args.client
    blog_content_file = DATA_DIR / "input" / "blog_content.csv"
    page_metadata_file = DATA_DIR / "input" / "page_metadata.csv"
    internal_links_file = DATA_DIR / "input" / "internal_links.csv"
    output_report = DATA_DIR / "output" / "internal_linking_report.xlsx"

    for f in (blog_content_file, page_metadata_file, internal_links_file):
        if not f.exists():
            raise SystemExit(
                f"Missing input file: {f}\n"
                f"Expected layout: data/{args.client}/input/<file>.csv"
            )

    # ---------------------------------------------------------------
    # PHASE 2 – LOAD INPUTS
    # ---------------------------------------------------------------
    blog_df = load_blog_content(blog_content_file)
    blog_df = blog_df[blog_df["url"].apply(is_valid_source_url)].copy()

    meta_df = load_page_metadata(page_metadata_file)
    raw_links_list = load_internal_links(internal_links_file)


    # ---------------------------------------------------------------
    # PREPARE METADATA FOR AUDIT
    # ---------------------------------------------------------------
    meta_df["priority_tier"] = meta_df["importance"]
    meta_df["priority_score"] = 0  # Phase 1 intentionally skipped

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
        meta_df=audited_df,
        raw_links_list=raw_links_list,
        client_config=client_config,
    )



    # ---------------------------------------------------------------
    # PHASE 5 – EXPORT REPORT
    # ---------------------------------------------------------------
    export_internal_linking_report(
        audited_df=audited_df,
        opportunities=opportunities_df,
        raw_links_list=raw_links_list,
        output_path=output_report,
        client_config=client_config,
    )

    print_summary(
        client=args.client,
        client_config=client_config,
        blog_df=blog_df,
        meta_df=meta_df,
        raw_links_list=raw_links_list,
        audited_df=audited_df,
        opportunities_df=opportunities_df,
        output_path=output_report,
        runtime_seconds=time.time() - start_time,
    )

  

if __name__ == "__main__":
    main()