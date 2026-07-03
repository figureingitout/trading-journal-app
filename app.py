import os
import math
import calendar
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import create_client, Client

# =========================
# Page config
# =========================
st.set_page_config(
    page_title="Trading Journal",
    page_icon="📈",
    layout="wide"
)

# =========================
# Styling
# =========================
st.markdown("""
<style>
.block-container {
    padding-top: 0.75rem;
    padding-bottom: 2rem;
    max-width: 96rem;
}

/* Header */
.app-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 0.75rem;
}
.app-header-left h1 {
    margin: 0;
}
.app-header-right {
    text-align: right;
    font-size: 0.9rem;
    color: #9ca3af;
}
.app-header-right strong {
    color: #e5e7eb;
}
.app-header-status {
    font-size: 0.8rem;
    color: #9ca3af;
}

/* KPI metrics */
div[data-testid="stMetric"] {
    border: 1px solid rgba(148,163,184,0.35);
    border-radius: 12px;
    padding: 10px 14px;
    background: rgba(15,23,42,0.4);
}

/* Calendar */
.calendar-header {
    text-align: center;
    font-weight: 700;
    padding: 8px 0;
    border-bottom: 1px solid rgba(148,163,184,0.35);
    margin-bottom: 4px;
}
.calendar-cell {
    border: 1px solid rgba(148,163,184,0.35);
    border-radius: 12px;
    min-height: 120px;
    padding: 8px;
    margin-bottom: 8px;
    background: rgba(15,23,42,0.5);
    position: relative;
}
.calendar-cell.empty {
    background: rgba(15,23,42,0.25);
    border-style: dashed;
}
.calendar-day-num {
    font-size: 0.95rem;
    font-weight: 700;
    margin-bottom: 8px;
}
.pnl-pos { color: #22c55e; font-weight: 700; }
.pnl-neg { color: #ef4444; font-weight: 700; }
.pnl-flat { color: #cbd5e1; font-weight: 700; }
.tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.75rem;
    margin-top: 6px;
    background: rgba(148,163,184,0.25);
}

/* Watchlist top controls */
.watchlist-top {
    border: 1px solid rgba(148,163,184,0.35);
    border-radius: 14px;
    padding: 12px 14px;
    margin-bottom: 14px;
    background: rgba(15,23,42,0.5);
}
</style>
""", unsafe_allow_html=True)

# =========================
# Config / constants
# =========================
DEFAULT_TRADE_COLUMNS = [
    "id", "trade_date", "ticker", "setup", "side", "contracts", "entry", "exit",
    "gross_pnl", "commissions", "pnl", "followed_plan", "notes", "session",
    "created_at"
]

CORE_REQUIRED_TRADE_COLUMNS = [
    "trade_date", "ticker", "side", "contracts", "entry", "exit", "pnl"
]

WATCHLIST_COLUMNS = [
    "id", "symbol", "bias", "thesis", "entry_zone", "invalidate", "notes",
    "catalyst", "status", "created_at"
]

# Futures: ES, NQ, RTY (Russell 2000), VIX
FUTURES_SYMBOLS_DEFAULT = ["ES", "NQ", "RTY", "VIX"]

FUTURES_NAMES = {
    "ES": "S&P 500 (ES)",
    "NQ": "Nasdaq 100 (NQ)",
    "RTY": "Russell 2000 (RTY)",
    "VIX": "VIX Volatility Index",
}

FUTURES_BASE = {
    "ES": 6200,
    "NQ": 22800,
    "RTY": 2180,
    "VIX": 15,
}

US_MARKET_OPEN_ET = time(9, 30)
US_MARKET_CLOSE_ET = time(16, 0)

# =========================
# Helpers
# =========================
def safe_float(x, default=0.0):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return default
        return float(x)
    except Exception:
        return default


def format_money(x):
    x = safe_float(x, 0.0)
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def ensure_datetime_col(df, col):
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def init_supabase():
    url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
    key = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", ""))
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


supabase: Client | None = init_supabase()


def db_ready():
    return supabase is not None


