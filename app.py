import streamlit as st
import sqlite3
import pandas as pd
import datetime
import requests
import hashlib
import re

DB_PATH = "trading_journal.db"


def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def table_columns(conn, table_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row[1] for row in rows]


def add_column_if_missing(conn, table_name, column_name, column_def):
    cols = table_columns(conn, table_name)
    if column_name not in cols:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        marketing_opt_in INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        timestamp TEXT,
        category TEXT,
        request TEXT,
        outcome TEXT,
        notes TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date TEXT,
        ticker TEXT,
        side TEXT,
        quantity REAL,
        entry_price REAL,
        exit_price REAL,
        pnl REAL,
        strategy TEXT,
        notes TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        ticker TEXT,
        reason TEXT,
        date_added TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    add_column_if_missing(conn, "users", "email", "TEXT")
    add_column_if_missing(conn, "users", "marketing_opt_in", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "users", "created_at", "TEXT")

    conn.commit()
    conn.close()


def valid_email(email: str) -> bool:
    pattern = r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"
    return re.match(pattern, email) is not None


def create_user(email: str, username: str, password: str, marketing_opt_in: bool):
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO users (email, username, password_hash, marketing_opt_in, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                email.strip().lower(),
                username.strip().lower(),
                hash_password(password),
                1 if marketing_opt_in else 0,
                datetime.datetime.now().isoformat()
            )
        )
        conn.commit()
        return True, "Account created successfully."
    except sqlite3.IntegrityError as e:
        msg = str(e).lower()
        if "email" in msg:
            return False, "That email is already registered."
        if "username" in msg:
            return False, "That username already exists."
        return False, "Unable to create account."
    finally:
        conn.close()


def authenticate_user(login_value: str, password: str):
    conn = get_conn()
    value = login_value.strip().lower()
    row = conn.execute(
        """
        SELECT id, username, email
        FROM users
        WHERE (username = ? OR email = ?) AND password_hash = ?
        """,
        (value, value, hash_password(password))
    ).fetchone()
    conn.close()
    return row


def log_activity(user_id, category, request, outcome, notes=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO activity_log (user_id, timestamp, category, request, outcome, notes) VALUES (?,?,?,?,?,?)",
        (user_id, datetime.datetime.now().isoformat(), category, request, outcome, notes)
    )
    conn.commit()
    conn.close()


def log_trade(user_id, date, ticker, side, qty, entry, exitp, pnl, strategy, notes):
    conn = get_conn()
    conn.execute(
        "INSERT INTO trades (user_id, date, ticker, side, quantity, entry_price, exit_price, pnl, strategy, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (user_id, date, ticker, side, qty, entry, exitp, pnl, strategy, notes)
    )
    conn.commit()
    conn.close()


def add_watchlist(user_id, ticker, reason):
    conn = get_conn()
    conn.execute(
        "INSERT INTO watchlist (user_id, ticker, reason, date_added) VALUES (?,?,?,?)",
        (user_id, ticker, reason, datetime.date.today().isoformat())
    )
    conn.commit()
    conn.close()


def ask_openai_compatible(prompt, api_key, base_url, model, system_prompt):
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    }
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def provider_config(provider_name):
    configs = {
        "Groq": {
            "base_url": "https://api.groq.com/openai/v1",
            "model": "llama-3.3-70b-versatile"
        },
        "Perplexity": {
            "base_url": "https://api.perplexity.ai",
            "model": "sonar"
        },
        "OpenAI Compatible": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini"
        }
    }
    return configs[provider_name]


init_db()

st.set_page_config(page_title="Trading Journal", layout="wide")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "username" not in st.session_state:
    st.session_state.username = None
if "email" not in st.session_state:
    st.session_state.email = None
if "ai_history" not in st.session_state:
    st.session_state.ai_history = []
if "user_api_key" not in st.session_state:
    st.session_state.user_api_key = ""

st.title("📈 Trading Journal")

if not st.session_state.logged_in:
    login_tab, signup_tab = st.tabs(["Login", "Sign Up"])

    with login_tab:
        st.subheader("Login")
        with st.form("login_form"):
            login_value = st.text_input("Email or Username")
            login_pass = st.text_input("Password", type="password")
            login_submit = st.form_submit_button("Login")
            if login_submit:
                row = authenticate_user(login_value, login_pass)
                if row:
                    st.session_state.logged_in = True
                    st.session_state.user_id = row[0]
                    st.session_state.username = row[1]
                    st.session_state.email = row[2]
                    st.success(f"Welcome back, {row[1]}!")
                    st.rerun()
                else:
                    st.error("Invalid email/username or password.")

    with signup_tab:
        st.subheader("Create Account")
        with st.form("signup_form"):
            new_email = st.text_input("Email")
            new_user = st.text_input("Choose a username")
            new_pass = st.text_input("Choose a password", type="password")
            confirm_pass = st.text_input("Confirm password", type="password")
            marketing_opt_in = st.checkbox("Email me product updates and trading journal tips")
            create_submit = st.form_submit_button("Create account")

            if create_submit:
                if not valid_email(new_email.strip()):
                    st.error("Please enter a valid email address.")
                elif len(new_user.strip()) < 3:
                    st.error("Username must be at least 3 characters.")
                elif len(new_pass) < 6:
                    st.error("Password must be at least 6 characters.")
                elif new_pass != confirm_pass:
                    st.error("Passwords do not match.")
                else:
                    ok, msg = create_user(new_email, new_user, new_pass, marketing_opt_in)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

    st.stop()

