import streamlit as st
import sqlite3
import pandas as pd
import datetime
import requests
import hashlib
import re
import calendar

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
    CREATE TABLE IF NOT EXISTS strategies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        market_type TEXT,
        setup_type TEXT,
        time_of_day TEXT,
        market_conditions TEXT,
        entry_criteria TEXT,
        exit_criteria TEXT,
        risk_rules TEXT,
        checklist TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date TEXT,
        entry_time TEXT,
        exit_time TEXT,
        ticker TEXT,
        side TEXT,
        quantity REAL,
        entry_price REAL,
        exit_price REAL,
        pnl REAL,
        percent_gain REAL,
        strategy TEXT,
        followed_plan INTEGER DEFAULT 1,
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

    add_column_if_missing(conn, "trades", "entry_time", "TEXT")
    add_column_if_missing(conn, "trades", "exit_time", "TEXT")
    add_column_if_missing(conn, "trades", "percent_gain", "REAL")
    add_column_if_missing(conn, "trades", "followed_plan", "INTEGER DEFAULT 1")

    conn.commit()
    conn.close()


def valid_email(email: str) -> bool:
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return re.match(pattern, email.strip()) is not None


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


def compute_percent_gain(side, entry_price, exit_price):
    if entry_price in (0, None):
        return 0.0
    try:
        if side == "Long":
            return ((exit_price - entry_price) / entry_price) * 100
        else:
            return ((entry_price - exit_price) / entry_price) * 100
    except Exception:
        return 0.0


def add_strategy(user_id, name, market_type, setup_type, time_of_day, market_conditions,
                 entry_criteria, exit_criteria, risk_rules, checklist, notes):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO strategies (
            user_id, name, market_type, setup_type, time_of_day, market_conditions,
            entry_criteria, exit_criteria, risk_rules, checklist, notes, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id, name, market_type, setup_type, time_of_day, market_conditions,
            entry_criteria, exit_criteria, risk_rules, checklist, notes,
            datetime.datetime.now().isoformat()
        )
    )
    conn.commit()
    conn.close()


