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



def compute_expected_payout(row, baseline_df):
    """
    Computes expected 13-rätt payout for one row, using:
        payout = (0.65 * 0.4) / (product of Svenska Folket % across all
                  13 matches, as fractions)
    The turnover assumption cancels out algebraically, so it's not a
    parameter here - see project notes.

    Args:
        row: a single row with columns m1..m13
        baseline_df: DataFrame from parse_kupong() with match_nr, sv1, svx, sv2

    Returns:
        float: expected payout in kr
    """
    sv_lookup = {
        int(r["match_nr"]): {"1": r["sv1"], "X": r["svx"], "2": r["sv2"]}
        for _, r in baseline_df.iterrows()
    }

    sv_product = 1.0
    for m in range(1, 14):
        pick = str(row[f"m{m}"]).strip()
        sv_pct = sv_lookup.get(m, {}).get(pick, 1e-6)
        sv_product *= (sv_pct / 100.0)

    if sv_product <= 0:
        return 0.0

    return (0.65 * 0.4) / sv_product


def compute_payout_rank(unique_rows, baseline_df, min_payout=500.0):
    """
    METHOD 2 ranking: drops rows whose expected 13-rätt payout is below
    min_payout, then ranks the remaining rows by row probability under
    baseline_df's imp1/impx/imp2 (highest first).

    Args:
        unique_rows: DataFrame with columns m1..m13, one row per candidate
        baseline_df: DataFrame from parse_kupong() (or after Bayesian
            update) with match_nr, sv1, svx, sv2, imp1, impx, imp2
        min_payout: minimum expected payout (kr) to keep a row

    Returns:
        DataFrame with unique_rows' columns plus expected_payout and
        row_probability - sorted best-first (only rows above min_payout)
    """
    prob_lookup = {
        int(row["match_nr"]): {"1": row["imp1"], "X": row["impx"], "2": row["imp2"]}
        for _, row in baseline_df.iterrows()
    }

    payouts = []
    probs = []

    for _, row in unique_rows.iterrows():
        payouts.append(compute_expected_payout(row, baseline_df))

        row_prob = 1.0
        for m in range(1, 14):
            pick = str(row[f"m{m}"]).strip()
            row_prob *= prob_lookup.get(m, {}).get(pick, 1e-9)
        probs.append(row_prob)

    ranked = unique_rows.copy()
    ranked["expected_payout"] = payouts
    ranked["row_probability"] = probs

    ranked = ranked[ranked["expected_payout"] >= min_payout].reset_index(drop=True)
    ranked = ranked.sort_values(by="row_probability", ascending=False).reset_index(drop=True)

    return ranked




def compute_distribution_table(ranked_rows, baseline_df, top_n=300):
    """
    Computes, for each of the 13 matches, what percentage of the top_n rows
    picked "1", "X", or "2" - plus each match's home/away team names.

    Args:
        ranked_rows: DataFrame with columns m1..m13, already sorted best-first
        baseline_df: DataFrame from parse_kupong() with match_nr, home, away
        top_n: how many top rows to compute the distribution over

    Returns:
        DataFrame with columns: match_nr, home, away, pct_1, pct_X, pct_2
    """
    top_rows = ranked_rows.head(top_n)
    team_lookup = {
        int(row["match_nr"]): (row["home"], row["away"])
        for _, row in baseline_df.iterrows()
    }

    results = []
    for m in range(1, 14):
        col = top_rows[f"m{m}"].astype(str).str.strip()
        total = len(col)
        pct_1 = round(100 * (col == "1").sum() / total) if total > 0 else 0
        pct_x = round(100 * (col == "X").sum() / total) if total > 0 else 0
        pct_2 = round(100 * (col == "2").sum() / total) if total > 0 else 0

        home, away = team_lookup.get(m, ("", ""))
        results.append({
            "match_nr": m, "home": home, "away": away,
            "pct_1": pct_1, "pct_X": pct_x, "pct_2": pct_2
        })

    return pd.DataFrame(results)