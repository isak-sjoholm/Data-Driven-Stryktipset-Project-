"""
saturday_automation.py
-----------------------
Main orchestration script: runs the full Stryktipset pipeline once experts
are ready - fetches the kupong, builds expert priors, runs the historical
threshold search, ranks candidate rows with all three methods (agreement,
payout, value), and emails the results.

Usage:
    python -m AUTOMATION.saturday_automation
"""

import os
import pandas as pd
from datetime import datetime
import json

from AUTOMATION.automation_checker import check_experts_ready
from AUTOMATION.automated_runner import (
    expand_expert_to_rows,
    compute_agreement_rank,
    compute_payout_rank,
    compute_value_rank,
    compute_distribution_table,
    compute_agreement_with_experts_table,
    compute_expert_dropout_breakdown,
    calculate_method_stats,
    rows_to_txt,
)
from KUPONG.kupong_fetcher import check_kupong_in_sheets
from PREPROCESSING.prior_elicitation import (
    convert_picks_to_priors,
    compute_consensus_prior_and_k,
    apply_bayesian_update,
)
from ANALYSIS.baseline_analysis import (
    parse_kupong,
    compute_features_vectorized,
    get_historical_intervals,
    filter_combinations_by_intervals,
    describe_applied_filters,
    PROCESSED_DIR,
    RAW_DIR,
)
from EMAIL.email_sender import build_email_html, send_combined_results_email

TOP_N = 300
MIN_PAYOUT = 10000.0
MIN_PROBABILITY = 0.00002

_expert_emails_env = os.environ.get("EXPERT_EMAILS")
if _expert_emails_env:
    RECIPIENTS = [e.strip() for e in _expert_emails_env.split(",") if e.strip()]
else:
    RECIPIENTS = ["isaksjo04@gmail.com"]  # local testing fallback