def log_trade(user_id, date, entry_time, exit_time, ticker, side, qty, entry, exitp, strategy, followed_plan, notes):
    pnl = (exitp - entry) * qty if side == "Long" else (entry - exitp) * qty
    percent_gain = compute_percent_gain(side, entry, exitp)

    conn = get_conn()
    conn.execute(
        """
        INSERT INTO trades (
            user_id, date, entry_time, exit_time, ticker, side, quantity,
            entry_price, exit_price, pnl, percent_gain, strategy, followed_plan, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id, date, entry_time, exit_time, ticker, side, qty,
            entry, exitp, pnl, percent_gain, strategy, 1 if followed_plan else 0, notes
        )
    )
    conn.commit()
    conn.close()
    return pnl, percent_gain


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


def normalize_broker_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    df = df_raw.copy()
    lower_cols = {c.lower(): c for c in df.columns}

    def pick(*candidates):
        for cand in candidates:
            if cand.lower() in lower_cols:
                return lower_cols[cand.lower()]
        return None

    date_col = pick("date", "time", "timestamp", "trade_date", "filled time", "execution time")
    entry_time_col = pick("entry_time", "time", "timestamp", "filled time", "execution time")
    exit_time_col = pick("exit_time", "close time")
    symbol_col = pick("symbol", "ticker", "instrument", "product", "asset", "market")
    side_col = pick("side", "buy_sell", "direction", "type", "action")
    qty_col = pick("quantity", "qty", "size", "amount", "contracts", "shares")
    entry_col = pick("entry_price", "price", "open_price", "avg_price", "fill_price", "buy_price")
    exit_col = pick("exit_price", "close_price", "sell_price", "exit", "closing_price")
    pnl_col = pick("pnl", "profit", "pl", "realized_pnl", "net_profit", "realized p&l")
    notes_col = pick("notes", "comment", "memo", "description")
    strategy_col = pick("strategy", "tag", "category", "label", "setup")

    rows = []
    for _, row in df.iterrows():
        try:
            dt = row[date_col] if date_col else datetime.date.today().isoformat()
            try:
                parsed_dt = pd.to_datetime(dt)
                date_str = parsed_dt.date().isoformat()
                time_str = parsed_dt.strftime("%H:%M")
            except Exception:
                date_str = str(dt)
                time_str = ""

            entry_time = time_str
            if entry_time_col and pd.notna(row[entry_time_col]):
                try:
                    entry_time = pd.to_datetime(row[entry_time_col]).strftime("%H:%M")
                except Exception:
                    entry_time = str(row[entry_time_col])

            exit_time = ""
            if exit_time_col and pd.notna(row[exit_time_col]):
                try:
                    exit_time = pd.to_datetime(row[exit_time_col]).strftime("%H:%M")
                except Exception:
                    exit_time = str(row[exit_time_col])

            ticker_val = str(row[symbol_col]).upper().strip() if symbol_col else ""
            side_raw = str(row[side_col]).strip().lower() if side_col else ""
            if "buy" in side_raw or "long" in side_raw:
                side_val = "Long"
            elif "sell" in side_raw or "short" in side_raw:
                side_val = "Short"
            else:
                side_val = "Long"

            qty_val = float(row[qty_col]) if qty_col and pd.notna(row[qty_col]) else 0.0
            entry_val = float(row[entry_col]) if entry_col and pd.notna(row[entry_col]) else 0.0
            exit_val = float(row[exit_col]) if exit_col and pd.notna(row[exit_col]) else entry_val

            if pnl_col and pd.notna(row[pnl_col]):
                pnl_val = float(row[pnl_col])
            else:
                pnl_val = (exit_val - entry_val) * qty_val if side_val == "Long" else (entry_val - exit_val) * qty_val

            percent_val = compute_percent_gain(side_val, entry_val, exit_val)
            strategy_val = str(row[strategy_col]).strip() if strategy_col and pd.notna(row[strategy_col]) else ""
            notes_val = str(row[notes_col]).strip() if notes_col and pd.notna(row[notes_col]) else ""

            if ticker_val:
                rows.append({
                    "date": date_str,
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                    "ticker": ticker_val,
                    "side": side_val,
                    "quantity": qty_val,
                    "entry_price": entry_val,
                    "exit_price": exit_val,
                    "pnl": pnl_val,
                    "percent_gain": percent_val,
                    "strategy": strategy_val,
                    "followed_plan": 1,
                    "notes": notes_val,
                })
        except Exception:
            continue

    return pd.DataFrame(rows)


def render_calendar(day_df, selected_year, selected_month):
    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdayscalendar(selected_year, selected_month)

    st.markdown("""
    <style>
    .calendar-grid {display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin-top:10px;}
    .calendar-head {font-weight:700;text-align:center;padding:6px 0;}
    .day-tile {
        border-radius:12px;
        padding:10px;
        min-height:110px;
        color:white;
        font-size:0.85rem;
        display:flex;
        flex-direction:column;
        justify-content:space-between;
    }
    .day-empty {
        background:#f0f0f0;
        border-radius:12px;
        min-height:110px;
    }
    .day-num {font-weight:700;font-size:0.95rem;}
    .small {font-size:0.75rem;opacity:0.95;}
    </style>
    """, unsafe_allow_html=True)

    for name in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]:
        pass

    header_html = '<div class="calendar-grid">' + "".join(
        [f'<div class="calendar-head">{d}</div>' for d in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]]
    )

    tiles = ""
    for week in weeks:
        for day in week:
            if day == 0:
                tiles += '<div class="day-empty"></div>'
            else:
                date_key = f"{selected_year:04d}-{selected_month:02d}-{day:02d}"
                row = day_df[day_df["date"] == date_key]
                if not row.empty:
                    pnl = float(row["daily_pnl"].iloc[0])
                    pct = float(row["daily_pct"].iloc[0])
                    followed_ratio = float(row["follow_ratio"].iloc[0])

                    bg = "#1f7a1f" if pnl > 0 else "#b42318" if pnl < 0 else "#6b7280"
                    border = "#22c55e" if followed_ratio >= 1 else "#ef4444" if followed_ratio == 0 else "#f59e0b"
                    plan_text = "Plan ✓" if followed_ratio >= 1 else "Plan ✗" if followed_ratio == 0 else "Plan Mixed"

                    tiles += f"""
                    <div class="day-tile" style="background:{bg}; border:4px solid {border};">
                        <div class="day-num">{day}</div>
                        <div>
                            <div><strong>${pnl:,.2f}</strong></div>
                            <div class="small">{pct:+.2f}%</div>
                        </div>
                        <div class="small">{plan_text}</div>
                    </div>
                    """
                else:
                    tiles += f"""
                    <div class="day-tile" style="background:#9ca3af; border:4px solid #d1d5db;">
                        <div class="day-num">{day}</div>
                        <div class="small">No trades</div>
                        <div class="small">-</div>
                    </div>
                    """

    footer = "</div>"
    st.markdown(header_html + tiles + footer, unsafe_allow_html=True)


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
account_size = st.sidebar.number_input("Account Size ($) for % calendar", min_value=100.0, value=25000.0, step=100.0)

if st.sidebar.button("Log out"):
    st.session_state.logged_in = False
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.email = None
    st.session_state.ai_history = []
    st.session_state.user_api_key = ""
    st.rerun()

strategy_tab, trade_tab, watch_tab, analytics_tab, calendar_tab, ai_tab = st.tabs([
    "My Strategy", "Trades", "Watchlist", "Analytics", "Calendar", "AI Assistant"
])

with strategy_tab:
    st.subheader("My Strategy")
    with st.form("strategy_form", clear_on_submit=True):
        name = st.text_input("Strategy Name")
        col1, col2, col3 = st.columns(3)
        market_type = col1.selectbox("Market Type", ["Stocks", "Futures", "Crypto", "Forex", "Options", "Other"])
        setup_type = col2.text_input("Setup Type")
        time_of_day = col3.text_input("Best Time of Day")
        market_conditions = st.text_area("Market Conditions")
        entry_criteria = st.text_area("Entry Criteria")
        exit_criteria = st.text_area("Exit Criteria")
        risk_rules = st.text_area("Risk Rules")
        checklist = st.text_area("Checklist")
        notes = st.text_area("Extra Notes")
        if st.form_submit_button("Save Strategy"):
            if not name.strip():
                st.error("Strategy name is required.")
            else:
                add_strategy(
                    st.session_state.user_id, name, market_type, setup_type, time_of_day,
                    market_conditions, entry_criteria, exit_criteria, risk_rules, checklist, notes
                )
                st.success("Strategy saved.")

    conn = get_conn()
    df_strat = pd.read_sql(
        """
        SELECT name, market_type, setup_type, time_of_day, market_conditions,
               entry_criteria, exit_criteria, risk_rules, checklist, notes
        FROM strategies
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        conn,
        params=(st.session_state.user_id,)
    )
    conn.close()
    st.subheader("Saved Strategies")
    st.dataframe(df_strat, use_container_width=True)

