"""
log_reg_analysis.py
----------------
1. Parses a gameweek ("kupong") for the logistic regression model, keeping
   raw odds and crowd percentages as features (no implied-probability
   conversion).
2. Trains a calibrated multinomial logistic regression model for
   Stryktipset, predicting match outcome (1/X/2) probabilities from odds
   and crowd percentages, using historical match data.
3. Applies the trained model to a new gameweek to predict probabilities.
"""

import os
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import LabelEncoder


# SETUP - paths relative to this file's location
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(ROOT_DIR, "PROCESSED_DATA")

FEATURE_COLS = ["oddset1", "oddsetx", "oddset2", "svfolket1", "svfolketx", "svfolket2"]


def parse_kupong_for_log_reg(raw_input):
    """
    Parses a semicolon-separated kupong into 13 games, keeping raw odds and
    crowd percentages as-is (no implied-probability conversion) - these are
    the features the logistic regression model expects.
    """
    rows = []
    games = [g.strip() for g in raw_input.split(";") if g.strip()]

    for i, game in enumerate(games, 1):
        game = game.lstrip().removeprefix(f"Game {i},").strip()
        parts = [p.strip() for p in game.split(", ")]
        if len(parts) != 8:
            raise ValueError(f"Game {i} does not have exactly 8 comma-space-separated values: {parts}")

        home, away, sv1, svx, sv2, o1, ox, o2 = parts
        sv_1, sv_x, sv_2 = map(float, (sv1, svx, sv2))
        o1 = float(o1.replace(",", "."))
        ox = float(ox.replace(",", "."))
        o2 = float(o2.replace(",", "."))

        rows.append({
            "match_nr": i, "home": home, "away": away,
            "sv1": sv_1, "svx": sv_x, "sv2": sv_2,
            "odds1": o1, "oddsx": ox, "odds2": o2,
        })

    return pd.DataFrame(rows)


def build_log_reg_model():
    """
    Trains a calibrated multinomial logistic regression model for
    Stryktipset, predicting match outcome (1/X/2) probabilities from odds
    and crowd percentages. Trained on every individual historical match
    (ML_stryktipset.csv, built by PREPROCESSING.preprocessing).

    Returns:
        (clf, label_encoder) tuple
    """
    csv_path = os.path.join(PROCESSED_DIR, "ML_stryktipset.csv")
    df = pd.read_csv(csv_path)

    X = df[FEATURE_COLS].astype(float)
    y = df["utfall"].astype(str)

    lbl = LabelEncoder()
    y_encoded = lbl.fit_transform(y)

    base_clf = LogisticRegression(solver="lbfgs", max_iter=1000)
    clf = CalibratedClassifierCV(estimator=base_clf, cv=5, method="isotonic")
    clf.fit(X, y_encoded)

    print(f"[INFO] Trained logistic regression model on {len(df)} matches")
    return clf, lbl


def score_log_reg_probabilities(raw_input, clf, lbl):
    """
    Applies the trained model to a new kupong, returning predicted
    probabilities (p1, pX, p2) for each of the 13 matches.

    Args:
        raw_input: kupong string, same format as parse_kupong()
        clf: trained classifier from build_log_reg_model()
        lbl: label encoder from build_log_reg_model()

    Returns:
        DataFrame with match_nr, p1, pX, p2
    """
    df_in = parse_kupong_for_log_reg(raw_input)

    df_in = df_in.rename(columns={
        "odds1": "oddset1", "oddsx": "oddsetx", "odds2": "oddset2",
        "sv1": "svfolket1", "svx": "svfolketx", "sv2": "svfolket2",
    })

    X_new = df_in[FEATURE_COLS].astype(float)

    probabilities = clf.predict_proba(X_new)
    class_labels = lbl.inverse_transform(clf.classes_)

    probabilities_df = pd.DataFrame(probabilities, columns=[f"p{c}" for c in class_labels], index=df_in.index)
    probabilities_df.insert(0, "match_nr", df_in["match_nr"])

    return probabilities_df