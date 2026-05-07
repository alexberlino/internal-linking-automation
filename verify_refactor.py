# verify_refactor.py
"""
Verifies the Phase 5 refactor produces equivalent output to the original.

Runs both versions of build_anchor_optimization_report on the same inputs
and reports any differences. Run this BEFORE committing the refactor:

    python verify_refactor.py --client proofserve

Expected outcome for ProofServe:
  - "Only in OLD" should be 0
  - "Only in NEW" may be > 0 ONLY for rows where destination_page is the
    homepage (those were unreachable in the old code due to the
    undefined is_homepage_url reference). All other deltas indicate
    a regression and need investigation.
"""

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Dict, List

import pandas as pd

from phases.client_config import load_client_config
from phases.phase_2_blog_loader import load_blog_content
from phases.phase_2_links_loader import load_internal_links
from phases.phase_2_metadata_loader import load_page_metadata
from phases.phase_3_audit import audit_internal_links
from phases.phase_5_reporting import build_anchor_optimization_report as new_build


# ---------------------------------------------------------------------
# OLD implementation, copied verbatim from your v2 phase_5_reporting.py
# (with the undefined is_homepage_url replaced by a stub that returns
# False, matching the only path through which the old code could have
# run without crashing).
# ---------------------------------------------------------------------

