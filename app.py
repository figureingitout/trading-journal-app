import streamlit as st
import pandas as pd
import datetime
import requests
import re
import calendar
import yfinance as yf
import plotly.graph_objects as go
from supabase import create_client

st.set_page_config(page_title="Trading Journal", layout="wide")

supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"]
)


def valid_email(email: str) -> bool:
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return re.match(pattern, email.strip()) is not None


def compute_percent_gain(side, entry_price, exit_price):
    if entry_price in (0, None):
        return 0.0
    try:
        if side == "Long":
            return ((exit_price - entry_price) / entry_price) * 100
        return ((entry_price - exit_price) / entry_price) * 100
    except Exception:
        return 0.0


def ensure_session_state():
    defaults = {
        "logged_in": False,
        "user_id": None,
        "username": None,
        "email": None,
        "access_token": None,
        "refresh_token": None,
        "ai_history": [],
        "user_api_key": "",
        "refresh_market": False,
        "benchmark_mode": "Futures"
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def sync_supabase_session():
    if st.session_state.access_token and st.session_state.refresh_token:
        try:
            supabase.auth.set_session(
                st.session_state.access_token,
                st.session_state.refresh_token
            )
            user_resp = supabase.auth.get_user()
            user = user_resp.user
            if user:
                st.session_state.logged_in = True
                st.session_state.user_id = user.id
                st.session_state.email = getattr(user, "email", "")
                username = ""
                meta = getattr(user, "user_metadata", {}) or {}
                if isinstance(meta, dict):
                    username = meta.get("username", "")
                st.session_state.username = username or st.session_state.email or "User"
                return
        except Exception:
            pass

    st.session_state.logged_in = False
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.email = None


def sign_up_user(email: str, username: str, password: str):
    response = supabase.auth.sign_up({
        "email": email.strip().lower(),
        "password": password,
        "options": {
            "data": {
                "username": username.strip()
            }
        }
    })
    return response


def sign_in_user(login_value: str, password: str):
    response = supabase.auth.sign_in_with_password({
        "email": login_value.strip().lower(),
        "password": password
    })
    return response


def sign_out_user():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    st.session_state.logged_in = False
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.email = None
    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.session_state.ai_history = []
    st.session_state.user_api_key = ""
    st.session_state.refresh_market = False


def save_profile_if_needed(user_id: str, email: str, username: str):
    try:
        existing = supabase.table("profiles").select("id").eq("id", user_id).execute()
        if not existing.data:
            supabase.table("profiles").insert({
                "id": user_id,
                "email": email,
                "full_name": username
            }).execute()
    except Exception:
        pass


def add_strategy(user_id, name, market_type, setup_type, time_of_day, market_conditions,
                 entry_criteria, exit_criteria, risk_rules, checklist, notes):
    supabase.table("strategies").insert({
        "user_id": user_id,
        "name": name,
        "market_type": market_type,
        "setup_type": setup_type,
        "time_of_day": time_of_day,
        "market_conditions": market_conditions,
        "entry_criteria": entry_criteria,
        "exit_criteria": exit_criteria,
        "risk_rules": risk_rules,
        "checklist": checklist,
        "notes": notes
    }).execute()


def get_strategies_df(user_id):
    response = (
        supabase.table("strategies")
        .select("id,name,market_type,setup_type,time_of_day,market_conditions,entry_criteria,exit_criteria,risk_rules,checklist,notes,created_at")
        .eq("user_id", user_id)
        .order("id", desc=True)
        .execute()
    )
    return pd.DataFrame(response.data if response.data else [])


def delete_strategy(strategy_id):
    (
        supabase.table("strategies")
        .delete()
        .eq("id", strategy_id)
        .execute()
    )


def log_trade(user_id, date, entry_time, exit_time, ticker, side, qty, entry, exitp, strategy, followed_plan, notes):
    pnl = (exitp - entry) * qty if side == "Long" else (entry - exitp) * qty
    percent_gain = compute_percent_gain(side, entry, exitp)

    supabase.table("trades").insert({
        "user_id": user_id,
        "trade_date": str(date),
        "entry_time": entry_time,
        "exit_time": exit_time,
        "symbol": ticker,
        "asset_type": "",
        "side": side.lower(),
        "quantity": qty,
        "entry_price": entry,
        "exit_price": exitp,
        "pnl": pnl,
        "percent_gain": percent_gain,
        "followed_plan": followed_plan,
        "notes": notes
    }).execute()

    return pnl, percent_gain


def get_trades_df(user_id):
    response = (
        supabase.table("trades")
        .select("id,trade_date,entry_time,exit_time,symbol,side,quantity,entry_price,exit_price,pnl,percent_gain,followed_plan,notes")
        .eq("user_id", user_id)
        .order("trade_date", desc=True)
        .order("entry_time", desc=True)
        .execute()
    )
    df = pd.DataFrame(response.data if response.data else [])
    if not df.empty:
        df = df.rename(columns={
            "trade_date": "date",
            "symbol": "ticker"
        })
        df["side"] = df["side"].fillna("").str.title()
    return df


def delete_trade(trade_id):
    (
        supabase.table("trades")
        .delete()
        .eq("id", trade_id)
        .execute()
    )


def add_watchlist(user_id, ticker, reason):
    supabase.table("watchlist").insert({
        "user_id": user_id,
        "symbol": ticker,
        "reason": reason
    }).execute()


def get_watchlist_df(user_id):
    response = (
        supabase.table("watchlist")
        .select("symbol,reason,date_added")
        .eq("user_id", user_id)
        .order("id", desc=True)
        .execute()
    )
    df = pd.DataFrame(response.data if response.data else [])
    if not df.empty:
        df = df.rename(columns={"symbol": "ticker"})
    return df


@st.cache_data(ttl=30, show_spinner=False)
def fetch_quotes(symbols):
    results = []
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2d", interval="1d", auto_adjust=False)

            if hist is not None and len(hist) >= 2:
                current_price = float(hist["Close"].iloc[-1])
                previous_close = float(hist["Close"].iloc[-2])
            elif hist is not None and len(hist) == 1:
                current_price = float(hist["Close"].iloc[-1])
                previous_close = current_price
            else:
                current_price = None
                previous_close = None

            if current_price is not None and previous_close not in (None, 0):
                change = current_price - previous_close
                change_pct = (change / previous_close) * 100
            else:
                change = None
                change_pct = None

            results.append({
                "symbol": symbol,
                "price": current_price,
                "change": change,
                "change_pct": change_pct
            })
        except Exception:
            results.append({
                "symbol": symbol,
                "price": None,
                "change": None,
                "change_pct": None
            })
    return results


@st.cache_data(ttl=30, show_spinner=False)
def fetch_intraday_with_sma(symbol, period="10d", interval="30m"):
    try:
        hist = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
        if hist is None or hist.empty:
            return pd.DataFrame()
        df = hist[["Close"]].copy()
        df["SMA20"] = df["Close"].rolling(window=20).mean()
        df["SMA50"] = df["Close"].rolling(window=50).mean()
        df["SMA200"] = df["Close"].rolling(window=200).mean()
        return df
    except Exception:
        return pd.DataFrame()


def render_quote_cards(title, quote_list):
    st.markdown(f"### {title}")
    if not quote_list:
        st.info("No symbols available.")
        return

    cols = st.columns(len(quote_list))
    for col, q in zip(cols, quote_list):
        with col:
            if q["price"] is None:
                st.metric(q["symbol"], "N/A", "Unavailable")
            else:
                delta_text = f"{q['change']:+.2f} ({q['change_pct']:+.2f}%)"
                st.metric(
                    q["symbol"],
                    f"{q['price']:.2f}",
                    delta_text
                )


def render_intraday_chart(symbol, df):
    if df.empty:
        st.info(f"No intraday data available for {symbol}.")
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index,
        y=df["Close"],
        mode="lines",
        name=f"{symbol} Price",
        line=dict(color="white")
    ))

    if df["SMA20"].notna().any():
        fig.add_trace(go.Scatter(
            x=df.index,
            y=df["SMA20"],
            mode="lines",
            name="SMA 20",
            line=dict(color="yellow")
        ))
    if df["SMA50"].notna().any():
        fig.add_trace(go.Scatter(
            x=df.index,
            y=df["SMA50"],
            mode="lines",
            name="SMA 50",
            line=dict(color="cyan")
        ))
    if df["SMA200"].notna().any():
        fig.add_trace(go.Scatter(
            x=df.index,
            y=df["SMA200"],
            mode="lines",
            name="SMA 200",
            line=dict(color="magenta")
        ))

    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template="plotly_dark",
        height=250,
        title=f"{symbol} – 10D / 30m with SMA 20, 50, 200"
    )
    st.plotly_chart(fig, use_container_width=True)


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
                    "followed_plan": True,
                    "notes": notes_val,
                })
        except Exception:
            continue

    return pd.DataFrame(rows)


