# phases/phase_2_blog_loader.py

from pathlib import Path
import pandas as pd
from typing import Union



REQUIRED_COLUMNS = {
    "url",
    "content",
}


def load_blog_content(
    path: Union[str, Path],
    encoding: str = "utf-8",
) -> pd.DataFrame:
    """
    Loads blog article content used as link sources.

    Required columns:
    - url
    - content

    Optional columns:
    - non_branded_traffic
    - language
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Blog content file not found: {path}")

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

    # Clean core fields
    df["url"] = df["url"].astype(str).str.strip()
    df["content"] = df["content"].fillna("").astype(str)

    # Optional numeric cleanup
    if "non_branded_traffic" in df.columns:
        df["non_branded_traffic"] = (
            pd.to_numeric(df["non_branded_traffic"], errors="coerce")
            .fillna(0)
            .astype(int)
        )

    return df