@st.cache_data(ttl=60)
def fetch_table_columns(table_name: str):
    if not db_ready():
        return []
    try:
        sample = supabase.table(table_name).select("*").limit(1).execute()
        rows = getattr(sample, "data", None) or []
        if rows:
            return list(rows[0].keys())
    except Exception:
        pass
    return []


def trade_select_columns():
    existing = fetch_table_columns("trades")
    if not existing:
        return CORE_REQUIRED_TRADE_COLUMNS
    return [c for c in DEFAULT_TRADE_COLUMNS if c in existing]


@st.cache_data(ttl=30, show_spinner=False)
def get_trades_df():
    empty = pd.DataFrame(columns=DEFAULT_TRADE_COLUMNS)
    if not db_ready():
        return empty, "Supabase is not configured."

    cols = trade_select_columns()
    try:
        res = supabase.table("trades").select(",".join(cols)).order("trade_date", desc=True).execute()
        rows = getattr(res, "data", None) or []
        df = pd.DataFrame(rows)

        for c in DEFAULT_TRADE_COLUMNS:
            if c not in df.columns:
                df[c] = np.nan

        df = ensure_datetime_col(df, "trade_date")
        df = ensure_datetime_col(df, "created_at")

        numeric_cols = ["contracts", "entry", "exit", "gross_pnl", "commissions", "pnl"]
        for c in numeric_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        if "followed_plan" in df.columns:
            df["followed_plan"] = df["followed_plan"].astype("boolean")

        return df[DEFAULT_TRADE_COLUMNS], None
    except Exception:
        return empty, "Nothing here yet. Add a trade to get started."


@st.cache_data(ttl=30, show_spinner=False)
def get_watchlist_df():
    empty = pd.DataFrame(columns=WATCHLIST_COLUMNS)
    if not db_ready():
        return empty, "Supabase is not configured."

    try:
        res = supabase.table("watchlist").select("*").order("created_at", desc=True).execute()
        rows = getattr(res, "data", None) or []
        df = pd.DataFrame(rows)
    except Exception:
        return empty, "Nothing here yet. Add a symbol to get started."

    for c in WATCHLIST_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan

    df = ensure_datetime_col(df, "created_at")
    return df[WATCHLIST_COLUMNS], None


def invalidate_cache():
    get_trades_df.clear()
    get_watchlist_df.clear()
    fetch_table_columns.clear()


def upsert_watchlist(payload, row_id=None):
    if not db_ready():
        return False, "Supabase is not configured."

    try:
        if row_id:
            res = supabase.table("watchlist").update(payload).eq("id", row_id).execute()
        else:
            res = supabase.table("watchlist").insert(payload).execute()
        invalidate_cache()
        return True, res
    except Exception as e:
        return False, str(e)


def delete_watchlist(row_id):
    if not db_ready():
        return False, "Supabase is not configured."

    try:
        res = supabase.table("watchlist").delete().eq("id", row_id).execute()
        invalidate_cache()
        return True, res
    except Exception as e:
        return False, str(e)


def trades_metrics(df: pd.DataFrame):
    if df.empty:
        return {
            "net_pnl": 0.0,
            "gross_pnl": 0.0,
            "commissions": 0.0,
            "trades": 0,
            "win_rate": 0.0,
            "avg_trade": 0.0,
            "daily_pnl": 0.0,
            "daily_pct": 0.0,
            "net_pct": 0.0,
        }

    work = df.copy()
    work["pnl"] = pd.to_numeric(work["pnl"], errors="coerce").fillna(0.0)
    if "gross_pnl" in work.columns:
        work["gross_pnl"] = pd.to_numeric(work["gross_pnl"], errors="coerce").fillna(work["pnl"])
    else:
        work["gross_pnl"] = work["pnl"]
    if "commissions" in work.columns:
        work["commissions"] = pd.to_numeric(work["commissions"], errors="coerce").fillna(0.0)
    else:
        work["commissions"] = 0.0

    trades = len(work)
    wins = int((work["pnl"] > 0).sum())

    base_capital = 20000.0
    net_pnl = float(work["pnl"].sum())
    net_pct = net_pnl / base_capital * 100.0

    today = datetime.now().date()
    if "trade_date" in work.columns:
        today_rows = work[pd.to_datetime(work["trade_date"], errors="coerce").dt.date == today]
    else:
        today_rows = pd.DataFrame(columns=work.columns)
    daily_pnl = float(today_rows["pnl"].sum()) if not today_rows.empty else 0.0
    daily_pct = daily_pnl / base_capital * 100.0

    return {
        "net_pnl": net_pnl,
        "gross_pnl": float(work["gross_pnl"].sum()),
        "commissions": float(work["commissions"].sum()),
        "trades": trades,
        "win_rate": (wins / trades * 100.0) if trades else 0.0,
        "avg_trade": float(work["pnl"].mean()) if trades else 0.0,
        "daily_pnl": daily_pnl,
        "daily_pct": daily_pct,
        "net_pct": net_pct,
    }