def import_trades(user_id, df_norm):
    for _, r in df_norm.iterrows():
        supabase.table("trades").insert({
            "user_id": user_id,
            "trade_date": r["date"],
            "entry_time": r["entry_time"],
            "exit_time": r["exit_time"],
            "symbol": r["ticker"],
            "asset_type": "",
            "side": r["side"].lower(),
            "quantity": float(r["quantity"]),
            "entry_price": float(r["entry_price"]),
            "exit_price": float(r["exit_price"]),
            "pnl": float(r["pnl"]),
            "percent_gain": float(r["percent_gain"]),
            "followed_plan": bool(r["followed_plan"]),
            "notes": r["notes"]
        }).execute()


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


def build_performance_vs_market_chart(daily_df, mode="Futures"):
    # Your cumulative performance (%)
    perf = daily_df.copy()
    perf = perf.sort_values("date")
    base = perf["daily_pnl"].iloc[0] if len(perf) > 0 else 0
    perf["cum_pnl"] = perf["daily_pnl"].cumsum()
    # Treat starting point as 0% and compute percent change vs initial equity proxy
    # Here we approximate by cumulative P&L relative to initial equity proxy:
    # If you later want true equity curves, we can wire in account size history.
    perf["your_return_pct"] = (perf["cum_pnl"] / max(abs(perf["daily_pnl"]).sum(), 1)) * 100

    # Market benchmarks over the same dates
    if mode == "Futures":
        symbols = ["MES=F", "MNQ=F", "MYM=F"]
        labels = ["MES", "MNQ", "MYM"]
    else:
        symbols = ["SPY", "QQQ", "DIA"]
        labels = ["SPY", "QQQ", "DIA"]

    index_returns = {}
    for sym, label in zip(symbols, labels):
        try:
            hist = yf.Ticker(sym).history(period="3mo", interval="1d", auto_adjust=False)
            if hist is None or hist.empty:
                continue
            df = hist[["Close"]].copy()
            df = df.sort_index()
            df["return_pct"] = (df["Close"] / df["Close"].iloc[0] - 1) * 100
            index_returns[label] = df
        except Exception:
            continue

    if not index_returns:
        st.info("No market data available for benchmark comparison.")
        return

    # Align on dates in perf
    fig = go.Figure()

    if not perf.empty:
        fig.add_trace(go.Scatter(
            x=perf["date"],
            y=perf["your_return_pct"],
            mode="lines",
            name="Your Performance",
            line=dict(color="white", width=2)
        ))

    for label, df_idx in index_returns.items():
        # Align to perf date range
        df_idx = df_idx.copy()
        df_idx = df_idx.loc[df_idx.index.isin(perf["date"])] if not perf.empty else df_idx
        if df_idx.empty:
            continue
        fig.add_trace(go.Scatter(
            x=df_idx.index,
            y=df_idx["return_pct"],
            mode="lines",
            name=label,
            line=dict(width=1)
        ))

    fig.update_layout(
        title=f"Your Performance vs {mode} Benchmarks (Cumulative %)",
        margin=dict(l=10, r=10, t=40, b=10),
        template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=300
    )
    st.plotly_chart(fig, use_container_width=True)


