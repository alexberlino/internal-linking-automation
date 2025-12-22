# phases/phase_2_links_loader.py

from pathlib import Path
import pandas as pd
from typing import Union



REQUIRED_COLUMNS = {
    "source_url",
    "target_url",
    "anchor",
}


def load_internal_links(
    path: Union[str, Path],
    encoding: str = "utf-8",
) -> list[dict]:
    """
    Loads existing internal links.

    Required columns:
    - source_url
    - target_url
    - anchor

    Returns:
    - raw_links_list: List[Dict] with keys: source, dest, anchor
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Internal links file not found: {path}")

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, encoding=encoding)
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        raise ValueError("Unsupported file format (use CSV or Excel).")

    # Normalize column names
    df.columns = [c.strip().lower() for c in df.columns]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Clean fields
    df["source_url"] = df["source_url"].astype(str).str.strip()
    df["target_url"] = df["target_url"].astype(str).str.strip()
    df["anchor"] = df["anchor"].fillna("").astype(str).str.strip()

    # Convert to expected structure
    raw_links_list = [
        {
            "source": row["source_url"],
            "dest": row["target_url"],
            "anchor": row["anchor"],
        }
        for _, row in df.iterrows()
    ]

    return raw_links_list
