# My Trading Journal App

A simple, self-hosted trading journal & activity log built with Streamlit + SQLite.

## Setup
1. Install dependencies: `pip install streamlit pandas`
2. Place `trading_journal.db` and `app.py` in the same folder
3. Run: `streamlit run app.py`

## What it tracks
- **Activity Log**: every research question, strategy idea, or chat request you make (like this conversation)
- **Trades**: entry/exit, P&L, strategy tags
- **Watchlist**: tickers you're monitoring and why
- **Analytics**: win rate, total P&L, per-ticker performance

## Pre-seeded data
This build already includes two log entries from your Perplexity conversation:
1. Research into best stock trading apps for 2026 (Fidelity, Schwab, Robinhood, Webull, E*TRADE)
2. This app-build request itself

## Next steps
- Add broker CSV import (e.g., Robinhood/Fidelity export) for auto-logging trades
- Add tagging/filtering by strategy or emotion
- Deploy to Streamlit Community Cloud for access from any device
