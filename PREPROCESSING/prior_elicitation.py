"""
prior_elicitation.py
----------------
1. Fetches expert picks for the current round from Google Sheets.
2. Converts picks (1, X, 2, 1X, etc.) into implied probabilities based on
   an EV heuristic (an expert's pick reflects which outcome(s) they believe
   have the best expected value, not a direct probability estimate).
3. Combines multiple experts' priors into one consensus prior, weighted by
   confidence and inter-expert agreement.
4. Performs a Bayesian update of odds-implied probabilities using the
   consensus prior.
"""

import pandas as pd
import numpy as np
import gspread
from google.oauth2.service_account import Credentials


SERVICE_ACCOUNT_FILE = "stryktipset-priors-automation-27f390beda4d.json"
SHEET_ID = "1O7dHCXAblAGXLAzOKYQ93hr7DTkFUv7iqEg2aUkaidY"
TAB_NAME = "Current Round"


def fetch_current_round_from_sheets():
    """
    Fetches all expert picks for the current round from the "Current Round"
    tab of the Google Sheet.

    Returns:
        DataFrame with columns: timestamp, player_name, game_type,
        game_1..game_13
    """
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).worksheet(TAB_NAME)

    all_records = ws.get_all_values()
    if not all_records:
        return pd.DataFrame()

    headers = all_records[0]
    headers = [h.strip() if h else f"_empty_{i}" for i, h in enumerate(headers)]

    while headers and headers[-1].startswith("_empty_"):
        headers.pop()

    data_rows = all_records[1:] if len(all_records) > 1 else []
    data_rows = [row for row in data_rows if any(cell.strip() for cell in row[:len(headers)] if cell)]

    if not data_rows:
        return pd.DataFrame()

    trimmed_rows = [row[:len(headers)] for row in data_rows]
    df = pd.DataFrame(trimmed_rows, columns=headers)

    expected_cols = ["timestamp", "player_name", "game_type"] + [f"game_{i}" for i in range(1, 14)]
    missing = [col for col in expected_cols if col not in df.columns]
    if missing:
        raise ValueError(f"[ERROR] Missing columns in Google Sheet: {missing}")

    print(f"[INFO] Fetched {len(df)} rows from Google Sheets ({df['game_type'].iloc[0] if len(df) > 0 else 'N/A'})")
    return df


def _pick_to_probs_from_ev(pick_str, oddset1, oddsetx, oddset2, imp1, impx, imp2, ev_target=0.15, smoothing_temp=0.3):
    """
    Converts a single expert's pick for one match into (p1, pX, p2), based
    on the assumption that the expert's chosen outcome(s) have the highest
    expected value (EV). Sets EV = ev_target for chosen outcomes and solves
    for the implied probability, then smooths with a temperature-scaled
    softmax so no outcome gets exactly 0% probability.
    """
    if pd.isna(pick_str) or not pick_str:
        return (np.nan, np.nan, np.nan)

    pick_str = str(pick_str).strip().upper()
    pick_str = "".join(pick_str.split())

    market_probs = np.array([imp1, impx, imp2])
    market_odds = np.array([oddset1, oddsetx, oddset2])

    selected_outcomes = []
    if "1" in pick_str:
        selected_outcomes.append(0)
    if "X" in pick_str:
        selected_outcomes.append(1)
    if "2" in pick_str:
        selected_outcomes.append(2)

    if not selected_outcomes:
        return (np.nan, np.nan, np.nan)

    target_probs = np.zeros(3)

    if len(selected_outcomes) == 1:
        idx = selected_outcomes[0]
        target_probs[idx] = (1 + ev_target) / market_odds[idx]

        other_ev = max(0.0, ev_target - 0.05)
        for other_idx in [0, 1, 2]:
            if other_idx != idx:
                target_probs[other_idx] = (1 + other_ev) / market_odds[other_idx]
                max_prob = market_probs[other_idx] * 1.2
                target_probs[other_idx] = min(target_probs[other_idx], max_prob)
    else:
        for idx in selected_outcomes:
            individual_ev = ev_target * 0.85
            target_probs[idx] = (1 + individual_ev) / market_odds[idx]
            max_prob = market_probs[idx] * 1.5
            target_probs[idx] = min(target_probs[idx], max_prob)

        other_ev = max(0.0, ev_target * 0.3)
        for other_idx in [0, 1, 2]:
            if other_idx not in selected_outcomes:
                target_probs[other_idx] = (1 + other_ev) / market_odds[other_idx]
                max_prob = market_probs[other_idx] * 0.8
                target_probs[other_idx] = min(target_probs[other_idx], max_prob)

    total = target_probs.sum()
    if total > 0:
        target_probs = target_probs / total
    else:
        target_probs = market_probs

    logits = np.log(target_probs + 1e-10) / smoothing_temp
    exp_logits = np.exp(logits - np.max(logits))
    smoothed_probs = exp_logits / exp_logits.sum()

    smoothed_probs = np.maximum(smoothed_probs, 0.05)
    smoothed_probs = smoothed_probs / smoothed_probs.sum()

    return (float(smoothed_probs[0]), float(smoothed_probs[1]), float(smoothed_probs[2]))