st.sidebar.success(f"Logged in as {st.session_state.username}")
st.sidebar.caption(st.session_state.email if st.session_state.email else "")

if st.sidebar.button("Log out"):
    st.session_state.logged_in = False
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.email = None
    st.session_state.ai_history = []
    st.session_state.user_api_key = ""
    st.rerun()

main_tab, trade_tab, watch_tab, analytics_tab, ai_tab = st.tabs([
    "Activity Log", "Trades", "Watchlist", "Analytics", "AI Assistant"
])

with main_tab:
    st.subheader("Log Research / Chat Activity")
    with st.form("activity_form", clear_on_submit=True):
        category = st.selectbox("Category", ["App Research", "Strategy", "News", "Question", "Other"])
        request_text = st.text_input("What did you ask / work on?")
        outcome = st.text_area("Outcome / Answer summary")
        notes = st.text_area("Notes")
        if st.form_submit_button("Save Entry"):
            log_activity(st.session_state.user_id, category, request_text, outcome, notes)
            st.success("Logged!")

    conn = get_conn()
    df = pd.read_sql(
        "SELECT timestamp, category, request, outcome, notes FROM activity_log WHERE user_id = ? ORDER BY id DESC",
        conn,
        params=(st.session_state.user_id,)
    )
    conn.close()
    st.dataframe(df, use_container_width=True)

with trade_tab:
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
            log_trade(st.session_state.user_id, str(date), ticker.upper(), side, qty, entry, exitp, pnl, strategy, notes)
            st.success(f"Trade saved. P&L: ${pnl:,.2f}")

    conn = get_conn()
    df_trades = pd.read_sql(
        "SELECT date, ticker, side, quantity, entry_price, exit_price, pnl, strategy, notes FROM trades WHERE user_id = ? ORDER BY id DESC",
        conn,
        params=(st.session_state.user_id,)
    )
    conn.close()
    st.dataframe(df_trades, use_container_width=True)

with watch_tab:
    st.subheader("Watchlist")
    with st.form("watch_form", clear_on_submit=True):
        wt = st.text_input("Ticker")
        wr = st.text_input("Reason")
        if st.form_submit_button("Add to Watchlist"):
            add_watchlist(st.session_state.user_id, wt.upper(), wr)
            st.success("Added!")
    conn = get_conn()
    df_watch = pd.read_sql(
        "SELECT ticker, reason, date_added FROM watchlist WHERE user_id = ? ORDER BY id DESC",
        conn,
        params=(st.session_state.user_id,)
    )
    conn.close()
    st.dataframe(df_watch, use_container_width=True)

with analytics_tab:
    st.subheader("Performance Analytics")
    conn = get_conn()
    df_trades = pd.read_sql(
        "SELECT ticker, pnl FROM trades WHERE user_id = ?",
        conn,
        params=(st.session_state.user_id,)
    )
    conn.close()
    if not df_trades.empty:
        total_pnl = df_trades["pnl"].sum()
        win_rate = (df_trades["pnl"] > 0).mean() * 100
        st.metric("Total P&L", f"${total_pnl:,.2f}")
        st.metric("Win Rate", f"{win_rate:.1f}%")
        st.bar_chart(df_trades.groupby("ticker")["pnl"].sum())
    else:
        st.info("Log some trades to see analytics.")

with ai_tab:
    st.subheader("AI Assistant")
    st.caption("Each user can bring their own AI API key. Your journal stays private to your login.")

    provider = st.selectbox("AI Provider", ["Groq", "Perplexity", "OpenAI Compatible"])
    cfg = provider_config(provider)
    base_url = st.text_input("Base URL", value=cfg["base_url"])
    model = st.text_input("Model", value=cfg["model"])
    system_prompt = st.text_area(
        "System prompt",
        value="You are a trading journal assistant. Help summarize notes, review trades, and answer market research questions clearly."
    )
    api_key_input = st.text_input("Your API key", type="password", value=st.session_state.user_api_key)
    st.session_state.user_api_key = api_key_input

    if not st.session_state.user_api_key:
        st.info("Enter your own API key to use the assistant.")
    else:
        for msg in st.session_state.ai_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_input = st.chat_input("Ask your AI assistant about trades, setups, or market news...")
        if user_input:
            st.session_state.ai_history.append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    try:
                        answer = ask_openai_compatible(
                            user_input,
                            st.session_state.user_api_key,
                            base_url,
                            model,
                            system_prompt
                        )
                        st.markdown(answer)
                        st.session_state.ai_history.append({"role": "assistant", "content": answer})
                        log_activity(
                            st.session_state.user_id,
                            f"AI Chat ({provider})",
                            user_input,
                            answer[:500],
                            "Auto-logged from AI Assistant tab"
                        )
                    except Exception as e:
                        st.error(f"API error: {e}")
