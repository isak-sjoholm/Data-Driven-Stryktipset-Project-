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



def compute_agreement_with_experts_table(ranked_rows, expert_panel, sheet_df, baseline_df, top_n=300):
    """
    Computes, for each expert (plus Svenska Folket), what percentage of
    their fully expanded rows are found among the top_n ranked rows.

    Args:
        ranked_rows: DataFrame with columns m1..m13, already sorted best-first
        expert_panel: DataFrame with columns match_nr, pick, player (long
            format, one row per expert per match) - used to get player IDs
        sheet_df: DataFrame from check_experts_ready(), with player_name and
            game_1..game_13 columns - used to expand each expert's picks
        baseline_df: DataFrame from parse_kupong() with match_nr, sv1, svx, sv2
        top_n: how many top rows to check agreement against

    Returns:
        DataFrame with columns: name, agreement_pct
    """
    match_cols = [f"m{i}" for i in range(1, 14)]
    top_set = set(tuple(row) for row in ranked_rows[match_cols].head(top_n).astype(str).values)

    results = []

    # Per-expert agreement
    for player_id, (_, expert_row) in enumerate(sheet_df.iterrows(), start=1):
        rows = [{"match_nr": m, "pick": expert_row[f"game_{m}"], "player": player_id} for m in range(1, 14)]
        df_expert = pd.DataFrame(rows)
        expanded = expand_expert_to_rows(df_expert)

        total = len(expanded)
        if total == 0:
            results.append({"name": expert_row["player_name"], "agreement_pct": 0})
            continue

        matches = sum(
            1 for _, r in expanded.iterrows()
            if tuple(str(r[c]) for c in match_cols) in top_set
        )
        agreement_pct = round(100 * matches / total)
        results.append({"name": expert_row["player_name"], "agreement_pct": agreement_pct})

    # Svenska Folket agreement: majority pick per match vs. majority in top_n
    total_matches = 0
    matches_agree = 0
    for m in range(1, 14):
        match_col = f"m{m}"
        top_picks = ranked_rows[match_col].head(top_n).value_counts()
        if len(top_picks) == 0:
            continue
        majority_pick = top_picks.index[0]

        sv_row = baseline_df[baseline_df["match_nr"] == m].iloc[0]
        sv_map = {"1": sv_row["sv1"], "X": sv_row["svx"], "2": sv_row["sv2"]}
        sv_majority = max(sv_map, key=sv_map.get)

        if majority_pick == sv_majority:
            matches_agree += 1
        total_matches += 1

    sv_agreement_pct = round(100 * matches_agree / total_matches) if total_matches > 0 else 0
    results.append({"name": "Svenska Folket", "agreement_pct": sv_agreement_pct})

    return pd.DataFrame(results)



def rows_to_txt(ranked_rows, top_n=300, game_type="Stryktipset"):
    """
    Converts the top_n ranked rows into the txt format used for the emailed
    attachment: one header line with the game type, then one line per row
    in the format "E,1,X,2,...".

    Args:
        ranked_rows: DataFrame with columns m1..m13, already sorted best-first
        top_n: how many top rows to include
        game_type: written as the header line

    Returns:
        str: the full txt content
    """
    match_cols = [f"m{i}" for i in range(1, 14)]
    top_rows = ranked_rows[match_cols].head(top_n)

    lines = [game_type]
    for _, row in top_rows.iterrows():
        outcomes = [str(row[c]).strip() for c in match_cols]
        lines.append("E," + ",".join(outcomes))

    return "\n".join(lines)




