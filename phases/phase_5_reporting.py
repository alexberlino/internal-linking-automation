# phases/phase_5_reporting.py

from typing import List, Dict, Union, Optional, Any
from pathlib import Path
import re
from urllib.parse import urlparse
import pandas as pd


# -------------------------------------------------------------------
# GLOBAL CONFIG (Phase 5)
# -------------------------------------------------------------------
# Scope:
# - Ignore "anchor text quality" changes.
# - Only flag EXISTING links where the anchor is a commercial term
#   but the CURRENT destination is a blog URL.
# - Brand-only anchors may map to homepage, but ONLY when the anchor
#   is basically just the brand.
# - Ignore empty anchors.
# - Ignore anchors that are purely dates (e.g. 01/01/2019).
# - Ignore anchors that look like article titles/listicles (e.g. "13 beste ...").

COMMERCIAL_ANCHOR_RULES = [
    # --------------------------------------------------
    # VERY SPECIFIC COMMERCIAL INTENTS (FIRST)
    # --------------------------------------------------
    {
        "kw": "woocommerce hosting",
        "pattern": r"\bwoocommerce\s+hosting\b",
        "target_url": "https://raidboxes.io/solutions/woocommerce-hosting/",
    },
    {
        "kw": "green wordpress hosting",
        "pattern": r"\b(green|grünes|klimafreundliches|nachhaltiges)\s+wordpress\s+hosting\b",
        "target_url": "https://raidboxes.io/platform/green-wordpress-hosting/",
    },
    {
        "kw": "high traffic wordpress hosting",
        "pattern": r"\b(high[-\s]?traffic|enterprise)\b.*\bwordpress\s+hosting\b|\bwordpress\s+hosting\b.*\b(high[-\s]?traffic|enterprise)\b",
        "target_url": "https://raidboxes.io/solutions/high-traffic-wordpress-hosting/",
    },
    {
        "kw": "managed cloud hosting",
        "pattern": r"\bmanaged\s+cloud\s+hosting\b",
        "target_url": "https://raidboxes.io/solutions/wordpress-managed-cloud-hosting/",
    },

    # --------------------------------------------------
    # PLATFORM / FEATURE COMMERCIAL PAGES
    # --------------------------------------------------
    {
        "kw": "wordpress support",
        "pattern": r"\bwordpress\s+support\b|\bfragen\s+im\s+wordpress\s+support\b",
        "target_url": "https://raidboxes.io/platform/wordpress-support/",
    },
    {
        "kw": "wordpress security",
        "pattern": r"\bwordpress\s+(security|sicherheit)\b|\bsicher(es|heit)\b.*\bwordpress\b",
        "target_url": "https://raidboxes.io/platform/wordpress-security/",
    },
    {
        "kw": "wordpress performance",
        "pattern": r"\bwordpress\s+performance\b|\bschnell(es|e)\s+wordpress\s+hosting\b",
        "target_url": "https://raidboxes.io/platform/wordpress-performance/",
    },
    {
        "kw": "wordpress management",
        "pattern": r"\bwordpress\s+management\b|\bwebsites?\s+verwalten\b",
        "target_url": "https://raidboxes.io/platform/wordpress-management/",
    },

    # --------------------------------------------------
    # MIGRATION / PRICING / TOOLS
    # --------------------------------------------------
    {
        "kw": "wordpress migration",
        "pattern": r"\bwordpress\s+migration\b|\bwordpress\s+umzug\b|\bumzugsservice\b",
        "target_url": "https://raidboxes.io/free-wordpress-migration/",
    },
    {
        "kw": "wordpress hosting preise",
        "pattern": r"\bwordpress\s+hosting\b.*\b(preise|pricing|tarife|kosten)\b|\b(preise|pricing|tarife|kosten)\b.*\bwordpress\s+hosting\b",
        "target_url": "https://raidboxes.io/wordpress-hosting-pricing/",
    },
    {
        "kw": "wordpress speed test",
        "pattern": r"\bwordpress\s+speed\s+test\b|\bwie\s+schnell\s+lädt\b.*\bwordpress\b",
        "target_url": "https://raidboxes.io/wordpress-speed-test/",
    },
    {
        "kw": "performance test",
        "pattern": r"\bperformance[-\s]*test\b|\blangsame\s+website\b|\bslow\s+website\b",
        "target_url": "https://raidboxes.io/performance-test/",
    },

    # --------------------------------------------------
    # CUSTOMER SEGMENTS
    # --------------------------------------------------
    {
        "kw": "wordpress hosting für agenturen",
        "pattern": r"\bwordpress\s+hosting\b.*\b(agenturen|freelancer)\b|\b(agenturen|freelancer)\b.*\bwordpress\s+hosting\b",
        "target_url": "https://raidboxes.io/customers/website-creators/",
    },
    {
        "kw": "wordpress hosting für unternehmen",
        "pattern": r"\bwordpress\s+hosting\b.*\b(unternehmen|shops)\b|\b(unternehmen|shops)\b.*\bwordpress\s+hosting\b",
        "target_url": "https://raidboxes.io/customers/website-owners/",
    },

    # --------------------------------------------------
    # DOMAINS / EMAIL / PARTNER
    # --------------------------------------------------
    {
        "kw": "domains",
        "pattern": r"\bdomain(s)?\b|\bdomain\s+kaufen\b",
        "target_url": "https://raidboxes.io/domains/",
    },
    {
        "kw": "email hosting",
        "pattern": r"\b(e-?mail|email)\s+hosting\b",
        "target_url": "https://raidboxes.io/email-hosting/",
    },
    {
        "kw": "affiliate programm",
        "pattern": r"\baffiliate\s+(programm|program)\b",
        "target_url": "https://raidboxes.io/affiliate/",
    },

    # --------------------------------------------------
    # COMPETITOR ALTERNATIVES
    # --------------------------------------------------
    {
        "kw": "ionos alternative",
        "pattern": r"\bionos\s+alternative\b",
        "target_url": "https://raidboxes.io/ionos-alternative/",
    },
    {
        "kw": "strato alternative",
        "pattern": r"\bstrato\s+alternative\b",
        "target_url": "https://raidboxes.io/strato-alternative/",
    },

    # --------------------------------------------------
    # GENERIC COMMERCIAL (LAST BEFORE BRAND)
    # --------------------------------------------------
    {
        "kw": "managed wordpress hosting",
        "pattern": r"\bmanaged\s+wordpress\s+hosting\b",
        "target_url": "https://raidboxes.io/solutions/managed-wordpress-hosting/",
    },
    {
        "kw": "wordpress hosting",
        "pattern": r"\bwordpress\s+hosting\b",
        "target_url": "https://raidboxes.io/solutions/managed-wordpress-hosting/",
    },

    # --------------------------------------------------
    # BRAND ONLY (ABSOLUTELY LAST)
    # --------------------------------------------------
    {
        "kw": "brand",
        "pattern": r"^\s*raidboxes(?:®|™)?(?:\.io)?\s*$",
        "target_url": "https://raidboxes.io/",
    },
]


