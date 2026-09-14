"""
automated_runner.py
--------------------
Core agreement-ranking logic: expands each expert's picks into individual
outcome rows, computes how far a row deviates from historical norms, scores
"fill-up" rows that have no direct expert support, and ranks candidate rows
by how well they match the expert panel's picks.
"""

import pandas as pd
import itertools


def expand_expert_to_rows(df_expert):
    """
    Expands one expert's picks (one row per match, comma-separated symbols
    like "1,X") into every possible single-row combination.

    Args:
        df_expert: DataFrame with columns match_nr, pick, player - one row
            per match for a single expert, sorted by match_nr

    Returns:
        DataFrame with columns m1..m13 (one row per possible combination)
        plus a 'player' column
    """
    all_choices = []
    for _, row in df_expert.iterrows():
        pick_str = str(row["pick"]) if pd.notna(row["pick"]) else ""
        picks = [p.strip().upper() for p in pick_str.replace("x", "X").split(",") if p.strip()]
        if not picks:
            picks = [""]
        all_choices.append(picks)

    combinations = list(itertools.product(*all_choices))
    df_rows = pd.DataFrame(combinations, columns=[f"m{i}" for i in range(1, len(all_choices) + 1)])
    df_rows["player"] = df_expert["player"].iloc[0]
    return df_rows