def compute_value_rank(unique_rows, baseline_df, min_probability=0.00002):
    """
    METHOD 3 ranking: drops rows whose probability of 13 rätt is below
    min_probability, then ranks the remaining rows by expected value:
        EV = row_probability * (expected_payout + 1)
    (the "-1" constant from the full formula P13*payout - (1-P13) doesn't
    affect ranking, so it's dropped here)

    Args:
        unique_rows: DataFrame with columns m1..m13, one row per candidate
        baseline_df: DataFrame from parse_kupong() (or after Bayesian
            update) with match_nr, sv1, svx, sv2, imp1, impx, imp2
        min_probability: minimum row probability (P13) to keep a row

    Returns:
        DataFrame with unique_rows' columns plus row_probability,
        expected_payout, and expected_value - sorted best-first (only rows
        above min_probability)
    """
    prob_lookup = {
        int(row["match_nr"]): {"1": row["imp1"], "X": row["impx"], "2": row["imp2"]}
        for _, row in baseline_df.iterrows()
    }

    probs = []
    payouts = []

    for _, row in unique_rows.iterrows():
        row_prob = 1.0
        for m in range(1, 14):
            pick = str(row[f"m{m}"]).strip()
            row_prob *= prob_lookup.get(m, {}).get(pick, 1e-9)
        probs.append(row_prob)
        payouts.append(compute_expected_payout(row, baseline_df))

    ranked = unique_rows.copy()
    ranked["row_probability"] = probs
    ranked["expected_payout"] = payouts
    ranked["expected_value"] = ranked["row_probability"] * (ranked["expected_payout"] + 1)

    ranked = ranked[ranked["row_probability"] >= min_probability].reset_index(drop=True)
    ranked = ranked.sort_values(by="expected_value", ascending=False).reset_index(drop=True)

    return ranked





import numpy as np

def calculate_method_stats(top_rows, baseline_df, n_simulations=100000):
    """
    Simulates n_simulations random rounds (drawn from baseline_df's
    imp1/impx/imp2) and computes:
    - prob_13: probability that AT LEAST ONE of top_rows gets all 13 right
    - mean_payout: expected payout, weighted by each row's own P(13 rätt)
    - min_payout / max_payout: payout range among rows with P(13 rätt) > 0

    Args:
        top_rows: DataFrame with columns m1..m13 (the rows being evaluated)
        baseline_df: DataFrame from parse_kupong() (or after Bayesian
            update) with match_nr, imp1, impx, imp2, sv1, svx, sv2

    Returns:
        dict with prob_13, mean_payout, min_payout, max_payout
    """
    match_cols = [f"m{i}" for i in range(1, 14)]
    probs_by_match = {
        int(row["match_nr"]): [row["imp1"], row["impx"], row["imp2"]]
        for _, row in baseline_df.iterrows()
    }
    choices = ["1", "X", "2"]

    # Simulate n_simulations rounds
    sim_results = np.empty((n_simulations, 13), dtype="<U1")
    for i, m in enumerate(range(1, 14)):
        p = probs_by_match[m]
        sim_results[:, i] = np.random.choice(choices, size=n_simulations, p=p)

    # Compare each row against every simulation
    predictions = top_rows[match_cols].astype(str).values
    n_rows = len(predictions)

    # For each row, count how many simulations it matched exactly (13/13)
    row_win_counts = np.zeros(n_rows, dtype=int)
    any_win_count = 0

    for sim_idx in range(n_simulations):
        sim = sim_results[sim_idx]
        matches = (predictions == sim).all(axis=1)
        if matches.any():
            any_win_count += 1
        row_win_counts += matches.astype(int)

    prob_13 = any_win_count / n_simulations
    prob_13_per_row = row_win_counts / n_simulations

    # Compute payout per row
    payouts = np.array([compute_expected_payout(row, baseline_df) for _, row in top_rows.iterrows()])

    # Mean payout: weighted by each row's own P(13 rätt)
    if prob_13_per_row.sum() > 0:
        weights = prob_13_per_row / prob_13_per_row.sum()
        mean_payout = float(np.sum(payouts * weights))
    else:
        mean_payout = 0.0

    valid_mask = prob_13_per_row > 0
    if valid_mask.sum() > 0:
        min_payout = float(payouts[valid_mask].min())
        max_payout = float(payouts[valid_mask].max())
    else:
        min_payout = float(payouts.min()) if len(payouts) > 0 else 0.0
        max_payout = float(payouts.max()) if len(payouts) > 0 else 0.0

    return {
        "prob_13": prob_13,
        "mean_payout": mean_payout,
        "min_payout": min_payout,
        "max_payout": max_payout,
    }