# ----------------- APP FLOW -----------------

ensure_session_state()
sync_supabase_session()

st.title("📈 Trading Journal")

if not st.session_state.logged_in:
    login_tab, signup_tab = st.tabs(["Login", "Sign Up"])

    with login_tab:
        st.subheader("Login")
        with st.form("login_form"):
            login_email = st.text_input("Email")
            login_pass = st.text_input("Password", type="password")
            login_submit = st.form_submit_button("Login")
            if login_submit:
                try:
                    resp = sign_in_user(login_email, login_pass)
                    session = resp.session
                    user = resp.user

                    st.session_state.access_token = session.access_token
                    st.session_state.refresh_token = session.refresh_token
                    st.session_state.logged_in = True
                    st.session_state.user_id = user.id
                    st.session_state.email = user.email

                    meta = getattr(user, "user_metadata", {}) or {}
                    username = meta.get("username", "") if isinstance(meta, dict) else ""
                    st.session_state.username = username or user.email

                    save_profile_if_needed(user.id, user.email, st.session_state.username)
                    st.success(f"Welcome back, {st.session_state.username}!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")

    with signup_tab:
        st.subheader("Create Account")
        with st.form("signup_form"):
            new_email = st.text_input("Email")
            new_user = st.text_input("Choose a username")
            new_pass = st.text_input("Choose a password", type="password")
            confirm_pass = st.text_input("Confirm password", type="password")
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
                    try:
                        resp = sign_up_user(new_email, new_user, new_pass)
                        user = resp.user
                        session = resp.session

                        if user:
                            save_profile_if_needed(user.id, new_email.strip().lower(), new_user.strip())

                        if session:
                            st.session_state.access_token = session.access_token
                            st.session_state.refresh_token = session.refresh_token
                            st.session_state.logged_in = True
                            st.session_state.user_id = user.id
                            st.session_state.email = user.email
                            st.session_state.username = new_user.strip()
                            st.success("Account created successfully.")
                            st.rerun()
                        else:
                            st.success("Account created. Check your email to confirm your account before logging in.")
                    except Exception as e:
                        st.error(f"Sign up failed: {e}")

    st.stop()

