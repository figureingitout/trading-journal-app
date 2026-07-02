import os
import math
import calendar
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import create_client, Client

# Optional: only used if installed
try:
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
    AGGRID_AVAILABLE = True
except Exception:
    AGGRID_AVAILABLE = False


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

/* Top header: clock + title */
.app-header {
    display: flex;
    align-items: baseline;
    gap: 1rem;
    margin-bottom: 0.75rem;
}
.app-header-left {
    font-size: 0.9rem;
    color: #9ca3af;
}
.app-header-left strong {
    color: #e5e7eb;
}
.app-header-right h1 {
    margin: 0;
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

/* Generic cards */
.section-card {
    border: 1px solid rgba(148,163,184,0.35);
    border-radius: 14px;
    padding: 14px;
    background: rgba(15,23,42,0.5);
}
.small-muted {
    color: #9aa0a6;
    font-size: 0.9rem;
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
.calendar-cell.today {
    border-color: #fbbf24;
    box-shadow: 0 0 0 1px rgba(251,191,36,0.6);
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
.today-badge {
    position: absolute;
    top: 6px;
    right: 8px;
    font-size: 0.7rem;
    padding: 2px 6px;
    border-radius: 999px;
    background: rgba(251,191,36,0.9);
    color: #111827;
    font-weight: 600;
}

/* Watchlist top controls */
.watchlist-top {
    border: 1px solid rgba(148,163,184,0.35);
    border-radius: 14px;
    padding: 12px 14px;
    margin-bottom: 14px;
    background: rgba(15,23,42,0.5);
}

/* Mini futures charts row */
.futures-mini-row {
    margin-bottom: 8px;
}
.futures-mini-title {
    font-size: 0.85rem;
    color: #9aa0a6;
    margin-bottom: 4px;
}

/* Minor tweaks */
hr {
    margin-top: 0.5rem;
    margin-bottom: 1rem;
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

FUTURES_SYMBOLS_DEFAULT = ["ES", "NQ", "YM", "RTY", "CL", "GC"]

US_MARKET_OPEN_ET = time(9, 30)   # 9:30 AM Eastern
US_MARKET_CLOSE_ET = time(16, 0)  # 4:00 PM Eastern
PREOPEN_WINDOW_MINUTES = 30       # countdown starts this many minutes before open


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
    # Basic best-effort schema detection via sample row
    try:
        sample = supabase.table(table_name).select("*").limit(1).execute()
        rows = getattr(sample, "data", None) or []
        if rows:
            return list(rows[0].keys())
    except Exception:
        pass
    return []


def get_existing_trade_columns():
    cols = fetch_table_columns("trades")
    if cols:
        return cols
    return []


def get_existing_watchlist_columns():
    cols = fetch_table_columns("watchlist")
    if cols:
        return cols
    return []


def trade_select_columns():
    existing = get_existing_trade_columns()
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
    except Exception as e:
        # Friendly empty state instead of technical error
        return empty, "Nothing here yet. Add a trade to get started."


@st.cache_data(ttl=30, show_spinner=False)
def get_watchlist_df():
    empty = pd.DataFrame(columns=WATCHLIST_COLUMNS)
    if not db_ready():
        return empty, "Supabase is not configured."

    existing = get_existing_watchlist_columns()
    try:
        cols = [c for c in WATCHLIST_COLUMNS if c in existing] or existing
        res = supabase.table("watchlist").select(",".join(cols) if cols else "*").order("created_at", desc=True).execute()
        rows = getattr(res, "data", None) or []
        df = pd.DataFrame(rows)
    except Exception as e:
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


def upsert_trade(payload, trade_id=None):
    if not db_ready():
        return False, "Supabase is not configured."

    try:
        if trade_id:
            res = supabase.table("trades").update(payload).eq("id", trade_id).execute()
        else:
            res = supabase.table("trades").insert(payload).execute()
        invalidate_cache()
        return True, res
    except Exception as e:
        return False, str(e)


def delete_trade(trade_id):
    if not db_ready():
        return False, "Supabase is not configured."

    try:
        res = supabase.table("trades").delete().eq("id", trade_id).execute()
        invalidate_cache()
        return True, res
    except Exception as e:
        return False, str(e)


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


def daily_calendar_agg(trades_df: pd.DataFrame):
    if trades_df.empty or "trade_date" not in trades_df.columns:
        return pd.DataFrame(columns=["date", "daily_net_pnl", "daily_pct", "follow_ratio", "trade_count"])

    df = trades_df.copy()
    df = df.dropna(subset=["trade_date"])
    if df.empty:
        return pd.DataFrame(columns=["date", "daily_net_pnl", "daily_pct", "follow_ratio", "trade_count"])

    df["date"] = pd.to_datetime(df["trade_date"]).dt.date
    if "pnl" not in df.columns:
        df["pnl"] = 0.0
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

    # Daily percentage move: you can plug in your account base here if desired
    base_capital = 20000.0
    out["daily_pct"] = out["daily_net_pnl"] / base_capital * 100.0

    return out.sort_values("date")


def pnl_class(x):
    x = safe_float(x, 0.0)
    if x > 0:
        return "pnl-pos"
    if x < 0:
        return "pnl-neg"
    return "pnl-flat"


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
                    <div class='calendar-cell{" today" if is_today else ""}'>
                        <div class='calendar-day-num'>{day}</div>
                        <div class='small-muted'>No trades</div>
                        {"<div class='today-badge'>Today</div>" if is_today else ""}
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
                    <div class='calendar-cell{" today" if is_today else ""}'>
                        <div class='calendar-day-num'>{day}</div>
                        <div class='{pnl_class(net)}'>{format_money(net)} ({pct:+.2f}%)</div>
                        <div class='small-muted'>{tcount} trade{'s' if tcount != 1 else ''}</div>
                        <div class='tag'>{follow_text}</div>
                        {"<div class='today-badge'>Today</div>" if is_today else ""}
                    </div>
                    """
                    st.markdown(html, unsafe_allow_html=True)


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

    base_capital = 20000.0  # adjust to your true account base

    net_pnl = float(work["pnl"].sum())
    net_pct = net_pnl / base_capital * 100.0

    # Daily P&L (today only)
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


def get_futures_snapshot(symbols):
    # Placeholder row; connect to real data later
    rows = []
    for s in symbols:
        rows.append({
            "Instrument": f"{s} Futures",
            "Last": np.nan,
            "Change": np.nan,
            "%": np.nan,
        })
    return pd.DataFrame(rows)


def get_local_now():
    # Get aware datetime in local system timezone
    return datetime.now(timezone.utc).astimezone()


def market_status_and_countdown():
    now_local = get_local_now()

    # Fixed market reference timezone: Eastern
    et = timezone(timedelta(hours=-4))  # works for current daylight period

    now_et = now_local.astimezone(et)
    today_et = now_et.date()

    open_dt = datetime.combine(today_et, US_MARKET_OPEN_ET, tzinfo=et)
    close_dt = datetime.combine(today_et, US_MARKET_CLOSE_ET, tzinfo=et)

    status = "Market closed"
    countdown = None
    ding = False

    if now_et < open_dt:
        delta_to_open = open_dt - now_et
        if delta_to_open <= timedelta(minutes=PREOPEN_WINDOW_MINUTES):
            status = "Market opens in"
            countdown = delta_to_open
            if delta_to_open <= timedelta(seconds=1):
                ding = True
        else:
            status = "Market closed"
    elif open_dt <= now_et <= close_dt:
        status = "Market open"
    else:
        status = "Market closed"

    return now_local, status, countdown, ding


# =========================
# Data load
# =========================
trades_df, trades_msg = get_trades_df()
watchlist_df, watchlist_msg = get_watchlist_df()

# =========================
# Header (clock + date + market status)
# =========================
now_local, market_status, countdown, ding = market_status_and_countdown()
date_str = now_local.strftime("%a, %b %-d, %Y") if hasattr(now_local, "strftime") else ""
time_str = now_local.strftime("%-I:%M %p") if hasattr(now_local, "strftime") else ""

header_html = f"""
<div class="app-header">
  <div class="app-header-left">
    <div><strong>{time_str}</strong> • {date_str}</div>
    <div class="app-header-status">
      {market_status}{(" " + f"{int(countdown.total_seconds()//60):02d}:{int(countdown.total_seconds()%60):02d}") if countdown else ""}
    </div>
  </div>
  <div class="app-header-right">
    <h1>Trading Journal</h1>
  </div>
</div>
"""

st.markdown(header_html, unsafe_allow_html=True)

# Play ding at market open (simple placeholder)
if ding:
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg")

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

    m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
    m1.metric("Net P&L", format_money(metrics["net_pnl"]), f"{metrics['net_pct']:+.2f}%")
    m2.metric("Gross P&L", format_money(metrics["gross_pnl"]))
    m3.metric("Commissions", format_money(metrics["commissions"]))
    m4.metric("Trades", f"{metrics['trades']}")
    m5.metric("Win Rate", f"{metrics['win_rate']:.1f}%")
    m6.metric("Avg Trade", format_money(metrics["avg_trade"]))
    m7.metric("Daily P&L", format_money(metrics["daily_pnl"]), f"{metrics['daily_pct']:+.2f}%")

    c1, c2 = st.columns(2)
    with c1:
        fig = equity_curve_chart(trades_df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nothing here yet. Add a trade to get started.")
    with c2:
        fig = monthly_pnl_chart(trades_df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nothing here yet. Add a trade to get started.")

    fig = setup_pnl_chart(trades_df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

# =========================
# Trades
# =========================
with tab_trades:
    st.subheader("Trades")

    with st.expander("Add / Edit Trade", expanded=False):
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

        b1, b2 = st.columns(2)
        with b1:
            if st.button("Save trade", use_container_width=True):
                payload = {
                    "trade_date": str(trade_date),
                    "ticker": ticker,
                    "setup": setup,
                    "side": side,
                    "contracts": contracts,
                    "entry": entry,
                    "exit": exit_,
                    "gross_pnl": gross_pnl,
                    "commissions": commissions,
                    "pnl": pnl,
                    "followed_plan": followed_plan,
                    "notes": notes,
                    "session": session,
                }
                ok, msg = upsert_trade(payload, trade_id=selected_trade_id)
                if ok:
                    st.success("Trade saved.")
                    st.rerun()
                else:
                    st.error(f"Save failed: {msg}")
        with b2:
            if selected_trade_id and st.button("Delete trade", use_container_width=True):
                ok, msg = delete_trade(selected_trade_id)
                if ok:
                    st.success("Trade deleted.")
                    st.rerun()
                else:
                    st.error(f"Delete failed: {msg}")

    # Manual import above manual entry (placeholder section)
    st.markdown("### Manual import")
    st.info("Manual import will go here (e.g., file upload / broker export).")

    st.markdown("### Trade log")
    display_df = trades_df.copy()
    if not display_df.empty and "trade_date" in display_df.columns:
        display_df["trade_date"] = pd.to_datetime(display_df["trade_date"], errors="coerce").dt.date

    if trades_msg:
        st.info(trades_msg)

    if AGGRID_AVAILABLE and not display_df.empty:
        gb = GridOptionsBuilder.from_dataframe(display_df)
        gb.configure_default_column(editable=False, filter=True, sortable=True, resizable=True)
        gb.configure_selection("single", use_checkbox=True)
        grid_options = gb.build()
        AgGrid(
            display_df,
            gridOptions=grid_options,
            theme="streamlit",
            height=420,
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            fit_columns_on_grid_load=True,
            use_container_width=True,
            reload_data=False,
        )
    else:
        st.dataframe(display_df, use_container_width=True, height=420)

# =========================
# Watchlist (combined ideas + prep + futures mini-charts)
# =========================
with tab_watchlist:
    st.subheader("Watchlist")

    # Mini futures charts row at top, kept small and side by side
    st.markdown("<div class='futures-mini-row'>", unsafe_allow_html=True)
    fc1, fc2, fc3 = st.columns(3)
    symbols_text = ", ".join(FUTURES_SYMBOLS_DEFAULT)
    fut_df = get_futures_snapshot(FUTURES_SYMBOLS_DEFAULT)
    with fc1:
        st.markdown("<div class='futures-mini-title'>Market context</div>", unsafe_allow_html=True)
        st.dataframe(fut_df, use_container_width=True, height=130)
    with fc2:
        st.markdown("<div class='futures-mini-title'>Notes</div>", unsafe_allow_html=True)
        st.text_area(
            "Futures prep",
            placeholder="Key levels, overnight inventory, bias, economic events...",
            height=130,
            label_visibility="collapsed",
        )
    with fc3:
        st.markdown("<div class='futures-mini-title'>Symbols", unsafe_allow_html=True)
        st.text_input("Symbols", value=symbols_text, label_visibility="collapsed")
    st.markdown("</div>", unsafe_allow_html=True)

    # Watchlist top controls
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
        show_cols = [c for c in ["id", "symbol", "bias", "thesis", "entry_zone", "invalidate", "catalyst", "status", "notes", "created_at"] if c in watchlist_df.columns]
        st.dataframe(watchlist_df[show_cols], use_container_width=True, height=420)

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
                        index=["Long", "Short", "Neutral"].index(str(row.get("bias", "Neutral"))) if str(row.get("bias", "Neutral")) in ["Long", "Short", "Neutral"] else 2
                    )
                    thesis = st.text_input("Thesis ", value="" if pd.isna(row.get("thesis")) else str(row.get("thesis", "")))
                    status = st.selectbox(
                        "Status ",
                        ["Active", "Watching", "Triggered", "Closed"],
                        index=["Active", "Watching", "Triggered", "Closed"].index(str(row.get("status", "Watching"))) if str(row.get("status", "Watching")) in ["Active", "Watching", "Triggered", "Closed"] else 1
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
    cal_notice = None

    try:
        if trades_df is not None and not trades_df.empty:
            cal_df = daily_calendar_agg(trades_df)
    except Exception as e:
        cal_notice = "Trade data could not be overlaid on the calendar."

    render_calendar_grid(year, month, cal_df)

    if cal_notice:
        st.info(cal_notice)
    elif trades_msg:
        st.info("Calendar is showing without trade overlays because trades could not be loaded.")

    st.caption("The calendar grid always renders. Trade data is optional and overlays when available.")