def monthly_pnl_chart(df: pd.DataFrame):
    if df.empty:
        return None
    work = df.dropna(subset=["trade_date"]).copy()
    if work.empty:
        return None

    work["month"] = pd.to_datetime(work["trade_date"]).dt.to_period("M").astype(str)
    work["pnl"] = pd.to_numeric(work["pnl"], errors="coerce").fillna(0.0)
    monthly = work.groupby("month", as_index=False)["pnl"].sum()
    fig = px.bar(
        monthly,
        x="month",
        y="pnl",
        title="Monthly Net P&L",
        color="pnl",
        color_continuous_scale=["#ef4444", "#94a3b8", "#22c55e"]
    )
    fig.update_layout(height=330, margin=dict(l=10, r=10, t=40, b=10), coloraxis_showscale=False)
    return fig


def equity_curve_chart(df: pd.DataFrame):
    if df.empty:
        return None
    work = df.dropna(subset=["trade_date"]).copy()
    if work.empty:
        return None
    work = work.sort_values("trade_date")
    work["pnl"] = pd.to_numeric(work["pnl"], errors="coerce").fillna(0.0)
    work["equity"] = work["pnl"].cumsum()
    fig = px.line(work, x="trade_date", y="equity", title="Equity Curve", markers=False)
    fig.update_layout(height=330, margin=dict(l=10, r=10, t=40, b=10))
    return fig


def setup_pnl_chart(df: pd.DataFrame):
    if df.empty or "setup" not in df.columns:
        return None
    work = df.copy()
    work["setup"] = work["setup"].fillna("Unspecified")
    work["pnl"] = pd.to_numeric(work["pnl"], errors="coerce").fillna(0.0)
    agg = work.groupby("setup", as_index=False)["pnl"].sum().sort_values("pnl", ascending=False)
    if agg.empty:
        return None
    fig = px.bar(agg, x="setup", y="pnl", title="Net P&L by Setup")
    fig.update_layout(height=330, margin=dict(l=10, r=10, t=40, b=10))
    return fig


def generate_futures_series(symbol: str):
    idx = pd.date_range(
        end=pd.Timestamp.now(),
        periods=30,
        freq=pd.Timedelta(minutes=10)
    )
    base = FUTURES_BASE.get(symbol, 100)

    np.random.seed(abs(hash(symbol)) % (2**32))
    steps = np.random.normal(0, 1, len(idx))
    prices = base + np.cumsum(steps)

    return idx, prices, base


