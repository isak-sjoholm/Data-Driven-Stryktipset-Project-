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


def _normalize_pick_symbols(pick_str):
    """Extracts the set of unique outcome symbols (1, X, 2) from a pick string."""
    if pick_str is None:
        return set()
    s = str(pick_str).upper().replace(",", "").replace(" ", "")
    return {c for c in s if c in {"1", "X", "2"}}


def compute_agreement_rank(unique_rows, expert_panel, baseline_df):
    """
    Ranks candidate rows by how well they match the expert panel's picks.

    Ranking order:
    1. agreement_inclusion: for each of the 13 matches, +1 if the row's pick
       for that match was among the expert's picks, summed across all
       experts and matches (higher = better match with experts)
    2. agreement_complements: how many "extra" symbols the matching experts
       had for those matches (lower = more confident/less hedged = better)
    3. row_probability: the row's probability per baseline_df's imp1/impx/imp2
       (higher = better)

    Args:
        unique_rows: DataFrame with columns m1..m13, one row per candidate
        expert_panel: DataFrame with columns match_nr, pick, player (long
            format, one row per expert per match)
        baseline_df: DataFrame from parse_kupong() (or after Bayesian
            update) with match_nr, imp1, impx, imp2

    Returns:
        DataFrame with unique_rows' columns plus agreement_inclusion,
        agreement_complements, row_probability - sorted best-first
    """
    prob_lookup = {
        int(row["match_nr"]): {"1": row["imp1"], "X": row["impx"], "2": row["imp2"]}
        for _, row in baseline_df.iterrows()
    }

    main_scores = []
    tie_scores = []
    prob_scores = []

    for _, row in unique_rows.iterrows():
        total_inclusion = 0
        total_complements = 0
        row_prob = 1.0

        for m in range(1, 14):
            pick = str(row[f"m{m}"]).strip()

            for _, exp_row in expert_panel[expert_panel["match_nr"] == m].iterrows():
                expert_symbols = _normalize_pick_symbols(exp_row.get("pick", ""))
                if pick and pick in expert_symbols:
                    total_inclusion += 1
                    total_complements += (len(expert_symbols) - 1)

            row_prob *= prob_lookup.get(m, {}).get(pick, 1e-9)

        main_scores.append(total_inclusion)
        tie_scores.append(total_complements)
        prob_scores.append(row_prob)

    ranked = unique_rows.copy()
    ranked["agreement_inclusion"] = main_scores
    ranked["agreement_complements"] = tie_scores
    ranked["row_probability"] = prob_scores

    ranked = ranked.sort_values(
        by=["agreement_inclusion", "agreement_complements", "row_probability"],
        ascending=[False, True, False]
    ).reset_index(drop=True)

    return ranked