st.sidebar.success(f"Logged in as {st.session_state.username}")
st.sidebar.caption(st.session_state.email if st.session_state.email else "")
account_size = st.sidebar.number_input("Account Size ($) for % calendar", min_value=100.0, value=25000.0, step=100.0)

if st.sidebar.button("Log out"):
    sign_out_user()
    st.rerun()

# Benchmark mode: Futures vs ETF
st.session_state.benchmark_mode = st.sidebar.radio("Benchmark Mode", ["Futures", "ETF"])

# Market overview controls
top_left, top_right = st.columns([3, 1])
with top_right:
    if st.button("Refresh Market Data"):
        # Clear cache and rerun for fresh quotes/charts
        fetch_quotes.clear()
        fetch_intraday_with_sma.clear()
        st.session_state.refresh_market = True
        st.rerun()

with top_left:
    st.subheader("Market Overview")

try:
    df_watch_for_top = get_watchlist_df(st.session_state.user_id)
except Exception:
    df_watch_for_top = pd.DataFrame()

if st.session_state.benchmark_mode == "Futures":
    market_symbols = ["MES=F", "MNQ=F", "MYM=F", "M2K=F", "^VIX"]
    market_labels = ["MES=F", "MNQ=F", "MYM=F", "M2K=F", "^VIX"]
else:
    market_symbols = ["SPY", "QQQ", "DIA", "IWM", "^VIX"]
    market_labels = ["SPY", "QQQ", "DIA", "IWM", "^VIX"]

market_quotes = fetch_quotes(market_symbols)

watch_symbols = []
if not df_watch_for_top.empty and "ticker" in df_watch_for_top.columns:
    watch_symbols = (
        df_watch_for_top["ticker"]
        .dropna()
        .astype(str)
        .str.upper()
        .drop_duplicates()
        .head(5)
        .tolist()
    )

watch_quotes = fetch_quotes(watch_symbols) if watch_symbols else []

render_quote_cards("Benchmarks", market_quotes)
if watch_quotes:
    render_quote_cards("Watchlist Movers", watch_quotes)
else:
    st.info("Add some watchlist symbols to show their price action here.")

# Separate charts per benchmark symbol
st.markdown("#### Benchmark Charts (10D / 30m with SMA 20, 50, 200)")
for sym, label in zip(market_symbols, market_labels):
    st.markdown(f"**{label}**")
    df_intraday = fetch_intraday_with_sma(sym, period="10d", interval="30m")
    render_intraday_chart(sym, df_intraday)

st.markdown("---")

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
                try:
                    add_strategy(
                        st.session_state.user_id, name, market_type, setup_type, time_of_day,
                        market_conditions, entry_criteria, exit_criteria, risk_rules, checklist, notes
                    )
                    st.success("Strategy saved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not save strategy: {e}")

    try:
        df_strat = get_strategies_df(st.session_state.user_id)
        if not df_strat.empty:
            display_cols = [
                "name", "market_type", "setup_type", "time_of_day", "market_conditions",
                "entry_criteria", "exit_criteria", "risk_rules", "checklist", "notes"
            ]
            st.subheader("Saved Strategies")
            st.dataframe(df_strat[display_cols], use_container_width=True)

            st.markdown("### Delete a Strategy")
            strategy_delete_options = {
                f"{row['name']} | {row.get('setup_type', '')} | {row.get('market_type', '')}": row["id"]
                for _, row in df_strat.iterrows()
            }
            strategy_to_delete_label = st.selectbox(
                "Choose a strategy to delete",
                [""] + list(strategy_delete_options.keys())
            )
            confirm_delete_strategy = st.checkbox("I understand this will permanently delete the selected strategy.")
            if st.button("Delete Selected Strategy", type="secondary"):
                if not strategy_to_delete_label:
                    st.warning("Pick a strategy first.")
                elif not confirm_delete_strategy:
                    st.warning("Please confirm deletion first.")
                else:
                    try:
                        delete_strategy(strategy_delete_options[strategy_to_delete_label])
                        st.success("Strategy deleted.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not delete strategy: {e}")
        else:
            st.info("No strategies saved yet.")
    except Exception as e:
        st.error(f"Could not load strategies: {e}")