def futures_chart(symbol: str):
    idx, prices, base = generate_futures_series(symbol)
    df = pd.DataFrame({"time": idx, "price": prices})
    last = prices[-1]
    change = last - base
    pct_change = (change / base * 100.0) if base != 0 else 0.0

    line_color = "#22c55e" if last >= base else "#ef4444"

    fig = px.line(df, x="time", y="price")  # no title, name is in st.metric
    fig.update_traces(line=dict(color=line_color, width=2))
    fig.update_layout(
        height=160,
        margin=dict(l=6, r=6, t=12, b=6),
        xaxis_title=None,
        yaxis_title=None,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showgrid=False, visible=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(148,163,184,0.12)")
    return fig, last, change, pct_change


def daily_calendar_agg(trades_df: pd.DataFrame):
    if trades_df.empty or "trade_date" not in trades_df.columns:
        return pd.DataFrame(columns=["date", "daily_net_pnl", "daily_pct", "follow_ratio", "trade_count"])

    df = trades_df.copy()
    df = df.dropna(subset=["trade_date"])
    if df.empty:
        return pd.DataFrame(columns=["date", "daily_net_pnl", "daily_pct", "follow_ratio", "trade_count"])

    df["date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)

    if "followed_plan" in df.columns:
        follow_series = df["followed_plan"].astype("boolean")
    else:
        follow_series = pd.Series([pd.NA] * len(df), index=df.index, dtype="boolean")

    g = df.groupby("date", as_index=False).agg(
        daily_net_pnl=("pnl", "sum"),
        trade_count=("ticker", "count")
    )

    follow_df = df[["date"]].copy()
    follow_df["fp"] = follow_series.astype("float")
    follow_ratio = follow_df.groupby("date", as_index=False)["fp"].mean().rename(columns={"fp": "follow_ratio"})

    out = g.merge(follow_ratio, on="date", how="left")

    base_capital = 20000.0
    out["daily_pct"] = out["daily_net_pnl"] / base_capital * 100.0

    return out.sort_values("date")


def get_local_now():
    return datetime.now(timezone.utc).astimezone()


def market_status():
    now_local = get_local_now()

    et = timezone(timedelta(hours=-4))
    now_et = now_local.astimezone(et)
    today_et = now_et.date()

    open_dt = datetime.combine(today_et, US_MARKET_OPEN_ET, tzinfo=et)
    close_dt = datetime.combine(today_et, US_MARKET_CLOSE_ET, tzinfo=et)

    if now_et < open_dt:
        return now_local, "Market closed"
    elif open_dt <= now_et <= close_dt:
        return now_local, "Market open"
    else:
        return now_local, "Market closed"


def render_calendar_grid(year: int, month: int, cal_df: pd.DataFrame):
    day_map = {}
    if cal_df is not None and not cal_df.empty:
        for _, row in cal_df.iterrows():
            day_map[row["date"]] = row.to_dict()

    today = datetime.now().date()

    dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    cols = st.columns(7)
    for i, name in enumerate(dow):
        cols[i].markdown(f"<div class='calendar-header'>{name}</div>", unsafe_allow_html=True)

    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)

    for week in weeks:
        row_cols = st.columns(7)
        for idx, day in enumerate(week):
            with row_cols[idx]:
                if day == 0:
                    st.markdown("<div class='calendar-cell empty'></div>", unsafe_allow_html=True)
                    continue

                d = date(year, month, day)
                row = day_map.get(d, None)
                is_today = (d == today)

                if row is None:
                    html = f"""
                    <div class='calendar-cell'>
                        <div class='calendar-day-num'>{day}</div>
                        <div class='small-muted'>No trades</div>
                        {"<div class='tag'>Today</div>" if is_today else ""}
                    </div>
                    """
                    st.markdown(html, unsafe_allow_html=True)
                else:
                    net = safe_float(row.get("daily_net_pnl"), 0.0)
                    tcount = int(row.get("trade_count", 0) or 0)
                    fr = row.get("follow_ratio", np.nan)
                    pct = safe_float(row.get("daily_pct"), 0.0)

                    follow_text = "N/A"
                    if pd.notna(fr):
                        follow_text = f"{fr*100:.0f}% plan"

                    html = f"""
                    <div class='calendar-cell'>
                        <div class='calendar-day-num'>{day}</div>
                        <div class='{ "pnl-pos" if net > 0 else "pnl-neg" if net < 0 else "pnl-flat" }'>
                            {format_money(net)} ({pct:+.2f}%)
                        </div>
                        <div class='small-muted'>{tcount} trade{'s' if tcount != 1 else ''}</div>
                        <div class='tag'>{follow_text}</div>
                        {"<div class='tag'>Today</div>" if is_today else ""}
                    </div>
                    """
                    st.markdown(html, unsafe_allow_html=True)


# =========================
# Data load
# =========================
trades_df, trades_msg = get_trades_df()
watchlist_df, watchlist_msg = get_watchlist_df()

# =========================
# Header
# =========================
now_local, status = market_status()
date_str = now_local.strftime("%a, %b %-d, %Y")
time_str = now_local.strftime("%-I:%M %p")

header_html = f"""
<div class="app-header">
  <div class="app-header-left">
    <h1>Trading Journal</h1>
  </div>
  <div class="app-header-right">
    <div><strong>{time_str}</strong> • {date_str}</div>
    <div class="app-header-status">{status}</div>
  </div>
</div>
"""
st.markdown(header_html, unsafe_allow_html=True)

if not db_ready():
    st.warning("Supabase credentials are missing. The app will still render, but database features will not work.")

# =========================
# Tabs
# =========================
tab_dashboard, tab_trades, tab_watchlist, tab_calendar = st.tabs(
    ["Dashboard", "Trades", "Watchlist", "Calendar"]
)

# =========================
# Dashboard
# =========================
with tab_dashboard:
    metrics = trades_metrics(trades_df)

    # KPI order: Trades, Daily P&L, Net P&L, Gross P&L, Commissions, Win Rate, Avg Trade
    m_trades, m_daily, m_net, m_gross, m_comm, m_win, m_avg = st.columns(7)
    m_trades.metric("Trades", f"{metrics['trades']}")
    m_daily.metric("Daily P&L", format_money(metrics["daily_pnl"]), f"{metrics['daily_pct']:+.2f}%")
    m_net.metric("Net P&L", format_money(metrics["net_pnl"]), f"{metrics['net_pct']:+.2f}%")
    m_gross.metric("Gross P&L", format_money(metrics["gross_pnl"]))
    m_comm.metric("Commissions", format_money(metrics["commissions"]))
    m_win.metric("Win Rate", f"{metrics['win_rate']:.1f}%")
    m_avg.metric("Avg Trade", format_money(metrics["avg_trade"]))

    st.markdown("### Futures")
    st.button("Refresh futures prices")  # click → script reruns, data regenerates

    fc1, fc2, fc3, fc4 = st.columns(4)

    # ES
    with fc1:
        fig_es, last_es, ch_es, pct_es = futures_chart("ES")
        name = FUTURES_NAMES["ES"]
        delta_text = f"{ch_es:+.1f} ({pct_es:+.2f}%)"
        st.metric(name, f"{last_es:,.1f}", delta_text)
        st.plotly_chart(fig_es, use_container_width=True)

    # NQ
    with fc2:
        fig_nq, last_nq, ch_nq, pct_nq = futures_chart("NQ")
        name = FUTURES_NAMES["NQ"]
        delta_text = f"{ch_nq:+.1f} ({pct_nq:+.2f}%)"
        st.metric(name, f"{last_nq:,.1f}", delta_text)
        st.plotly_chart(fig_nq, use_container_width=True)

    # RTY
    with fc3:
        fig_rty, last_rty, ch_rty, pct_rty = futures_chart("RTY")
        name = FUTURES_NAMES["RTY"]
        delta_text = f"{ch_rty:+.1f} ({pct_rty:+.2f}%)"
        st.metric(name, f"{last_rty:,.1f}", delta_text)
        st.plotly_chart(fig_rty, use_container_width=True)

    # VIX
    with fc4:
        fig_vix, last_vix, ch_vix, pct_vix = futures_chart("VIX")
        name = FUTURES_NAMES["VIX"]
        delta_text = f"{ch_vix:+.2f} ({pct_vix:+.2f}%)"
        st.metric(name, f"{last_vix:,.2f}", delta_text)
        st.plotly_chart(fig_vix, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        fig_eq = equity_curve_chart(trades_df)
        if fig_eq:
            st.plotly_chart(fig_eq, use_container_width=True)
        else:
            st.info("Nothing here yet. Add a trade to get started.")

    with c2:
        fig_month = monthly_pnl_chart(trades_df)
        if fig_month:
            st.plotly_chart(fig_month, use_container_width=True)
        else:
            st.info("Nothing here yet. Add a trade to get started.")

    fig_setup = setup_pnl_chart(trades_df)
    if fig_setup:
        st.plotly_chart(fig_setup, use_container_width=True)

# =========================
# Trades
# =========================
with tab_trades:
    st.subheader("Trades")

    # --- File upload from trading platform ---
    st.markdown("### Upload trades from platform")
    uploaded_file = st.file_uploader(
        "Upload CSV export from your trading platform",
        type=["csv"],
        key="trades_upload"
    )

    uploaded_df = None
    if uploaded_file is not None:
        try:
            uploaded_df = pd.read_csv(uploaded_file)
            st.success(f"Loaded {len(uploaded_df)} rows from {uploaded_file.name}")
            st.dataframe(uploaded_df.head(), use_container_width=True, height=240)
            st.info("Mapping + Supabase insert can be wired here once we lock the exact broker export format.")
        except Exception as e:
            st.error(f"Could not read uploaded file: {e}")

    st.markdown("### Manual entry")
    selected_trade_id = None
    trade_ids = trades_df["id"].dropna().tolist() if "id" in trades_df.columns and not trades_df.empty else []
    pick_existing = st.checkbox("Edit existing trade")
    if pick_existing and trade_ids:
        selected_trade_id = st.selectbox("Select trade ID", trade_ids)
        existing = trades_df[trades_df["id"] == selected_trade_id].iloc[0].to_dict()
    else:
        existing = {}

    c1, c2, c3 = st.columns(3)
    with c1:
        trade_date = st.date_input(
            "Trade date",
            value=(existing.get("trade_date").date() if pd.notna(existing.get("trade_date")) else date.today())
        )
        ticker = st.text_input("Ticker", value="" if pd.isna(existing.get("ticker")) else str(existing.get("ticker", "")))
        setup = st.text_input("Setup", value="" if pd.isna(existing.get("setup")) else str(existing.get("setup", "")))
        side = st.selectbox("Side", ["Long", "Short"], index=0 if str(existing.get("side", "Long")).lower() != "short" else 1)
    with c2:
        contracts = st.number_input("Contracts", min_value=0, value=int(safe_float(existing.get("contracts"), 1)))
        entry = st.number_input("Entry", value=float(safe_float(existing.get("entry"), 0.0)), format="%.4f")
        exit_ = st.number_input("Exit", value=float(safe_float(existing.get("exit"), 0.0)), format="%.4f")
        session = st.text_input("Session", value="" if pd.isna(existing.get("session")) else str(existing.get("session", "")))
    with c3:
        gross_pnl = st.number_input("Gross P&L", value=float(safe_float(existing.get("gross_pnl"), safe_float(existing.get("pnl"), 0.0))), format="%.2f")
        commissions = st.number_input("Commissions", value=float(safe_float(existing.get("commissions"), 0.0)), format="%.2f")
        pnl = st.number_input("Net P&L", value=float(safe_float(existing.get("pnl"), gross_pnl - commissions)), format="%.2f")
        followed_plan = st.checkbox("Followed plan", value=bool(existing.get("followed_plan")) if pd.notna(existing.get("followed_plan")) else False)

    notes = st.text_area("Notes", value="" if pd.isna(existing.get("notes")) else str(existing.get("notes", "")))

    st.info("Save/delete logic can be wired to Supabase here once the schema is final.")

    st.markdown("### Trade log")
    display_df = trades_df.copy()
    if not display_df.empty and "trade_date" in display_df.columns:
        display_df["trade_date"] = pd.to_datetime(display_df["trade_date"], errors="coerce").dt.date

    if trades_msg:
        st.info(trades_msg)

    st.dataframe(display_df, use_container_width=True, height=420)

# =========================
# Watchlist
# =========================
with tab_watchlist:
    st.subheader("Watchlist")

    st.markdown("<div class='watchlist-top'>", unsafe_allow_html=True)
    top1, top2, top3, top4, top5 = st.columns([1.2, 1.2, 1.6, 1.2, 1.0])
    with top1:
        wl_symbol = st.text_input("Symbol", key="wl_symbol")
    with top2:
        wl_bias = st.selectbox("Bias", ["Long", "Short", "Neutral"], key="wl_bias")
    with top3:
        wl_thesis = st.text_input("Thesis", key="wl_thesis")
    with top4:
        wl_status = st.selectbox("Status", ["Active", "Watching", "Triggered", "Closed"], key="wl_status")
    with top5:
        st.write("")
        st.write("")
        add_watch = st.button("Add to watchlist", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if add_watch:
        payload = {
            "symbol": wl_symbol,
            "bias": wl_bias,
            "thesis": wl_thesis,
            "status": wl_status,
        }
        ok, msg = upsert_watchlist(payload)
        if ok:
            st.success("Added to watchlist.")
            st.rerun()
        else:
            st.error(f"Add failed: {msg}")

    if watchlist_msg:
        st.info(watchlist_msg)

    if watchlist_df.empty:
        st.info("Nothing here yet. Add a symbol to get started.")
    else:
        st.dataframe(watchlist_df, use_container_width=True, height=420)

        with st.expander("Edit / Delete Watchlist Item", expanded=False):
            ids = watchlist_df["id"].dropna().tolist() if "id" in watchlist_df.columns else []
            if ids:
                row_id = st.selectbox("Select item ID", ids)
                row = watchlist_df[watchlist_df["id"] == row_id].iloc[0].to_dict()

                c1, c2 = st.columns(2)
                with c1:
                    symbol = st.text_input("Symbol ", value=str(row.get("symbol", "")))
                    bias = st.selectbox(
                        "Bias ",
                        ["Long", "Short", "Neutral"],
                        index=["Long", "Short", "Neutral"].index(str(row.get("bias", "Neutral")))
                        if str(row.get("bias", "Neutral")) in ["Long", "Short", "Neutral"] else 2
                    )
                    thesis = st.text_input("Thesis ", value="" if pd.isna(row.get("thesis")) else str(row.get("thesis", "")))
                    status = st.selectbox(
                        "Status ",
                        ["Active", "Watching", "Triggered", "Closed"],
                        index=["Active", "Watching", "Triggered", "Closed"].index(str(row.get("status", "Watching")))
                        if str(row.get("status", "Watching")) in ["Active", "Watching", "Triggered", "Closed"] else 1
                    )
                with c2:
                    entry_zone = st.text_input("Entry zone", value="" if pd.isna(row.get("entry_zone")) else str(row.get("entry_zone", "")))
                    invalidate = st.text_input("Invalidate", value="" if pd.isna(row.get("invalidate")) else str(row.get("invalidate", "")))
                    catalyst = st.text_input("Catalyst", value="" if pd.isna(row.get("catalyst")) else str(row.get("catalyst", "")))
                    notes = st.text_area("Notes ", value="" if pd.isna(row.get("notes")) else str(row.get("notes", "")))

                e1, e2 = st.columns(2)
                with e1:
                    if st.button("Save watchlist item", use_container_width=True):
                        payload = {
                            "symbol": symbol,
                            "bias": bias,
                            "thesis": thesis,
                            "status": status,
                            "entry_zone": entry_zone,
                            "invalidate": invalidate,
                            "catalyst": catalyst,
                            "notes": notes,
                        }
                        ok, msg = upsert_watchlist(payload, row_id=row_id)
                        if ok:
                            st.success("Watchlist item saved.")
                            st.rerun()
                        else:
                            st.error(f"Save failed: {msg}")
                with e2:
                    if st.button("Delete watchlist item", use_container_width=True):
                        ok, msg = delete_watchlist(row_id)
                        if ok:
                            st.success("Watchlist item deleted.")
                            st.rerun()
                        else:
                            st.error(f"Delete failed: {msg}")

# =========================
# Calendar
# =========================
with tab_calendar:
    st.subheader("Calendar")

    today = date.today()
    c1, c2 = st.columns([1, 1])
    with c1:
        year = st.selectbox("Year", list(range(today.year - 3, today.year + 4)), index=3)
    with c2:
        month = st.selectbox("Month", list(range(1, 13)), index=today.month - 1, format_func=lambda m: calendar.month_name[m])

    cal_df = pd.DataFrame(columns=["date", "daily_net_pnl", "daily_pct", "follow_ratio", "trade_count"])
    try:
        if trades_df is not None and not trades_df.empty:
            cal_df = daily_calendar_agg(trades_df)
    except Exception:
        pass

    render_calendar_grid(year, month, cal_df)
    st.caption("The calendar grid always renders. Trade data overlays when available.")
