"""
send_reminder_if_needed.py
---------------------------
Sends a reminder email every Saturday if not enough experts have
registered their priors yet.

Runs automatically via cron/Actions:
    15 12 * * 6 cd "/path/to/project" && python -m AUTOMATION.send_reminder_if_needed

Usage:
    python -m AUTOMATION.send_reminder_if_needed
"""

import sys
import os
from datetime import datetime

from PREPROCESSING.prior_elicitation import fetch_current_round_from_sheets
from EMAIL.email_sender import send_reminder_email

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT_DIR, ".cache")


def _state_file(task_name):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{task_name}.last_sent")


def _read_last_sent(task_name):
    path = _state_file(task_name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except Exception:
        return None


def _mark_sent(task_name, date_str):
    path = _state_file(task_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(date_str)


def check_and_send_reminder():
    """
    Checks whether new priors exist. If not (fewer than 3 experts), sends
    a reminder email.

    Returns:
        bool: True if a reminder was sent, False otherwise
    """
    print("=" * 80)
    print("REMINDER EMAIL - CHECK")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()

    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        if _read_last_sent("send_reminder_if_needed") == today_str:
            print("[INFO] Reminder already sent today - aborting")
            print("=" * 80)
            return False

        df = fetch_current_round_from_sheets()
        unique_experts = 0

        if not df.empty:
            if "player_name" in df.columns:
                df = df[df["player_name"].notna()]
                df = df[df["player_name"].astype(str).str.strip() != ""]
                unique_experts = df["player_name"].nunique()

        if unique_experts >= 3:
            print(f"\n[INFO] {unique_experts} priors found - no reminder needed")
            print("=" * 80)
            return False
        else:
            print(f"[WARN] Only {unique_experts} priors found (need at least 3)")
            print("[INFO] Sending reminder email...")
            print()

            recipients = [
                "ludinho14@gmail.com",
                "fredrik-a@hotmail.com",
                "isaksjo04@gmail.com"
            ]

            if os.environ.get("REMINDER_TEST_ONLY") == "1":
                recipients = ["isaksjo04@gmail.com"]

            success = send_reminder_email(recipient_emails=recipients)

            if success:
                _mark_sent("send_reminder_if_needed", today_str)
                print(f"[INFO] Reminder email sent to {len(recipients)} recipients")
                print("=" * 80)
                return True
            else:
                print("[ERROR] Could not send reminder email")
                print("=" * 80)
                return False

    except Exception as e:
        print(f"[ERROR] Failed to check/send: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        return False


if __name__ == "__main__":
    try:
        success = check_and_send_reminder()
        if success:
            print("\n[INFO] Process succeeded!")
            sys.exit(0)
        else:
            print("\n[INFO] No reminder sent (priors already exist or an error occurred)")
            sys.exit(0)
    except KeyboardInterrupt:
        print("\n\n[WARN] Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n[ERROR] Critical error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)