_DATE_ONLY_PATTERNS = [
    r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$",  # 01/01/2019, 01.01.2019
    r"^\d{4}-\d{2}-\d{2}$",               # 2019-01-01
    r"^\d{4}$",                           # 2019
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
    Exclude anchors that look like editorial headlines/listicles, e.g.:
    - "13 beste WordPress Hosting Anbieter ..."
    - "10 Tipps für ..."
    - "7 Gründe warum ..."
    """
    if not isinstance(anchor, str):
        return False

    a = anchor.strip()
    if not a:
        return False

    a_lc = a.lower()

    # Starts with a number + classic listicle words
    if re.match(
        r"^\s*\d{1,3}\s+(best|beste|top|tipps|tips|gründe|reasons|maßnahmen|measures|steps|schritte)\b",
        a_lc,
    ):
        return True

    # Headline-ish keywords + long anchor (likely title)
    if re.search(r"\b(vergleich|test|guide|anleitung|tutorial|checkliste|trends|liste|ranking)\b", a_lc):
        if len(a) >= 35:
            return True

    # Very long anchors are almost always titles/CTA lines
    if len(a) >= 90:
        return True

    return False


def norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def is_blog_url(url: str) -> bool:
    if not isinstance(url, str) or not url:
        return False
    path = urlparse(url).path.lower()
    return (
        path == "/blog" or path.startswith("/blog/")
        or path == "/en/blog" or path.startswith("/en/blog/")
    )


def source_is_en(url: str) -> bool:
    if not isinstance(url, str) or not url:
        return False
    path = urlparse(url).path.lower()
    return path.startswith("/en/") or path == "/en"


def align_destination_language(target_url: str, source_url: str) -> str:
    """
    Ensure suggested destination matches the language bucket of the SOURCE.

    Raidboxes setup assumed:
    - English pages live under /en/...
    - German/default pages are root (no /de/ folder).
    """
    if not isinstance(target_url, str) or not target_url:
        return target_url

    t = urlparse(target_url)
    s_is_en = source_is_en(source_url)

    path = t.path or ""
    if s_is_en:
        if not path.lower().startswith("/en/") and path.lower() != "/en":
            path = "/en" + (path if path.startswith("/") else "/" + path)
    else:
        if path.lower().startswith("/en/"):
            path = path[3:]  # remove leading '/en'
            if not path.startswith("/"):
                path = "/" + path
        elif path.lower() == "/en":
            path = "/"

    rebuilt = t._replace(path=path, query="", fragment="")
    return rebuilt.geturl().rstrip("/")


def normalize_url_no_query(url: str) -> str:
    if not isinstance(url, str):
        return ""
    p = urlparse(url)
    return p._replace(query="", fragment="").geturl().rstrip("/")


def clean_anchor_for_matching(anchor: str) -> str:
    a = norm(anchor)
    a = re.sub(r"^(zum|zur|zu|to|for|über|about)\s+", "", a)
    return a


def is_strong_match(anchor: str, keyword: str) -> bool:
    a = clean_anchor_for_matching(anchor)
    k = norm(keyword)
    if not a or not k:
        return False
    if a == k:
        return True
    if a.startswith(k + " ") or a.endswith(" " + k):
        return True
    if k in a and len(a.split()) <= 6:
        return True
    return False


# -------------------------------------------------------------------
# Tab 3: Anchor Text Optimization
# -------------------------------------------------------------------

def build_anchor_optimization_report(
    raw_links_list: List[Dict],
    audited_df: pd.DataFrame,
) -> pd.DataFrame:
    """Commercial anchor -> commercial destination (ONLY when currently linking to a blog URL).

    Output columns are designed for actionability; we DO NOT suggest changing anchor text.
    """
    links_df = pd.DataFrame(raw_links_list)
    if links_df.empty:
        return pd.DataFrame()

    # Normalize required fields
    for col in ("source", "dest", "anchor"):
        if col not in links_df.columns:
            return pd.DataFrame()

    links_df["source"] = links_df["source"].fillna("").astype(str)
    links_df["dest"] = links_df["dest"].fillna("").astype(str)
    links_df["anchor"] = links_df["anchor"].fillna("").astype(str)

    rows: List[Dict[str, Any]] = []

    for _, r in links_df.iterrows():
        src = r["source"].strip()
        dst = r["dest"].strip()
        anchor = r["anchor"].strip()

        # Ignore empty anchors
        if not anchor:
            continue

        # Ignore anchors that are purely dates (e.g. 01/01/2019)
        if is_date_only_anchor(anchor):
            continue

        # Ignore anchors that look like article titles/listicles (e.g. "13 beste ...")
        if is_article_title_like_anchor(anchor):
            continue

        # Only care about cases where CURRENT destination is a blog URL
        if not is_blog_url(dst):
            continue

        anchor_lc = norm(anchor)

        # Find best commercial rule match (specific -> general order)
        matched_rule = None
        for rule in COMMERCIAL_ANCHOR_RULES:
            if re.search(rule["pattern"], anchor_lc, flags=re.IGNORECASE):
                if is_strong_match(anchor, rule["kw"]):
                    matched_rule = rule
                    break

        if matched_rule is None:
            continue

        suggested = align_destination_language(matched_rule["target_url"], src)

        # If suggestion resolves to the same destination (after removing query/fragments), skip
        if normalize_url_no_query(dst) == normalize_url_no_query(suggested):
            continue

        rows.append({
            "page_to_edit": src,
            "destination_page": dst,
            "current_anchor": anchor,
            "suggested_anchor": anchor,  # keep anchor unchanged
            "suggested_destination": suggested,
            "rule_triggered": f"commercial_mapping: {matched_rule['kw']}",
        })

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)

    # De-dupe identical recommendations
    out = out.drop_duplicates(
        subset=["page_to_edit", "destination_page", "current_anchor", "suggested_destination"]
    )

    return out


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
    # APPLY OPPORTUNITY IMPACT (targets) - Tab 2 behavior (new links)
    # --------------------------------------------------
    if opportunities_df is not None and not opportunities_df.empty:
        affected_targets = set(opportunities_df["target_url"])
        report.loc[
            report["url"].isin(affected_targets),
            "after"
        ] = (
            "Adding new internal links from relevant blog content will strengthen internal discoverability and support priority pages"
        )

    # --------------------------------------------------
    # APPLY ANCHOR OPTIMIZATION IMPACT (source pages) - Tab 3 behavior (reroute commercial anchors)
    # --------------------------------------------------
    if anchor_optimization_df is not None and not anchor_optimization_df.empty:
        affected_pages = set(anchor_optimization_df["page_to_edit"])
        report.loc[
            report["url"].isin(affected_pages),
            "after"
        ] = (
            "Updating commercial anchors that currently link to blog pages will improve navigation from informational content to commercial pages"
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
# Phase 5 Entry Point
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
