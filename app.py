"""
Personal Trading Journal App
Run: streamlit run app.py
"""
import streamlit as st
import sqlite3
import pandas as pd
import datetime

DB_PATH = "trading_journal.db"

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def log_activity(category, request, outcome, notes=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO activity_log (timestamp, category, request, outcome, notes) VALUES (?,?,?,?,?)",
        (datetime.datetime.now().isoformat(), category, request, outcome, notes)
    )
    conn.commit()
    conn.close()

def log_trade(date, ticker, side, qty, entry, exitp, pnl, strategy, notes):
    conn = get_conn()
    conn.execute(
        "INSERT INTO trades (date, ticker, side, quantity, entry_price, exit_price, pnl, strategy, notes) VALUES (?,?,?,?,?,?,?,?,?)",
        (date, ticker, side, qty, entry, exitp, pnl, strategy, notes)
    )
    conn.commit()
    conn.close()

def add_watchlist(ticker, reason):
    conn = get_conn()
    conn.execute(
        "INSERT INTO watchlist (ticker, reason, date_added) VALUES (?,?,?)",
        (ticker, reason, datetime.date.today().isoformat())
    )
    conn.commit()
    conn.close()

st.set_page_config(page_title="My Trading Journal", layout="wide")
st.title("📈 My Trading Journal")

tab1, tab2, tab3, tab4 = st.tabs(["Activity Log", "Trades", "Watchlist", "Analytics"])

with tab1:
    st.subheader("Log a Research / Chat Activity")
    with st.form("activity_form", clear_on_submit=True):
        category = st.selectbox("Category", ["App Research", "Strategy", "News", "Question", "Other"])
        request = st.text_input("What did you ask / work on?")
        outcome = st.text_area("Outcome / Answer summary")
        notes = st.text_area("Notes")
        if st.form_submit_button("Save Entry"):
            log_activity(category, request, outcome, notes)
            st.success("Logged!")

    conn = get_conn()
    df = pd.read_sql("SELECT * FROM activity_log ORDER BY id DESC", conn)
    conn.close()
    st.dataframe(df, use_container_width=True)

with tab2:
    st.subheader("Log a Trade")
    with st.form("trade_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        date = col1.date_input("Date", datetime.date.today())
        ticker = col2.text_input("Ticker")
        side = col3.selectbox("Side", ["Long", "Short"])
        qty = col1.number_input("Quantity", min_value=0.0)
        entry = col2.number_input("Entry Price", min_value=0.0)
        exitp = col3.number_input("Exit Price", min_value=0.0)
        strategy = st.text_input("Strategy / Setup")
        notes = st.text_area("Trade Notes")
        if st.form_submit_button("Save Trade"):
            pnl = (exitp - entry) * qty if side == "Long" else (entry - exitp) * qty
            log_trade(str(date), ticker.upper(), side, qty, entry, exitp, pnl, strategy, notes)
            st.success(f"Trade saved. P&L: ${pnl:,.2f}")

    conn = get_conn()
    df_trades = pd.read_sql("SELECT * FROM trades ORDER BY id DESC", conn)
    conn.close()
    st.dataframe(df_trades, use_container_width=True)

with tab3:
    st.subheader("Watchlist")
    with st.form("watch_form", clear_on_submit=True):
        wt = st.text_input("Ticker")
        wr = st.text_input("Reason")
        if st.form_submit_button("Add to Watchlist"):
            add_watchlist(wt.upper(), wr)
            st.success("Added!")
    conn = get_conn()
    df_watch = pd.read_sql("SELECT * FROM watchlist ORDER BY id DESC", conn)
    conn.close()
    st.dataframe(df_watch, use_container_width=True)

with tab4:
    st.subheader("Performance Analytics")
    conn = get_conn()
    df_trades = pd.read_sql("SELECT * FROM trades", conn)
    conn.close()
    if not df_trades.empty:
        total_pnl = df_trades["pnl"].sum()
        win_rate = (df_trades["pnl"] > 0).mean() * 100
        st.metric("Total P&L", f"${total_pnl:,.2f}")
        st.metric("Win Rate", f"{win_rate:.1f}%")
        st.bar_chart(df_trades.set_index("ticker")["pnl"])
    else:
        st.info("Log some trades to see analytics.")
