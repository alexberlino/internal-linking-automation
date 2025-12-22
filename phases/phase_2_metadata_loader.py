# phases/phase_2_metadata_loader.py

from pathlib import Path
import pandas as pd
from typing import Union



REQUIRED_COLUMNS = {
    "url",
    "title",
    "h1",
    "meta_description",
    "importance",
}

VALID_IMPORTANCE = {"A", "B", "C"}


def load_page_metadata(
    path: Union[str, Path],
    encoding: str = "utf-8",
) -> pd.DataFrame:
    """
    Loads page-level metadata used for:
    - target prioritization (importance)
    - intent / keyword derivation (title, h1)

    Required columns:
    - url
    - title
    - h1
    - meta_description
    - importance (A / B / C)
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Page metadata file not found: {path}")

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

    # Clean URL
    df["url"] = df["url"].astype(str).str.strip()

    # Clean text fields
    for col in ["title", "h1", "meta_description"]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    # Normalize importance
    df["importance"] = (
        df["importance"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    invalid = set(df["importance"].unique()) - VALID_IMPORTANCE
    if invalid:
        raise ValueError(
            f"Invalid importance values found: {invalid}. "
            f"Allowed: {VALID_IMPORTANCE}"
        )

    # Optional numeric fields (safe to include)
    for col in ["search_volume", "current_traffic"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df
