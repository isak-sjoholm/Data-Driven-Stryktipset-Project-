"""
automation_checker.py
--------------------
Checks Google Sheets and verifies when enough experts have submitted their
priors for the current round.
"""

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime


SERVICE_ACCOUNT_FILE = "stryktipset-priors-automation-27f390beda4d.json"
SHEET_ID = "1O7dHCXAblAGXLAzOKYQ93hr7DTkFUv7iqEg2aUkaidY"
TAB_NAME = "Current Round"


def check_experts_ready(required_experts=3):
    """
    Checks Google Sheets and returns:
    - (True, df) if enough experts have submitted
    - (False, df) if not enough experts yet (df may still contain partial data)
    - (False, None) if an error occurs or no data exists

    Args:
        required_experts: minimum number of unique experts needed

    Returns:
        (bool, DataFrame or None)
    """
    try:
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(SHEET_ID).worksheet(TAB_NAME)

        all_records = ws.get_all_values()
        if not all_records:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] No data in Google Sheets yet.")
            return False, None

        headers = all_records[0]
        headers = [h.strip() if h else f"_empty_{i}" for i, h in enumerate(headers)]
        while headers and headers[-1].startswith("_empty_"):
            headers.pop()

        data_rows = all_records[1:] if len(all_records) > 1 else []
        data_rows = [row for row in data_rows if any(cell.strip() for cell in row[:len(headers)] if cell)]

        if not data_rows:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] No data in Google Sheets yet.")
            return False, None

        trimmed_rows = [row[:len(headers)] for row in data_rows]
        df = pd.DataFrame(trimmed_rows, columns=headers)

        if df.empty:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] No data in Google Sheets yet.")
            return False, None

        # Filter out rows with empty player_name
        if "player_name" in df.columns:
            df = df[df["player_name"].notna()]
            df = df[df["player_name"].astype(str).str.strip() != ""]

        # Keep only the latest submission per expert
        df = df.sort_values("timestamp").drop_duplicates(subset="player_name", keep="last")

        unique_experts = df["player_name"].nunique()

        if unique_experts >= required_experts:
            expert_names = ", ".join(df["player_name"].unique())
            print(f"[{datetime.now().strftime('%H:%M:%S')}] All {unique_experts} experts ready! ({expert_names})")
            return True, df
        else:
            expert_names = ", ".join(df["player_name"].unique()) if unique_experts > 0 else "none"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting... {unique_experts}/{required_experts} experts ({expert_names})")
            return False, df

    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error fetching data: {e}")
        return False, None