def convert_picks_to_priors(sheet_df, kupong_df, default_confidence=7.0, ev_target=0.15, smoothing_temp=0.3):
    """
    Converts each expert's picks (from Google Sheets) into a per-match
    probability distribution, based on the EV heuristic above.

    Args:
        sheet_df: DataFrame from fetch_current_round_from_sheets()
        kupong_df: DataFrame from parse_kupong() with match info + odds
        default_confidence: confidence value (0-10) assigned to every pick
        ev_target: target EV for chosen outcomes (default 0.15 = 15% edge)
        smoothing_temp: softmax temperature for smoothing (lower = more smoothing)

    Returns:
        List of DataFrames, one per expert, each with columns:
        match_nr, home, away, p1, pX, p2, confidence, player
    """
    all_priors = []

    for player_name in sheet_df["player_name"].unique():
        player_data = sheet_df[sheet_df["player_name"] == player_name].iloc[0]

        rows = []
        for match_nr in range(1, 14):
            col_name = f"game_{match_nr}"
            if col_name not in player_data:
                continue

            pick = player_data[col_name]

            match_data = kupong_df[kupong_df["match_nr"] == match_nr]
            if match_data.empty:
                continue

            home = match_data["home"].iloc[0]
            away = match_data["away"].iloc[0]
            oddset1 = match_data["oddset1"].iloc[0]
            oddsetx = match_data["oddsetx"].iloc[0]
            oddset2 = match_data["oddset2"].iloc[0]
            imp1 = match_data["imp1"].iloc[0]
            impx = match_data["impx"].iloc[0]
            imp2 = match_data["imp2"].iloc[0]

            p1, pX, p2 = _pick_to_probs_from_ev(
                pick, oddset1, oddsetx, oddset2, imp1, impx, imp2,
                ev_target=ev_target, smoothing_temp=smoothing_temp
            )

            if all(pd.isna([p1, pX, p2])):
                continue

            rows.append({
                "match_nr": match_nr,
                "home": home,
                "away": away,
                "p1": float(p1) if not pd.isna(p1) else np.nan,
                "pX": float(pX) if not pd.isna(pX) else np.nan,
                "p2": float(p2) if not pd.isna(p2) else np.nan,
                "confidence": default_confidence,
                "player": len(all_priors) + 1
            })

        if rows:
            all_priors.append(pd.DataFrame(rows))

    return all_priors


def _normalize_triplet(p1, pX, p2):
    """Ensures (p1, pX, p2) sum to 1. Accepts percentages or fractions."""
    p1, pX, p2 = float(p1), float(pX), float(p2)
    s = p1 + pX + p2
    if s <= 0:
        return (1 / 3, 1 / 3, 1 / 3)
    if s > 1.5:  # likely percentages
        s = s / 100.0
        p1, pX, p2 = p1 / 100.0, pX / 100.0, p2 / 100.0
        return (p1 / s, pX / s, p2 / s)
    return (p1 / s, pX / s, p2 / s)


def _avg_pairwise_l1(dists, weights):
    """Computes weighted average L1 distance between all pairs of distributions."""
    n = len(dists)
    if n < 2:
        return 0.0

    l1_mean = 0.0
    total_weight = 0.0

    for i in range(n):
        for j in range(i + 1, n):
            w = weights[i] * weights[j]
            d1 = abs(dists[i][0] - dists[j][0])
            dX = abs(dists[i][1] - dists[j][1])
            d2 = abs(dists[i][2] - dists[j][2])
            l1 = d1 + dX + d2
            l1_mean += l1 * w
            total_weight += w

    if total_weight == 0:
        return 0.0

    l1_mean = l1_mean / total_weight
    return min(1.0, l1_mean / 2.0)