OLD_COMMERCIAL_ANCHOR_RULES = [
    {"kw": "nationwide process servers",
     "pattern": r"\bnationwide\s+process\s+servers?\b|\bnationwide\s+legal\s+service\b|\bproof(?:serve)?\b",
     "target_url": "https://www.proofserve.com/"},
    {"kw": "how process serving works",
     "pattern": r"\bhow\s+process\s+serving\s+works\b|\bai.powered\s+process\s+serving\b|\bautofill\s+ai\b|\bproof\s+autofill\b|\baddress\s+verification\b|\bgps\s+tracking\b|\bautomated\s+affidavits?\b|\bserve\s+in\s+60\s+seconds\b|\bdigital\s+service\s+of\s+process\b|\bservice\s+of\s+process\s+platform\b|\bprocess\s+serving\s+platform\b|\bprocess\s+serving\s+software\b|\bprocess\s+serving\s+app\b|\bprocess\s+server\s+app\b|\blegal\s+document\s+delivery\s+platform\b",
     "target_url": "https://www.proofserve.com/how-it-works"},
    {"kw": "process server pricing",
     "pattern": r"\bprocess\s+server\s+pricing\b|\bprocess\s+serv(?:ing|er)\s+cost(?:s)?\b|\bprocess\s+serv(?:ing|er)\s+rates?\b|\bhow\s+much\s+(?:does\s+)?(?:a\s+)?process\s+server\s+cost\b|\bhow\s+much\s+do\s+process\s+servers\s+charge\b|\btransparent\s+(?:legal\s+)?pricing\b|\bafordable\s+process\s+serv(?:ing|er)\b|\bprocess\s+server\s+fees?\b",
     "target_url": "https://www.proofserve.com/pricing"},
    {"kw": "skip tracing",
     "pattern": r"\bskip\s+trac(?:ing|e)\b|\bskip\s+trac(?:ing|e)\s+services?\b|\blocate\s+(?:a\s+)?(?:person|people|individual|defendant|debtor|respondent)\b|\bfind\s+(?:a\s+)?(?:hard.to.find\s+)?(?:person|people|individual|defendant|debtor)\b|\bpeople\s+search\b|\bopen.source\s+intel(?:ligence)?\b|\bdefendant\s+location\b|\beverify\s+(?:an?\s+)?address\b|\baddress\s+lookup\b",
     "target_url": "https://www.proofserve.com/skip-tracing"},
    {"kw": "serve legal papers",
     "pattern": r"\bserve\s+legal\s+(?:papers?|documents?)\b|\bserv(?:ing|e)\s+(?:court\s+)?papers?\b|\bserv(?:ing|e)\s+(?:legal\s+)?documents?\b|\bserv(?:ing|e)\s+(?:a\s+)?sumons\b|\bserv(?:ing|e)\s+(?:a\s+)?subpoena\b|\bserv(?:ing|e)\s+(?:a\s+)?complaint\b|\bserv(?:ing|e)\s+(?:a\s+)?defendant\b|\bdiy\s+process\s+serv(?:ing|ice)\b|\bself.service\s+process\s+serv(?:ing|ice)\b|\bafordable\s+(?:legal\s+)?document\s+serv(?:ing|ice)\b|\bserve\s+papers?\s+(?:fast|quickly|same.day)\b",
     "target_url": "https://www.proofserve.com/for-individuals"},
    {"kw": "process serving for law firms",
     "pattern": r"\blaw\s+firm\s+process\s+serv(?:ing|ice)\b|\bprocess\s+serv(?:ing|ice)\s+(?:for\s+)?law\s+firms?\b|\blitigation\s+(?:law\s+firm\s+)?process\s+serv(?:ing|ice)\b|\battorney\s+process\s+serv(?:ing|ice)\b|\blegal\s+team\s+process\s+serv(?:ing|ice)\b|\bparalegal\s+process\s+serv(?:ing|ice)\b|\blaw\s+firm\s+service\s+of\s+process\b|\bservice\s+of\s+process\s+(?:for\s+)?(?:law\s+firms?|attorneys?|paralegals?)\b",
     "target_url": "https://www.proofserve.com/for-law-firms"},
    {"kw": "collection agency process service",
     "pattern": r"\bcollection\s+agenc(?:y|ies)\s+process\s+serv(?:ing|ice)\b|\bprocess\s+serv(?:ing|ice)\s+(?:for\s+)?collection\s+(?:agencies|firms?|companies)\b|\bbulk\s+(?:document\s+)?(?:upload|serv(?:ing|ice))\b|\bbulk\s+process\s+serv(?:ing|ice)\b|\bbulk\s+serve\b|\bsalesforce\s+(?:process\s+serv(?:ing|ice)\s+)?integration\b|\bfilevine\s+integration\b|\bdebt\s+collection\s+(?:process\s+)?serv(?:ing|ice)\b|\bhigh.volume\s+(?:process\s+)?serv(?:ing|ice)\b|\bserve.first\s+states?\b|\bcollections?\s+(?:law\s+firm\s+)?service\s+of\s+process\b",
     "target_url": "https://www.proofserve.com/for-collections-agencies"},
    {"kw": "government process service",
     "pattern": r"\bgovernment\s+process\s+serv(?:ing|ice)\b|\bprocess\s+serv(?:ing|ice)\s+(?:for\s+)?government\b|\bgovernment\s+(?:agency\s+)?(?:document\s+)?serv(?:ing|ice)\b|\bpublic\s+agency\s+process\s+serv(?:ing|ice)\b|\bmunicipal\s+process\s+serv(?:ing|ice)\b",
     "target_url": "https://www.proofserve.com/for-government"},
    {"kw": "process serving companies",
     "pattern": r"\bprocess\s+serving\s+compan(?:y|ies)\b|\boutsource\s+(?:nationwide\s+)?(?:process\s+)?serv(?:ing|ice)\b|\bexpand\s+(?:to\s+)?all\s+50\s+states\b|\bnationwide\s+(?:process\s+serving\s+)?network\b|\bexpedited\s+(?:process\s+)?serv(?:ing|ice)\b|\bsame.day\s+(?:process\s+)?serv(?:ing|ice)\b|\bprocess\s+serving\s+network\b",
     "target_url": "https://www.proofserve.com/for-process-serving-companies"},
    {"kw": "process serving property management",
     "pattern": r"\bprocess\s+serv(?:ing|ice)\s+(?:for\s+)?property\s+management\b|\bproperty\s+management\s+process\s+serv(?:ing|ice)\b|\btenant\s+notice(?:s)?\b|\beviction\s+(?:notice|serv(?:ing|ice)|process)\b|\beviction\s+papers?\b|\boccupancy\s+check(?:s)?\b|\bviolation\s+notice(?:s)?\b|\blandlord\s+(?:process\s+)?serv(?:ing|ice)\b|\bproperty\s+manager\s+(?:process\s+)?serv(?:ing|ice)\b|\bserv(?:ing|e)\s+eviction\s+(?:papers?|notices?)\b",
     "target_url": "https://www.proofserve.com/property-management"},
    {"kw": "process server jobs",
     "pattern": r"\bprocess\s+server\s+jobs?\b|\bprocess\s+serving\s+jobs?\b|\bjoin\s+(?:proof(?:serve)?(?:\'s)?\s+)?(?:server\s+)?network\b|\bearn(?:ing)?\s+(?:as\s+a\s+)?process\s+server\b|\bget\s+paid\s+(?:as\s+a\s+)?(?:process\s+)?server\b|\bprocess\s+server\s+(?:app|mobile\s+app)\b|\bwork\s+as\s+a\s+process\s+server\b|\bprocess\s+server\s+income\b|\bprocess\s+server\s+pay\b|\bhow\s+much\s+do\s+process\s+servers\s+make\b|\bindependent\s+contractor\s+process\s+server\b|\bgig\s+(?:work\s+)?process\s+serv(?:ing|er)\b",
     "target_url": "https://www.proofserve.com/for-servers"},
    {"kw": "become a process server",
     "pattern": r"\bhow\s+to\s+become\s+a\s+process\s+server\b|\bbecoming\s+a\s+process\s+server\b|\bprocess\s+server\s+requirements?\b|\bprocess\s+server\s+certification\b|\bprocess\s+server\s+license\b|\bprocess\s+server\s+training\b|\bprocess\s+server\s+sign\s*up\b|\bstart(?:ing)?\s+(?:a\s+)?process\s+serving\s+(?:career|business)\b",
     "target_url": "https://www.proofserve.com/become-a-process-server"},
    {"kw": "process server police",
     "pattern": r"\bprocess\s+server\s+(?:police|officer|sheriff|law\s+enforcement)\b|\boff.duty\s+(?:police|officer|sheriff)\b|\blaw\s+enforcement\s+(?:process\s+)?serv(?:ing|ice)\b|\bpolice\s+officer\s+(?:extra\s+)?income\b|\bsheriff\s+(?:process\s+)?serv(?:ing|ice)\b|\bdeputy\s+(?:process\s+)?serv(?:ing|er)\b",
     "target_url": "https://www.proofserve.com/for-law-enforcement"},
    {"kw": "service of process",
     "pattern": r"\bservice\s+of\s+process\b|\bserv(?:ing|e)\s+process\b|\bprocess\s+serv(?:ing|er|ice|ed)\b|\blegal\s+service\s+(?:of\s+process\s+)?platform\b|\bdocument\s+serv(?:ing|ice)\b|\bserve\s+legal\s+documents?\b|\bserve\s+court\s+documents?\b",
     "target_url": "https://www.proofserve.com/how-it-works"},
    {"kw": "brand",
     "pattern": r"^\s*proof(?:serve)?(?:®|™)?(?:\.com)?\s*$",
     "target_url": "https://www.proofserve.com/"},
]