def run_pipeline(game_type="Stryktipset"):
    print("=" * 80)
    print(f"SATURDAY AUTOMATION - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # STEP 1: Check experts are ready
    print("\n[STEP 1] Checking experts...")
    is_ready, sheet_df = check_experts_ready(required_experts=3)
    if not is_ready or sheet_df is None:
        print("[INFO] Not enough experts ready. Exiting.")
        return
    print(f"[INFO] {sheet_df['player_name'].nunique()} experts ready: {', '.join(sheet_df['player_name'].unique())}")

    # STEP 2: Fetch kupong
    print("\n[STEP 2] Fetching kupong...")
    has_kupong, raw_kupong = check_kupong_in_sheets(game_type)
    if not has_kupong:
        raise ValueError(f"No kupong found for {game_type}")
    baseline_df = parse_kupong(raw_kupong)
    print(f"[INFO] Kupong parsed ({len(baseline_df)} matches)")

    # STEP 3: Build expert priors -> consensus -> Bayesian update
    print("\n[STEP 3] Building priors and applying Bayesian update...")
    priors = convert_picks_to_priors(sheet_df, baseline_df)
    consensus = compute_consensus_prior_and_k(priors)
    baseline_updated = apply_bayesian_update(baseline_df, consensus)
    print("[INFO] Bayesian update applied")


    # STEP 4: Load the pre-filtered pool (built earlier by prepare_pool.py), or
    # build it now if it doesn't exist yet (local testing / fallback)
    print("\n[STEP 4] Loading pre-filtered pool...")
    pool_dir = os.path.join(PROCESSED_DIR, "filled_combinations")
    pool_path = os.path.join(pool_dir, f"filtered_combinations_{game_type.lower()}.csv")
    meta_path = os.path.join(pool_dir, f"pool_meta_{game_type.lower()}.json")

    if os.path.exists(pool_path) and os.path.exists(meta_path):
        pool = pd.read_csv(pool_path, dtype=str, low_memory=False)
        with open(meta_path, "r") as f:
            pool_meta = json.load(f)
        total_before = pool_meta["total_before"]
        filter_descriptions = pool_meta["filter_descriptions"]
        total_after = len(pool)
        print(f"[INFO] Loaded pre-built pool: {total_after:,} rows (built earlier by prepare_pool.py)")
    else:
        print("[WARN] No pre-built pool found - building it now (this will take a while)...")
        combos = pd.read_csv(os.path.join(RAW_DIR, f"all_combinations_{game_type.lower()}.csv"), dtype=str, low_memory=False)
        total_before = len(combos)
        combo_features = compute_features_vectorized(combos, baseline_updated)
        thresholds, historical_features = get_historical_intervals(
            os.path.join(PROCESSED_DIR, f"kuponger_{game_type.lower()}"),
            baseline_updated,
            combo_features,
            target_retention=0.90,
        )
        filter_descriptions = describe_applied_filters(thresholds, historical_features)
        filtered_path = filter_combinations_by_intervals(game_type, baseline_updated, thresholds)
        pool = pd.read_csv(filtered_path, dtype=str, low_memory=False)
        total_after = len(pool)
        print(f"[INFO] Pool after historical filtering: {total_after:,} rows")


    # STEP 5: Build expert panel + per-expert row counts (before/after historical filter)
    match_cols = [f"m{i}" for i in range(1, 14)]
    pool_set = set(tuple(row) for row in pool[match_cols].astype(str).values)

    expert_panel_rows = []
    total_expanded_per_expert = {}
    after_historical_filter_per_expert = {}
    expanded_rows_by_expert = {}

    for player_id, (_, expert_row) in enumerate(sheet_df.iterrows(), start=1):
        for m in range(1, 14):
            expert_panel_rows.append({"match_nr": m, "pick": expert_row[f"game_{m}"], "player": player_id})
        rows = [{"match_nr": m, "pick": expert_row[f"game_{m}"], "player": player_id} for m in range(1, 14)]
        expanded = expand_expert_to_rows(pd.DataFrame(rows))
        expanded_rows_by_expert[expert_row["player_name"]] = expanded

        total_expanded_per_expert[expert_row["player_name"]] = len(expanded)
        surviving = sum(1 for _, r in expanded.iterrows() if tuple(str(r[c]) for c in match_cols) in pool_set)
        after_historical_filter_per_expert[expert_row["player_name"]] = surviving

    expert_panel = pd.DataFrame(expert_panel_rows)

    # STEP 6: Rank with all three methods
    print("\n[STEP 6] Ranking with all three methods...")
    agreement_ranked = compute_agreement_rank(pool, expert_panel, baseline_updated)
    payout_ranked = compute_payout_rank(pool, baseline_updated, min_payout=MIN_PAYOUT)
    value_ranked = compute_value_rank(pool, baseline_updated, min_probability=MIN_PROBABILITY)
    print(f"[INFO] Agreement: {len(agreement_ranked):,} rows | Payout: {len(payout_ranked):,} rows after threshold | Value: {len(value_ranked):,} rows after threshold")

    # STEP 7: Per-expert row counts surviving each method's secondary filter (for dropout breakdown)
    payout_set = set(tuple(row) for row in payout_ranked[match_cols].astype(str).values)
    value_set = set(tuple(row) for row in value_ranked[match_cols].astype(str).values)

    after_payout_filter_per_expert = {}
    after_value_filter_per_expert = {}
    for name, expanded in expanded_rows_by_expert.items():
        after_payout_filter_per_expert[name] = sum(
            1 for _, r in expanded.iterrows() if tuple(str(r[c]) for c in match_cols) in payout_set
        )
        after_value_filter_per_expert[name] = sum(
            1 for _, r in expanded.iterrows() if tuple(str(r[c]) for c in match_cols) in value_set
        )

    # STEP 8: Build tables, stats, and dropout breakdowns for each method
    print("\n[STEP 8] Building result tables and stats (this includes Monte Carlo simulation - may take a while)...")
    method_results = {}
    txt_attachments = {}

    method_configs = [
        ("agreement", agreement_ranked, 1, None, None),
        ("payout", payout_ranked, 2, after_historical_filter_per_expert, after_payout_filter_per_expert),
        ("value", value_ranked, 3, after_historical_filter_per_expert, after_value_filter_per_expert),
    ]

    for method_key, ranked_df, method_number, hist_counts, secondary_counts in method_configs:
        dist_table = compute_distribution_table(ranked_df, baseline_updated, top_n=TOP_N)
        agreement_table = compute_agreement_with_experts_table(ranked_df, expert_panel, sheet_df, baseline_updated, top_n=TOP_N)
        stats = calculate_method_stats(ranked_df.head(TOP_N), baseline_updated, n_simulations=100000)

        agreement_pct_per_expert = dict(zip(agreement_table["name"], agreement_table["agreement_pct"]))
        dropout_explanations = compute_expert_dropout_breakdown(
            sheet_df,
            total_expanded_per_expert,
            after_historical_filter_per_expert,
            agreement_pct_per_expert,
            after_secondary_filter_per_expert=secondary_counts,
            method_number=method_number,
        )

        method_results[method_key] = {
            "row_count": min(TOP_N, len(ranked_df)),
            "remaining_count": len(ranked_df),
            "distribution_df": dist_table,
            "agreement_df": agreement_table,
            "stats": stats,
            "dropout_explanations": dropout_explanations,
        }
        txt_attachments[f"Metod_{method_number}_{method_key}.txt"] = rows_to_txt(ranked_df, top_n=TOP_N, game_type=game_type)
        print(f"[INFO] Method {method_number} ({method_key}) done")

    method_results["payout"]["min_payout"] = MIN_PAYOUT
    method_results["value"]["min_probability"] = MIN_PROBABILITY

    # STEP 9: Build prior/consensus/odds/Bayesian tables for the email
    prior_tables = {}
    for i, (_, expert_row) in enumerate(sheet_df.iterrows()):
        if i < len(priors):
            prior_tables[expert_row["player_name"]] = priors[i]

    # STEP 10: Build and send email
    print("\n[STEP 10] Building and sending email...")
    html_body = build_email_html(
        game_type=game_type,
        total_combos_before=total_before,
        filter_descriptions=filter_descriptions,
        total_combos_after=total_after,
        expert_counts_after_filter=after_historical_filter_per_expert,
        prior_tables=prior_tables,
        consensus_df=consensus,
        odds_implied_df=baseline_df,
        bayesian_df=baseline_updated,
        method1=method_results["agreement"],
        method2=method_results["payout"],
        method3=method_results["value"],
    )

    subject = f"{game_type} - Resultat ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    success = send_combined_results_email(RECIPIENTS, html_body, txt_attachments, subject)

    print("\n" + "=" * 80)
    print(f"DONE: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Email sent: {success}")
    print("=" * 80)


if __name__ == "__main__":
    run_pipeline("Stryktipset")