def compute_consensus_prior_and_k(priors_list, k_max=10, tau=0.30):
    """
    Combines multiple experts' priors into a single consensus prior per
    match, plus an agreement weight k reflecting both confidence and how
    much the experts agree with each other.

    Args:
        priors_list: list of DataFrames from convert_picks_to_priors()
        k_max: maximum possible agreement weight
        tau: disagreement scale parameter

    Returns:
        DataFrame with columns: match_nr, home, away, prior1, priorX, prior2, k
    """
    if not priors_list:
        return pd.DataFrame(columns=["match_nr", "home", "away", "prior1", "priorX", "prior2", "k"])

    df_all = pd.concat(priors_list, ignore_index=True)
    rows = []

    for match_nr, g in df_all.groupby("match_nr"):
        g = g.dropna(subset=["p1", "pX", "p2"], how="all")
        if g.empty:
            continue

        home = g["home"].mode().iat[0]
        away = g["away"].mode().iat[0]

        player_dists = []
        weights_raw = []

        for _, r in g.iterrows():
            if pd.isna(r["p1"]) or pd.isna(r["pX"]) or pd.isna(r["p2"]):
                continue
            try:
                normalized = _normalize_triplet(r["p1"], r["pX"], r["p2"])
                if not isinstance(normalized, tuple) or len(normalized) != 3:
                    continue
                if any(x is None or np.isnan(x) for x in normalized):
                    continue

                player_dists.append(normalized)
                weights_raw.append(r["confidence"] / 10)
            except (ValueError, TypeError) as e:
                print(f"[WARN] Could not normalize prior for match {match_nr}: {e}")
                continue

        if not player_dists:
            continue

        weights_raw = np.array(weights_raw)
        weights_norm = (
            weights_raw / weights_raw.sum()
            if weights_raw.sum() > 0
            else np.ones_like(weights_raw) / len(weights_raw)
        )

        mean_p1 = np.dot([d[0] for d in player_dists], weights_norm)
        mean_pX = np.dot([d[1] for d in player_dists], weights_norm)
        mean_p2 = np.dot([d[2] for d in player_dists], weights_norm)

        dist = _avg_pairwise_l1(player_dists, weights_raw)

        agreement_strength = 1.0 - min(1.0, dist / float(tau))
        player_factor = len(player_dists) / 3.0
        conf_factor = float(weights_raw.mean())

        k = int(round(k_max * agreement_strength * player_factor * conf_factor))

        rows.append({
            "match_nr": int(match_nr),
            "home": home,
            "away": away,
            "prior1": mean_p1,
            "priorX": mean_pX,
            "prior2": mean_p2,
            "k": k
        })

    return pd.DataFrame(rows)


def apply_bayesian_update(baseline_df, combined_prior):
    """
    Blends odds-implied probabilities with the expert consensus prior,
    weighted by each match's agreement weight k:
        posterior = (k * prior + odds_implied) / (k + 1)

    Matches with no expert prior are left unchanged.

    Args:
        baseline_df: DataFrame from parse_kupong() with imp1/impx/imp2
        combined_prior: DataFrame from compute_consensus_prior_and_k()

    Returns:
        New DataFrame with imp1/impx/imp2 replaced by posterior probabilities
    """
    if combined_prior.empty:
        print("[INFO] No priors provided - skipping Bayesian update entirely.")
        return baseline_df.copy()

    df = baseline_df.copy()
    df = df.merge(combined_prior, on="match_nr", how="left", suffixes=("", "_prior"))

    missing_mask = df["k"].isna()
    if missing_mask.any():
        skipped = df.loc[missing_mask, "match_nr"].tolist()
        print(f"[INFO] Skipping Bayesian update for matches with no expert prior: {skipped}")

    prior_col_map = {"imp1": "prior1", "impx": "priorX", "imp2": "prior2"}
    for col, prior_col in prior_col_map.items():
        df[col] = np.where(
            df["k"].isna(),
            df[col],
            ((df["k"] * df[prior_col]) + df[col]) / (df["k"] + 1)
        )

    return df[baseline_df.columns]