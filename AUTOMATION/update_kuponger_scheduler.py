"""
update_kuponger_scheduler.py
-----------------------------
Keeps the current round's kupong fresh in Google Sheets by re-scraping
Svenska Spel and writing the result. Intended to run every 15 minutes via
a scheduled job.

Usage:
    python -m AUTOMATION.update_kuponger_scheduler
"""

from datetime import datetime

from KUPONG.kupong_scraper import fetch_from_svenskaspel
from KUPONG.kupong_fetcher import write_kupong_to_sheets

GAME_TYPE = "Stryktipset"


def update_kupong():
    """
    Fetches the latest kupong from Svenska Spel and writes it to Google
    Sheets. Logs whether the result is a real kupong or a placeholder
    (no active round).
    """
    print("=" * 80)
    print(f"UPDATE KUPONG - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    try:
        kupong = fetch_from_svenskaspel(GAME_TYPE)

        if not kupong:
            print(f"[ERROR] Could not fetch kupong for {GAME_TYPE}")
            return False

        is_placeholder = "NA, NA" in kupong
        write_kupong_to_sheets(kupong, GAME_TYPE)

        if is_placeholder:
            print(f"[WARN] {GAME_TYPE}: No active round found, wrote placeholder ({len(kupong)} chars)")
        else:
            print(f"[INFO] {GAME_TYPE}: Updated ({len(kupong)} chars)")

        return True

    except Exception as e:
        print(f"[ERROR] {GAME_TYPE}: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        print(f"\nDone: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)


if __name__ == "__main__":
    update_kupong()