with trade_tab:
    st.subheader("Log a Trade (Manual)")
    conn = get_conn()
    user_strategy_names = pd.read_sql(
        "SELECT name FROM strategies WHERE user_id = ? ORDER BY name",
        conn,
        params=(st.session_state.user_id,)
    )["name"].tolist()
    conn.close()

    strategy_options = [""] + user_strategy_names if user_strategy_names else [""]

    with st.form("trade_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        date = col1.date_input("Date", datetime.date.today())
        entry_time = col2.time_input("Entry Time", value=datetime.datetime.now().time())
        exit_time = col3.time_input("Exit Time", value=datetime.datetime.now().time())

        col4, col5, col6 = st.columns(3)
        ticker = col4.text_input("Ticker / Instrument")
        side = col5.selectbox("Side", ["Long", "Short"])
        qty = col6.number_input("Quantity", min_value=0.0)

        col7, col8 = st.columns(2)
        entry = col7.number_input("Entry Price", min_value=0.0)
        exitp = col8.number_input("Exit Price", min_value=0.0)

        strategy = st.selectbox("Linked Strategy", strategy_options)
        followed_plan = st.checkbox("I followed my plan on this trade", value=True)
        notes = st.text_area("Trade Notes")

        if st.form_submit_button("Save Trade"):
            pnl, pct = log_trade(
                st.session_state.user_id,
                str(date),
                entry_time.strftime("%H:%M"),
                exit_time.strftime("%H:%M"),
                ticker.upper(),
                side,
                qty,
                entry,
                exitp,
                strategy,
                followed_plan,
                notes
            )
            st.success(f"Trade saved. P&L: ${pnl:,.2f} | Return: {pct:+.2f}%")

    st.markdown("---")
    st.subheader("Bulk Import Trades from Broker (CSV or Excel)")
    uploaded_file = st.file_uploader(
        "Upload trade history",
        type=["csv", "xls", "xlsx"],
        help="Upload exported order/trade history from your broker or exchange."
    )

    if uploaded_file is not None:
        ext = uploaded_file.name.split(".")[-1].lower()
        try:
            if ext == "csv":
                df_raw = pd.read_csv(uploaded_file)
            else:
                df_raw = pd.read_excel(uploaded_file)
        except Exception as e:
            df_raw = None
            st.error(f"Could not read file: {e}")

        if df_raw is not None:
            st.write("Uploaded file preview:")
            st.dataframe(df_raw.head(), use_container_width=True)

            df_norm = normalize_broker_df(df_raw)
            if df_norm.empty:
                st.warning("No trades could be mapped from this file.")
            else:
                st.write("Mapped trades preview:")
                st.dataframe(df_norm.head(), use_container_width=True)

                if st.button("Import all mapped trades"):
                    for _, r in df_norm.iterrows():
                        conn = get_conn()
                        conn.execute(
                            """
                            INSERT INTO trades (
                                user_id, date, entry_time, exit_time, ticker, side, quantity,
                                entry_price, exit_price, pnl, percent_gain, strategy, followed_plan, notes
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                st.session_state.user_id,
                                r["date"],
                                r["entry_time"],
                                r["exit_time"],
                                r["ticker"],
                                r["side"],
                                float(r["quantity"]),
                                float(r["entry_price"]),
                                float(r["exit_price"]),
                                float(r["pnl"]),
                                float(r["percent_gain"]),
                                r["strategy"],
                                int(r["followed_plan"]),
                                r["notes"],
                            )
                        )
                        conn.commit()
                        conn.close()
                    st.success(f"Imported {len(df_norm)} trades.")
                    st.rerun()

    conn = get_conn()
    df_trades = pd.read_sql(
        """
        SELECT date, entry_time, exit_time, ticker, side, quantity,
               entry_price, exit_price, pnl, percent_gain, strategy, followed_plan, notes
        FROM trades
        WHERE user_id = ?
        ORDER BY date DESC, entry_time DESC
        """,
        conn,
        params=(st.session_state.user_id,)
    )
    conn.close()

    if not df_trades.empty:
        df_trades["followed_plan"] = df_trades["followed_plan"].map({1: "Yes", 0: "No"})
    st.subheader("Your Trades")
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
    df_analytics = pd.read_sql(
        """
        SELECT date, entry_time, ticker, side, pnl, percent_gain, strategy, followed_plan
        FROM trades
        WHERE user_id = ?
        ORDER BY date, entry_time
        """,
        conn,
        params=(st.session_state.user_id,)
    )
    conn.close()

    if not df_analytics.empty:
        total_pnl = df_analytics["pnl"].sum()
        win_rate = (df_analytics["pnl"] > 0).mean() * 100
        avg_pct = df_analytics["percent_gain"].mean()
        avg_win_pct = df_analytics[df_analytics["pnl"] > 0]["percent_gain"].mean() if not df_analytics[df_analytics["pnl"] > 0].empty else 0
        avg_loss_pct = df_analytics[df_analytics["pnl"] < 0]["percent_gain"].mean() if not df_analytics[df_analytics["pnl"] < 0].empty else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total P&L", f"${total_pnl:,.2f}")
        c2.metric("Win Rate", f"{win_rate:.1f}%")
        c3.metric("Avg % / Trade", f"{avg_pct:+.2f}%")
        c4.metric("Largest Trade", f"${df_analytics['pnl'].max():,.2f}")

        df_analytics["date"] = pd.to_datetime(df_analytics["date"], errors="coerce")
        daily = df_analytics.groupby("date", as_index=False)["pnl"].sum().sort_values("date")
        daily["running_total"] = daily["pnl"].cumsum()

        st.subheader("Running Total P&L")
        st.line_chart(daily.set_index("date")["running_total"])

        df_analytics["hour"] = pd.to_datetime(df_analytics["entry_time"], format="%H:%M", errors="coerce").dt.hour
        hourly = df_analytics.groupby("hour", dropna=True)["pnl"].sum()
        if not hourly.empty:
            st.subheader("P&L by Hour of Day")
            st.bar_chart(hourly)

        if df_analytics["strategy"].fillna("").ne("").any():
            st.subheader("Performance by Strategy")
            strat_stats = df_analytics.groupby("strategy", dropna=False).agg(
                trades=("pnl", "count"),
                total_pnl=("pnl", "sum"),
                avg_pct=("percent_gain", "mean")
            ).reset_index()
            st.dataframe(strat_stats, use_container_width=True)

        st.subheader("Discipline Metrics")
        followed_pct = (df_analytics["followed_plan"] == 1).mean() * 100
        st.metric("Trades Following Plan", f"{followed_pct:.1f}%")
        st.write(f"Average % gain on winners: {avg_win_pct:+.2f}%")
        st.write(f"Average % gain on losers: {avg_loss_pct:+.2f}%")
    else:
        st.info("Log or import some trades to see analytics.")

with calendar_tab:
    st.subheader("Calendar View")
    conn = get_conn()
    df_cal = pd.read_sql(
        """
        SELECT date, pnl, percent_gain, followed_plan
        FROM trades
        WHERE user_id = ?
        """,
        conn,
        params=(st.session_state.user_id,)
    )
    conn.close()

    today = datetime.date.today()
    c1, c2 = st.columns(2)
    selected_year = c1.selectbox("Year", list(range(today.year - 2, today.year + 3)), index=2)
    selected_month = c2.selectbox("Month", list(range(1, 13)), index=today.month - 1)

    if not df_cal.empty:
        df_cal["date"] = pd.to_datetime(df_cal["date"], errors="coerce")
        df_cal = df_cal.dropna(subset=["date"])
        df_cal["date_str"] = df_cal["date"].dt.strftime("%Y-%m-%d")
        daily = df_cal.groupby("date_str").agg(
            daily_pnl=("pnl", "sum"),
            follow_ratio=("followed_plan", "mean")
        ).reset_index().rename(columns={"date_str": "date"})
        daily["daily_pct"] = (daily["daily_pnl"] / account_size) * 100
        render_calendar(daily, selected_year, selected_month)

        st.subheader("Daily Summary")
        month_df = daily[daily["date"].str.startswith(f"{selected_year:04d}-{selected_month:02d}")]
        st.dataframe(month_df, use_container_width=True)
    else:
        st.info("No trades available for calendar view yet.")

with ai_tab:
    st.subheader("AI Assistant")
    st.caption("Use your own API key. The assistant is tuned for strategy, time-of-day, discipline, and performance review.")

    provider = st.selectbox("AI Provider", ["Groq", "Perplexity", "OpenAI Compatible"])
    cfg = provider_config(provider)
    base_url = st.text_input("Base URL", value=cfg["base_url"])
    model = st.text_input("Model", value=cfg["model"])
    system_prompt = st.text_area(
        "System prompt",
        value=(
            "You are a trading journal assistant. Analyze trades by time of day, percent gain, "
            "dollar P&L, strategy, and whether the trader followed the plan. Help identify patterns, "
            "mistakes, strengths, and discipline issues."
        )
    )
    api_key_input = st.text_input("Your API key", type="password", value=st.session_state.user_api_key)
    st.session_state.user_api_key = api_key_input

    if not st.session_state.user_api_key:
        st.info("Enter your own API key to use the assistant.")
    else:
        for msg in st.session_state.ai_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_input = st.chat_input("Ask your AI assistant about strategy, discipline, or performance...")
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
                    except Exception as e:
                        st.error(f"API error: {e}")
