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

    # ------------------------------------------------
    # HOMEPAGE / BRAND
    # --------------------------------------------------
    {
        "kw": "nationwide process servers",
        "pattern": (
            r"\bnationwide\s+process\s+servers?\b"
            r"|\bnationwide\s+legal\s+service\b"
            r"|\bproof(?:serve)?\b"
        ),
        "target_url": "https://www.proofserve.com/",
    },

    # --------------------------------------------------
    # HOW IT WORKS
    # --------------------------------------------------
    {
        "kw": "how process serving works",
        "pattern": (
            r"\bhow\s+process\s+serving\s+works\b"
            r"|\bai.powered\s+process\s+serving\b"
            r"|\bautofill\s+ai\b"
            r"|\bproof\s+autofill\b"
            r"|\baddress\s+verification\b"
            r"|\bgps\s+tracking\b"
            r"|\bautomated\s+affidavits?\b"
            r"|\bserve\s+in\s+60\s+seconds\b"
            r"|\bdigital\s+service\s+of\s+process\b"
            r"|\bservice\s+of\s+process\s+platform\b"
            r"|\bprocess\s+serving\s+platform\b"
            r"|\bprocess\s+serving\s+software\b"
            r"|\bprocess\s+serving\s+app\b"
            r"|\bprocess\s+server\s+app\b"
            r"|\blegal\s+document\s+delivery\s+platform\b"
        ),
        "target_url": "https://www.proofserve.com/how-it-works",
    },

    # --------------------------------------------------
    # PRICING
    # --------------------------------------------------
    {
        "kw": "process server pricing",
        "pattern": (
            r"\bprocess\s+server\s+pricing\b"
            r"|\bprocess\s+serv(?:ing|er)\s+cost(?:s)?\b"
            r"|\bprocess\s+serv(?:ing|er)\s+rates?\b"
            r"|\bhow\s+much\s+(?:does\s+)?(?:a\s+)?process\s+server\s+cost\b"
            r"|\bhow\s+much\s+do\s+process\s+servers\s+charge\b"
            r"|\btransparent\s+(?:legal\s+)?pricing\b"
            r"|\bafordable\s+process\s+serv(?:ing|er)\b"
            r"|\bprocess\s+server\s+fees?\b"
        ),
        "target_url": "https://www.proofserve.com/pricing",
    },

    # --------------------------------------------------
    # SKIP TRACING
    # --------------------------------------------------
    {
        "kw": "skip tracing",
        "pattern": (
            r"\bskip\s+trac(?:ing|e)\b"
            r"|\bskip\s+trac(?:ing|e)\s+services?\b"
            r"|\blocate\s+(?:a\s+)?(?:person|people|individual|defendant|debtor|respondent)\b"
            r"|\bfind\s+(?:a\s+)?(?:hard.to.find\s+)?(?:person|people|individual|defendant|debtor)\b"
            r"|\bpeople\s+search\b"
            r"|\bopen.source\s+intel(?:ligence)?\b"
            r"|\bdefendant\s+location\b"
            r"|\beverify\s+(?:an?\s+)?address\b"
            r"|\baddress\s+lookup\b"
        ),
        "target_url": "https://www.proofserve.com/skip-tracing",
    },

    # ------------------------------------------------
    # FOR INDIVIDUALS / SERVE LEGAL PAPERS
    # --------------------------------------------------
    {
        "kw": "serve legal papers",
        "pattern": (
            r"\bserve\s+legal\s+(?:papers?|documents?)\b"
            r"|\bserv(?:ing|e)\s+(?:court\s+)?papers?\b"
            r"|\bserv(?:ing|e)\s+(?:legal\s+)?documents?\b"
            r"|\bserv(?:ing|e)\s+(?:a\s+)?sumons\b"
            r"|\bserv(?:ing|e)\s+(?:a\s+)?subpoena\b"
            r"|\bserv(?:ing|e)\s+(?:a\s+)?complaint\b"
            r"|\bserv(?:ing|e)\s+(?:a\s+)?defendant\b"
            r"|\bdiy\s+process\s+serv(?:ing|ice)\b"
            r"|\bself.service\s+process\s+serv(?:ing|ice)\b"
            r"|\bafordable\s+(?:legal\s+)?document\s+serv(?:ing|ice)\b"
            r"|\bserve\s+papers?\s+(?:fast|quickly|same.day)\b"
        ),
        "target_url": "https://www.proofserve.com/for-individuals",
    },

    # --------------------------------------------------
    # FOR LAW FIRMS
    # --------------------------------------------------
    {
        "kw": "process serving for law firms",
        "pattern": (
            r"\blaw\s+firm\s+process\s+serv(?:ing|ice)\b"
            r"|\bprocess\s+serv(?:ing|ice)\s+(?:for\s+)?law\s+firms?\b"
            r"|\blitigation\s+(?:law\s+firm\s+)?process\s+serv(?:ing|ice)\b"
            r"|\battorney\s+process\s+serv(?:ing|ice)\b"
            r"|\blegal\s+team\s+process\s+serv(?:ing|ice)\b"
            r"|\bparalegal\s+process\s+serv(?:ing|ice)\b"
            r"|\blaw\s+firm\s+service\s+of\s+process\b"
            r"|\bservice\s+of\s+process\s+(?:for\s+)?(?:law\s+firms?|attorneys?|paralegals?)\b"
        ),
        "target_url": "https://www.proofserve.com/for-law-firms",
    },

    # --------------------------------------------------
    # FOR COLLECTION AGENCIES
    # --------------------------------------------------
    {
        "kw": "collection agency process service",
        "pattern": (
            r"\bcollection\s+agenc(?:y|ies)\s+process\s+serv(?:ing|ice)\b"
            r"|\bprocess\s+serv(?:ing|ice)\s+(?:for\s+)?collection\s+(?:agencies|firms?|companies)\b"
            r"|\bbulk\s+(?:document\s+)?(?:upload|serv(?:ing|ice))\b"
            r"|\bbulk\s+process\s+serv(?:ing|ice)\b"
            r"|\bbulk\s+serve\b"
            r"|\bsalesforce\s+(?:process\s+serv(?:ing|ice)\s+)?integration\b"
            r"|\bfilevine\s+integration\b"
            r"|\bdebt\s+collection\s+(?:process\s+)?serv(?:ing|ice)\b"
            r"|\bhigh.volume\s+(?:process\s+)?serv(?:ing|ice)\b"
            r"|\bserve.first\s+states?\b"
            r"|\bcollections?\s+(?:law\s+firm\s+)?service\s+of\s+process\b"
        ),
        "target_url": "https://www.proofserve.com/for-collections-agencies",
    },

    # --------------------------------------------------
    # FOR GOVERNMENT
    # --------------------------------------------------
    {
        "kw": "government process service",
        "pattern": (
            r"\bgovernment\s+process\s+serv(?:ing|ice)\b"
            r"|\bprocess\s+serv(?:ing|ice)\s+(?:for\s+)?government\b"
            r"|\bgovernment\s+(?:agency\s+)?(?:document\s+)?serv(?:ing|ice)\b"
            r"|\bpublic\s+agency\s+process\s+serv(?:ing|ice)\b"
            r"|\bmunicipal\s+process\s+serv(?:ing|ice)\b"
        ),
        "target_url": "https://www.proofserve.com/for-government",
    },

    # --------------------------------------------------
    # FOR PROCESS SERVING COMPANIES
    # --------------------------------------------------
    {
        "kw": "process serving companies",
        "pattern": (
            r"\bprocess\s+serving\s+compan(?:y|ies)\b"
            r"|\boutsource\s+(?:nationwide\s+)?(?:process\s+)?serv(?:ing|ice)\b"
            r"|\bexpand\s+(?:to\s+)?all\s+50\s+states\b"
            r"|\bnationwide\s+(?:process\s+serving\s+)?network\b"
            r"|\bexpedited\s+(?:process\s+)?serv(?:ing|ice)\b"
            r"|\bsame.day\s+(?:process\s+)?serv(?:ing|ice)\b"
            r"|\bprocess\s+serving\s+network\b"
        ),
        "target_url": "https://www.proofserve.com/for-process-serving-companies",
    },

    # --------------------------------------------------
    # FOR PROPERTY MANAGEMENT
    # --------------------------------------------------
    {
        "kw": "process serving property management",
        "pattern": (
            r"\bprocess\s+serv(?:ing|ice)\s+(?:for\s+)?property\s+management\b"
            r"|\bproperty\s+management\s+process\s+serv(?:ing|ice)\b"
            r"|\btenant\s+notice(?:s)?\b"
            r"|\beviction\s+(?:notice|serv(?:ing|ice)|process)\b"
            r"|\beviction\s+papers?\b"
            r"|\boccupancy\s+check(?:s)?\b"
            r"|\bviolation\s+notice(?:s)?\b"
            r"|\blandlord\s+(?:process\s+)?serv(?:ing|ice)\b"
            r"|\bproperty\s+manager\s+(?:process\s+)?serv(?:ing|ice)\b"
            r"|\bserv(?:ing|e)\s+eviction\s+(?:papers?|notices?)\b"
        ),
        "target_url": "https://www.proofserve.com/property-management",
    },

    # --------------------------------------------------
    # FOR SERVERS / PROCESS SERVER JOBS
    # --------------------------------------------------
    {
        "kw": "process server jobs",
        "pattern": (
            r"\bprocess\s+server\s+jobs?\b"
            r"|\bprocess\s+serving\s+jobs?\b"
            r"|\bjoin\s+(?:proof(?:serve)?(?:\'s)?\s+)?(?:server\s+)?network\b"
            r"|\bearn(?:ing)?\s+(?:as\s+a\s+)?process\s+server\b"
            r"|\bget\s+paid\s+(?:as\s+a\s+)?(?:process\s+)?server\b"
            r"|\bprocess\s+server\s+(?:app|mobile\s+app)\b"
            r"|\bwork\s+as\s+a\s+process\s+server\b"
            r"|\bprocess\s+server\s+income\b"
            r"|\bprocess\s+server\s+pay\b"
            r"|\bhow\s+much\s+do\s+process\s+servers\s+make\b"
            r"|\bindependent\s+contractor\s+process\s+server\b"
            r"|\bgig\s+(?:work\s+)?process\s+serv(?:ing|er)\b"
        ),
        "target_url": "https://www.proofserve.com/for-servers",
    },

    # --------------------------------------------------
    # BECOME A PROCESS SERVER
    # --------------------------------------------------
    {
        "kw": "become a process server",
        "pattern": (
            r"\bhow\s+to\s+become\s+a\s+process\s+server\b"
            r"|\bbecoming\s+a\s+process\s+server\b"
            r"|\bprocess\s+server\s+requirements?\b"
            r"|\bprocess\s+server\s+certification\b"
            r"|\bprocess\s+server\s+license\b"
            r"|\bprocess\s+server\s+training\b"
            r"|\bprocess\s+server\s+sign\s*up\b"
            r"|\bstart(?:ing)?\s+(?:a\s+)?process\s+serving\s+(?:career|business)\b"
        ),
        "target_url": "https://www.proofserve.com/become-a-process-server",
    },

    # --------------------------------------------------
    # FOR LAW ENFORCEMENT
    # --------------------------------------------------
    {
        "kw": "process server police",
        "pattern": (
            r"\bprocess\s+server\s+(?:police|officer|sheriff|law\s+enforcement)\b"
            r"|\boff.duty\s+(?:police|officer|sheriff)\b"
            r"|\blaw\s+enforcement\s+(?:process\s+)?serv(?:ing|ice)\b"
            r"|\bpolice\s+officer\s+(?:extra\s+)?income\b"
            r"|\bsheriff\s+(?:process\s+)?serv(?:ing|ice)\b"
            r"|\bdeputy\s+(?:process\s+)?serv(?:ing|er)\b"
        ),
        "target_url": "https://www.proofserve.com/for-law-enforcement",
    },

    # --------------------------------------------------
    # SERVICE OF PROCESS (generic — how-it-works)
    # --------------------------------------------------
    {
        "kw": "service of process",
        "pattern": (
            r"\bservice\s+of\s+process\b"
            r"|\bserv(?:ing|e)\s+process\b"
            r"|\bprocess\s+serv(?:ing|er|ice|ed)\b"
            r"|\blegal\s+service\s+(?:of\s+process\s+)?platform\b"
            r"|\bdocument\s+serv(?:ing|ice)\b"
            r"|\bserve\s+legal\s+documents?\b"
            r"|\bserve\s+court\s+documents?\b"
        ),
        "target_url": "https://www.proofserve.com/how-it-works",
    },

    # --------------------------------------------------
    # BRAND ONLY
    # --------------------------------------------------
    {
        "kw": "brand",
        "pattern": r"^\s*proof(?:serve)?(?:®|™)?(?:\.com)?\s*$",
        "target_url": "https://www.proofserve.com/",
    },
]


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


