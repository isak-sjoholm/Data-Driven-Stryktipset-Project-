# Data-Driven Stryktipset Project

An automated data pipeline for Stryktipset (Swedish football pools) that combines market odds, crowd betting data (Svenska Folket), and three experts' (Isak, Ludde, Fredrik) individual predictions to select and rank betting rows using three different strategies. Runs fully automated via GitHub Actions.

## Overview

Every week:
1. The kupong (odds + Svenska Folket percentages) is automatically scraped from Svenska Spel
2. Three experts submit their picks via an external web app (Lovable UI), which writes to a shared Google Sheet
3. Expert picks are converted to probabilities and combined (weighted by agreement and confidence) with market odds via a Bayesian update
4. All ~1.6 million possible betting rows are filtered down against a data-driven model of historically realistic rows (90% of historical winning rows must pass the filter)
5. The remaining rows are ranked using three different methods (see below)
6. A results email with tables, stats, and attached row lists is sent automatically to all three experts

## The three ranking methods

**Method 1 — Agreement:** Ranks rows by how well they match the experts' picks (match by match), with the experts' confidence (less hedging = more confident) and odds probability as tiebreakers. Completely ignores expected payout - the goal is consensus among the experts.

**Method 2 — Expected payout:** Drops rows whose expected payout at 13 correct is below 10,000 kr (based on the Svenska Folket distribution), then ranks the rest by probability under the Bayesian-updated probabilities.

**Method 3 — Value:** Drops rows with below 0.002% probability of getting 13 correct, then ranks the rest by expected value (probability × expected payout).

## Architecture

The pipeline is split into standalone scripts running on different schedules via GitHub Actions:

| Script | Schedule | Purpose |
|---|---|---|
| `update_kuponger_scheduler.py` | Every 15 min | Keeps the kupong (odds, Svenska Folket) fresh in Google Sheets |
| `prepare_pool.py` | Saturday ~12:00 | Runs the heavy historical filtering (independent of the experts, saves the result to the repo) |
| `saturday_automation.py` | Saturday ~13:00, 3h window | Waits for all three experts to finish, runs priors/ranking/email |
| `move_priors_to_historical.py` | Friday evening/morning | Moves last week's data from "Current Round" to "Historical Rounds" |
| `send_reminder_if_needed.py` | Saturday 12:15 | Sends a reminder email if fewer than 3 experts have registered |

**Why is the heavy filtering split out separately?** The historical filtering search takes ~15-20 minutes and only depends on odds/Svenska Folket data - not on the experts' picks. By running it earlier (before the experts are expected to be done, since they often submit late to see starting lineups), `saturday_automation.py` avoids waiting on the heavy computation after the experts are finally ready.

## Folder structure
| `send_reminder_if_needed.py` | Saturday 12:15 | Sends a reminder email if fewer than 3 experts have registered |

**Why is the heavy filtering split out separately?** The historical filtering search takes ~15-20 minutes and only depends on odds/Svenska Folket data - not on the experts' picks. By running it earlier (before the experts are expected to be done, since they often submit late to see starting lineups), `saturday_automation.py` avoids waiting on the heavy computation after the experts are finally ready.

## Folder structure

RAW_DATA/ Historical raw data (CSV, committed)
PROCESSED_DATA/ Generated data (mostly gitignored, except the pool files)
PREPROCESSING/ Builds filtered/formatted history plus expert priors
ANALYSIS/ Kupong parsing, feature computation, historical filtering, (unused) logistic regression
KUPONG/ Scraping (Playwright) and Google Sheets read/write for the kupong
AUTOMATION/ All orchestration and ranking scripts
EMAIL/ Builds and sends results/reminder emails
.github/workflows/ GitHub Actions schedules




## Historical data source

`RAW_DATA/` contains 1219 historical Stryktipset rounds. `PREPROCESSING/preprocessing.py` filters and structures this into one file per round (`PROCESSED_DATA/kuponger_stryktipset/`), which is then used by the historical filtering search in `ANALYSIS/baseline_analysis.py`.

## The data-driven historical filtering

Instead of hardcoded thresholds, `get_historical_intervals()` searches for exactly how tight the filters (per feature: number of draws, odds ranges, Svenska Folket bins, etc.) can be set without losing more than 10% of historically winning rows. The search is greedy: at each step, it takes the cheapest possible tightening (least loss of historical accuracy) until no further tightening is possible without dropping below 90% retention. This normally eliminates over 80% of the ~1.6 million possible rows.

## Known limitations

- **Daylight saving time:** GitHub Actions cron schedules are in UTC and don't automatically adjust for Swedish summer/winter time. The times above assume summer time (UTC+2) - when winter time (UTC+1) begins, all actual clock times shift by an hour.
- **Logistic regression:** `ANALYSIS/log_reg_analysis.py` remains in the codebase but isn't used in production - a historical comparison showed it performs worse than market odds on both log loss and accuracy, since the model is only trained on odds + Svenska Folket data (no information the odds don't already contain).
- **Stryktipset only:** the project is simplified to only handle Stryktipset (Europatipset/Topptipset are not supported).

## Required secrets (GitHub repo secrets)

| Secret | Content |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full contents of the Google service account key JSON file |
| `EMAIL_CONFIG` | Full contents of `email_config.txt` (SMTP credentials) |
| `EXPERT_EMAILS` | Comma-separated list of the experts' email addresses |

## Running locally

Each script can be run directly, e.g.:

```bash
python -m PREPROCESSING.preprocessing
python -m AUTOMATION.prepare_pool
python -m AUTOMATION.saturday_automation
```

Requires locally: `stryktipset-priors-automation-*.json` (service account key) and `email_config.txt` in the repo root - **both are gitignored and must never be committed.**