with trade_tab:
    st.subheader("Log a Trade (Manual)")
    try:
        df_strategy_names = get_strategies_df(st.session_state.user_id)
        user_strategy_names = sorted(df_strategy_names["name"].dropna().tolist()) if not df_strategy_names.empty else []
    except Exception:
        user_strategy_names = []

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
            try:
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
                st.rerun()
            except Exception as e:
                st.error(f"Could not save trade: {e}")

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
                    try:
                        import_trades(st.session_state.user_id, df_norm)
                        st.success(f"Imported {len(df_norm)} trades.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Import failed: {e}")

    try:
        df_trades = get_trades_df(st.session_state.user_id)
        if not df_trades.empty:
            df_display = df_trades.copy()
            df_display["followed_plan"] = df_display["followed_plan"].map({True: "Yes", False: "No", 1: "Yes", 0: "No"})
            st.subheader("Your Trades")
            st.dataframe(df_display.drop(columns=["id"]), use_container_width=True)

            st.markdown("### Delete a Trade")
            trade_delete_options = {}
            for _, row in df_trades.iterrows():
                label = f"{row['date']} | {row['ticker']} | {row['side']} | P&L ${float(row['pnl']):,.2f}"
                trade_delete_options[label] = row["id"]

            trade_to_delete_label = st.selectbox(
                "Choose a trade to delete",
                [""] + list(trade_delete_options.keys())
            )
            confirm_delete_trade = st.checkbox("I understand this will permanently delete the selected trade.")
            if st.button("Delete Selected Trade", type="secondary"):
                if not trade_to_delete_label:
                    st.warning("Pick a trade first.")
                elif not confirm_delete_trade:
                    st.warning("Please confirm deletion first.")
                else:
                    try:
                        delete_trade(trade_delete_options[trade_to_delete_label])
                        st.success("Trade deleted.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not delete trade: {e}")
        else:
            st.subheader("Your Trades")
            st.info("No trades logged yet.")
    except Exception as e:
        st.error(f"Could not load trades: {e}")

with watch_tab:
    st.subheader("Watchlist")
    with st.form("watch_form", clear_on_submit=True):
        wt = st.text_input("Ticker")
        wr = st.text_input("Reason")
        if st.form_submit_button("Add to Watchlist"):
            try:
                add_watchlist(st.session_state.user_id, wt.upper(), wr)
                st.success("Added!")
                st.rerun()
            except Exception as e:
                st.error(f"Could not add to watchlist: {e}")

    try:
        df_watch = get_watchlist_df(st.session_state.user_id)
        st.dataframe(df_watch, use_container_width=True)
    except Exception as e:
        st.error(f"Could not load watchlist: {e}")

with analytics_tab:
    st.subheader("Performance Analytics")
    try:
        df_analytics = get_trades_df(st.session_state.user_id)
    except Exception as e:
        df_analytics = pd.DataFrame()
        st.error(f"Could not load analytics: {e}")

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

        st.subheader("Discipline Metrics")
        followed_pct = (df_analytics["followed_plan"].astype(str).isin(["True", "1"])).mean() * 100
        st.metric("Trades Following Plan", f"{followed_pct:.1f}%")
        st.write(f"Average % gain on winners: {avg_win_pct:+.2f}%")
        st.write(f"Average % gain on losers: {avg_loss_pct:+.2f}%")
    else:
        st.info("Log or import some trades to see analytics.")

with calendar_tab:
    st.subheader("Calendar View")
    try:
        df_cal = get_trades_df(st.session_state.user_id)
    except Exception as e:
        df_cal = pd.DataFrame()
        st.error(f"Could not load calendar data: {e}")

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

        st.subheader("Performance vs Market (Calendar Period)")
        # Use only days in selected month for comparison chart
        perf_month = daily[daily["date"].str.startswith(f"{selected_year:04d}-{selected_month:02d}")]
        if perf_month.empty:
            st.info("No trades in this month to compare against the market.")
        else:
            perf_month_sorted = perf_month.copy()
            perf_month_sorted["date"] = pd.to_datetime(perf_month_sorted["date"], errors="coerce")
            perf_month_sorted = perf_month_sorted.dropna(subset=["date"]).sort_values("date")
            build_performance_vs_market_chart(perf_month_sorted, mode=st.session_state.benchmark_mode)
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