def is_blog_url(url: str) -> bool:
    if not isinstance(url, str) or not url:
        return False
    path = urlparse(url).path.lower()
    return (
        path == "/blog"
        or path.startswith("/blog/")
        or path == "/en/blog"
        or path.startswith("/en/blog/")
        or path == "/learn"               # ← ProofServe
        or path.startswith("/learn/")     # ← ProofServe
        or path == "/en/learn"            # ← ProofServe EN
        or path.startswith("/en/learn/")  # ← ProofServe EN
    )


def source_is_en(url: str) -> bool:
    if not isinstance(url, str) or not url:
        return False
    path = urlparse(url).path.lower()
    return path.startswith("/en/") or path == "/en"


def align_destination_language(target_url: str, source_url: str) -> str:
    """
    Ensure suggested destination matches the language bucket of the SOURCE.

    Workist setup assumed:
    - English pages live under /en/...
    - Default/root pages are non-EN
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
            path = path[3:]
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

    if k in a and len(a.split()) <= 10:
        return True

    anchor_tokens = set(re.findall(r"[a-z0-9]+", a))
    keyword_tokens = set(re.findall(r"[a-z0-9]+", k))

    if keyword_tokens and len(keyword_tokens.intersection(anchor_tokens)) >= max(2, len(keyword_tokens) - 1):
        return True

    return False


# -------------------------------------------------------------------
# Tab 3: Anchor Text Optimization
# -------------------------------------------------------------------
_SITEWIDE_ANCHOR_TEXTS = {
    "home", "about", "contact", "careers", "pricing", "sitemap",
    "privacy policy", "terms & conditions", "terms of service",
    "blog", "press", "events", "status", "api docs", "help center",
    "associations", "request a demo", "facebook", "twitter", "linkedin",
    "previous article", "next article",
    "how it works", "overview", "service areas", "become a server",
    "for law firms", "for collections agencies", "for individuals",
    "for government", "for process serving companies", "for servers",
    "for partners", "our commitment to integrity",
}


def _is_sitewide_link(anchor: str, source_url: str, links_df: pd.DataFrame,
                     min_repeats: int = 30) -> bool:
    """A link is sitewide if its (anchor, dest) appears on >=min_repeats pages."""
    return False  # populated by the pre-pass below

def build_anchor_optimization_report(
    raw_links_list: List[Dict],
    audited_df: pd.DataFrame,
) -> pd.DataFrame:
    """..."""
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
    # Pre-filter: drop footer/nav/sitewide links before analysis.
    # A link is sitewide if either:
    #   (a) its anchor text is in the known sitewide set, OR
    #   (b) the (anchor, dest) pair repeats across >=30 source pages
    #       (the proofserve footer has ~40 links repeating on every page).
    # ------------------------------------------------------------------
    pair_counts = (
        links_df.groupby(["anchor", "dest"])["source"]
        .nunique()
        .rename("source_pages")
        .reset_index()
    )
    repeated_pairs = set(
        zip(
            pair_counts.loc[pair_counts["source_pages"] >= 30, "anchor"],
            pair_counts.loc[pair_counts["source_pages"] >= 30, "dest"],
        )
    )

    anchor_lc = links_df["anchor"].str.strip().str.lower()
    is_sitewide_anchor = anchor_lc.isin(_SITEWIDE_ANCHOR_TEXTS)
    is_repeated_pair = list(zip(links_df["anchor"], links_df["dest"]))
    is_repeated_mask = pd.Series(
        [pair in repeated_pairs for pair in is_repeated_pair],
        index=links_df.index,
    )

    before = len(links_df)
    links_df = links_df.loc[~(is_sitewide_anchor | is_repeated_mask)].copy()
    after = len(links_df)
    # Optional debug:
    # print(f"Footer/nav filter dropped {before - after} of {before} links")

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

        dst_is_blog = is_blog_url(dst)
        dst_is_home = is_homepage_url(dst)
        if not dst_is_blog and not dst_is_home:
            continue

        anchor_lc = norm(anchor)

        matched_rule = None
        for rule in COMMERCIAL_ANCHOR_RULES:
            if re.search(rule["pattern"], anchor_lc, flags=re.IGNORECASE):
                matched_rule = rule
                break

        if matched_rule is None:
            continue

        suggested = align_destination_language(matched_rule["target_url"], src)

        if normalize_url_no_query(dst) == normalize_url_no_query(suggested):
            continue

        rows.append({
            "page_to_edit": src,
            "destination_page": dst,
            "current_anchor": anchor,
            "suggested_anchor": anchor,
            "suggested_destination": suggested,
            "rule_triggered": f"commercial_mapping: {matched_rule['kw']}",
        })

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)

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
    report = audited_df[
        audited_df["priority_tier"].isin(["A", "B"])
    ].copy()

    report["before"] = report["gap_status"].map({
        "Medium: Poor Anchors": "Uses generic or non-descriptive anchor text",
        "High: Under-Linked": "Receives insufficient internal links",
    }).fillna("No major internal linking issues detected")

    report["after"] = "No change required"
    if opportunities_df is not None and not opportunities_df.empty:
        if "target_url" in opportunities_df.columns:
            affected_targets = set(opportunities_df["target_url"])
            report.loc[
                report["url"].isin(affected_targets),
                "after"
            ] = (
                "Adding new internal links from relevant blog content will strengthen internal discoverability and support priority pages"
            )

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

    if opportunities is None or opportunities.empty or "target_url" not in opportunities.columns:
        return pd.DataFrame()

    opp_df = opportunities.copy()

    priority_map = {
        str(u).strip().rstrip("/"): t
        for u, t in zip(audited_df["url"], audited_df["priority_tier"])
    }

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