OLD_SITEWIDE = {
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

_DATE_PATTERNS = [
    r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$",
    r"^\d{4}-\d{2}-\d{2}$",
    r"^\d{4}$",
]


def _old_is_date(a: str) -> bool:
    if not isinstance(a, str) or not a.strip():
        return False
    return any(re.match(p, a.strip()) for p in _DATE_PATTERNS)


def _old_is_listicle(a: str) -> bool:
    if not isinstance(a, str) or not a.strip():
        return False
    a_lc = a.strip().lower()
    if re.match(r"^\s*\d{1,3}\s+(best|beste|top|tipps|tips|gründe|reasons|maßnahmen|measures|steps|schritte)\b", a_lc):
        return True
    if re.search(r"\b(vergleich|test|guide|anleitung|tutorial|checkliste|trends|liste|ranking)\b", a_lc):
        if len(a.strip()) >= 35:
            return True
    if len(a.strip()) >= 90:
        return True
    return False


def _old_is_blog_url(url: str) -> bool:
    """Matches v2: /blog, /en/blog, /learn (NOTE: v2 dropped /en/learn)."""
    if not isinstance(url, str) or not url:
        return False
    p = urlparse(url).path.lower()
    return p in {"/blog", "/en/blog", "/learn"} or p.startswith(("/blog/", "/en/blog/", "/learn/"))


def _old_norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _old_norm_url(u: str) -> str:
    if not isinstance(u, str):
        return ""
    p = urlparse(u)
    return p._replace(query="", fragment="").geturl().rstrip("/")


def old_build_anchor_optimization_report(
    raw_links_list: List[Dict],
    audited_df: pd.DataFrame,
) -> pd.DataFrame:
    """Reproduces the v2 build_anchor_optimization_report behavior."""
    links_df = pd.DataFrame(raw_links_list)
    if links_df.empty:
        return pd.DataFrame()

    for col in ("source", "dest", "anchor"):
        if col not in links_df.columns:
            return pd.DataFrame()

    links_df["source"] = links_df["source"].fillna("").astype(str)
    links_df["dest"] = links_df["dest"].fillna("").astype(str)
    links_df["anchor"] = links_df["anchor"].fillna("").astype(str)

    # Sitewide pre-filter (same as v2)
    pair_counts = (
        links_df.groupby(["anchor", "dest"])["source"].nunique()
        .rename("source_pages").reset_index()
    )
    repeated_pairs = set(zip(
        pair_counts.loc[pair_counts["source_pages"] >= 30, "anchor"],
        pair_counts.loc[pair_counts["source_pages"] >= 30, "dest"],
    ))
    anchor_lc_series = links_df["anchor"].str.strip().str.lower()
    is_sitewide = anchor_lc_series.isin(OLD_SITEWIDE)
    is_repeated = pd.Series(
        [(a, d) in repeated_pairs for a, d in zip(links_df["anchor"], links_df["dest"])],
        index=links_df.index,
    )
    links_df = links_df.loc[~(is_sitewide | is_repeated)].copy()

    rows: List[Dict[str, Any]] = []

    for _, r in links_df.iterrows():
        src, dst, anchor = r["source"].strip(), r["dest"].strip(), r["anchor"].strip()
        if not anchor or _old_is_date(anchor) or _old_is_listicle(anchor):
            continue
        # v2 only checks blog (homepage check was undefined → effectively False)
        if not _old_is_blog_url(dst):
            continue

        anchor_lc = _old_norm(anchor)
        matched = None
        for rule in OLD_COMMERCIAL_ANCHOR_RULES:
            if re.search(rule["pattern"], anchor_lc, flags=re.IGNORECASE):
                matched = rule
                break
        if matched is None:
            continue

        suggested = matched["target_url"]
        if _old_norm_url(dst) == _old_norm_url(suggested):
            continue

        rows.append({
            "page_to_edit": src,
            "destination_page": dst,
            "current_anchor": anchor,
            "suggested_anchor": anchor,
            "suggested_destination": suggested,
            "rule_triggered": f"commercial_mapping: {matched['kw']}",
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates(
        subset=["page_to_edit", "destination_page", "current_anchor", "suggested_destination"]
    )


# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------

def run_diff(client: str) -> int:
    BASE = Path(__file__).parent
    DATA = BASE / "data" / client / "input"

    # Load shared inputs
    meta_df = load_page_metadata(DATA / "page_metadata.csv")
    raw_links_list = load_internal_links(DATA / "internal_links.csv")

    # Build a minimal audited_df (anchor optimizer only needs raw_links_list +
    # the audited_df for column shape; it doesn't read priority_tier here)
    meta_df["priority_tier"] = meta_df["importance"]
    meta_df["priority_score"] = 0
    audited_df = audit_internal_links(
        page_df=meta_df,
        crawled_urls=set(meta_df["url"]),
        raw_links_list=raw_links_list,
    )

    # Run OLD
    print("Running OLD anchor optimization...")
    old_df = old_build_anchor_optimization_report(raw_links_list, audited_df)
    print(f"  OLD rows: {len(old_df)}")

    # Run NEW
    print("Running NEW anchor optimization...")
    cfg = load_client_config(BASE / "config" / client)
    new_df = new_build(raw_links_list, audited_df, cfg)
    print(f"  NEW rows: {len(new_df)}")

    # Compute diff on the natural key
    key = ["page_to_edit", "destination_page", "current_anchor", "suggested_destination"]

    if old_df.empty and new_df.empty:
        print("\nBoth outputs are empty. Nothing to compare.")
        return 0

    if old_df.empty:
        old_keys = set()
    else:
        old_keys = set(map(tuple, old_df[key].astype(str).values))

    if new_df.empty:
        new_keys = set()
    else:
        new_keys = set(map(tuple, new_df[key].astype(str).values))

    only_old = old_keys - new_keys
    only_new = new_keys - old_keys

    print("\n" + "=" * 70)
    print(f"Only in OLD: {len(only_old)}    (regressions — should be 0)")
    print(f"Only in NEW: {len(only_new)}    (additions — homepage rows OK)")
    print("=" * 70)

    if only_old:
        print("\n[!] REGRESSION — rows present in OLD but missing from NEW:")
        for row in list(only_old)[:20]:
            print(f"  {row}")
        if len(only_old) > 20:
            print(f"  ... and {len(only_old) - 20} more")

    if only_new:
        # Categorize: homepage destinations are expected; everything else is suspect
        homepage_paths = {"", "/"}
        homepage_rows = [
            r for r in only_new
            if urlparse(r[1]).path.rstrip("/").lower() in homepage_paths
        ]
        other_rows = [r for r in only_new if r not in set(homepage_rows)]

        print(f"\n[+] NEW additions:")
        print(f"    {len(homepage_rows)} link(s) point to homepage (expected — was unreachable in OLD)")
        print(f"    {len(other_rows)} link(s) of other type (review needed)")

        if other_rows:
            print("\n    Unexpected NEW additions (first 20):")
            for row in other_rows[:20]:
                print(f"      {row}")

    print()
    return len(only_old) + len([r for r in only_new if urlparse(r[1]).path.rstrip("/").lower() not in {"", "/"}])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", default="proofserve")
    args = parser.parse_args()

    unexpected = run_diff(args.client)
    if unexpected == 0:
        print("✅ Refactor produces equivalent output (expected differences only).")
    else:
        print(f"❌ {unexpected} unexpected difference(s). Review above before committing.")


if __name__ == "__main__":
    main()