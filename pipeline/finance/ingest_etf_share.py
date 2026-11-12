#!/usr/bin/env python3
"""
国家队 ETF 份额流向：入库 + 事件研究 + HTML 报表。

数据源：Tushare Pro
    fund_share    每日基金份额（万份）
    fund_nav      单位净值
    fund_daily    收盘价
    index_daily   沪深 300（基准）

输出：
    data/finance/finance.db
        etf_meta              标的池与分类
        etf_share_daily       单只 ETF 每日份额 / 净值 / 净申赎
        etf_flow_daily        按日期 × 分类聚合的净申赎
        etf_benchmark_daily   沪深 300 基准（收盘）
        etf_index_daily       沪深300 / 中证全指 OHLC（K 线图用）
        margin_daily          沪深两市融资余额（杠杆资金）
        etf_episode           大额流入事件与后续收益

    data/finance/国家队ETF份额流向_<最新日期>.html
        - 每日净申赎 × 沪深300
        - 累计持仓金额（2024 至今）
        - 中证全指 K 线 × 每日净买入 × 融资余额联动（2024 至今，ECharts）
        - 20 日滚动累计、分类累计、事件研究、最新明细

用法：
    python pipeline/finance/ingest_etf_share.py --start 20150101 --end 20261111
    python pipeline/finance/ingest_etf_share.py --report-only
    python pipeline/finance/ingest_etf_share.py --refresh-benchmark --report-only
    python pipeline/finance/ingest_etf_share.py --refresh-margin --report-only
    python pipeline/finance/ingest_etf_share.py --start 20150101 --end 20261111 --report

口径：
    净申赎（亿元）=（当日调整后份额 − 前一日调整后份额）× 当日单位净值 / 1e4
    份额单位为「万份」；折算/合并日按「份额比例 × 净值比例 ≈ 1」识别并置 0。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import tushare as ts

IP_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = IP_ROOT / "a-share-agent" / ".env"
DB_PATH = IP_ROOT / "data" / "finance" / "finance.db"
OUT_DIR = IP_ROOT / "data" / "finance"

BENCH_CODE = "000300.SH"
ALLSHARE_CODE = "000985.CSI"  # 中证全指，K线联动图默认基准

# 中央汇金重仓的 29 只核心宽基 ETF（与 wj624 报表口径一致，便于交叉核对）
# (6 位代码, 名称, 分类, 交易所)
TARGETS = [
    ("510300", "沪深300ETF 华泰柏瑞", "沪深300", "SH"),
    ("510310", "沪深300ETF 易方达", "沪深300", "SH"),
    ("510330", "沪深300ETF 华夏", "沪深300", "SH"),
    ("159919", "沪深300ETF 嘉实", "沪深300", "SZ"),
    ("510050", "上证50ETF 华夏", "上证50", "SH"),
    ("510100", "上证50ETF 易方达", "上证50", "SH"),
    ("510500", "中证500ETF 南方", "中证500", "SH"),
    ("512500", "中证500ETF 华夏", "中证500", "SH"),
    ("159922", "中证500ETF 嘉实", "中证500", "SZ"),
    ("512100", "中证1000ETF 南方", "中证1000", "SH"),
    ("159845", "中证1000ETF 华夏", "中证1000", "SZ"),
    ("560010", "中证1000ETF 广发", "中证1000", "SH"),
    ("159629", "中证1000ETF 富国", "中证1000", "SZ"),
    ("159915", "创业板ETF 易方达", "创业板", "SZ"),
    ("159952", "创业板ETF 广发", "创业板", "SZ"),
    ("159977", "创业板ETF 天弘", "创业板", "SZ"),
    ("159949", "创业板50ETF 华安", "创业板50", "SZ"),
    ("588080", "科创板50ETF 易方达", "科创板50", "SH"),
    ("588050", "科创板50ETF 工银", "科创板50", "SH"),
    ("588000", "科创50ETF 华夏", "科创板50", "SH"),
    ("563300", "A500ETF 华泰柏瑞", "中证A500", "SH"),
    ("159338", "中证A500ETF 国泰", "中证A500", "SZ"),
    ("159352", "A500ETF 南方", "中证A500", "SZ"),
    ("159361", "A500ETF 易方达", "中证A500", "SZ"),
    ("510180", "上证180ETF 华安", "上证180", "SH"),
    ("510230", "上证180金融ETF 国泰", "上证180金融", "SH"),
    ("159901", "深证100ETF 易方达", "深证100", "SZ"),
    ("515800", "中证800ETF 汇添富", "中证800", "SH"),
    ("560050", "MSCI中国A50ETF 汇添富", "MSCI中国A50", "SH"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS etf_meta (
    ts_code TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    bucket TEXT NOT NULL,
    exchange TEXT NOT NULL,
    list_date TEXT
);

CREATE TABLE IF NOT EXISTS etf_share_daily (
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    shares_wan REAL,
    adj_shares_wan REAL,
    unit_nav REAL,
    close REAL,
    premium_prev REAL,
    premium_same REAL,
    net_yi REAL,
    split_flag INTEGER DEFAULT 0,
    fetched_at TEXT,
    PRIMARY KEY (ts_code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_etf_share_date ON etf_share_daily(trade_date);

CREATE TABLE IF NOT EXISTS etf_flow_daily (
    trade_date TEXT NOT NULL,
    bucket TEXT NOT NULL,
    net_yi REAL,
    aum_yi REAL,
    n_etf INTEGER,
    n_pos INTEGER,
    breadth_cat INTEGER,
    net5 REAL,
    net20 REAL,
    stage TEXT,
    PRIMARY KEY (trade_date, bucket)
);

CREATE TABLE IF NOT EXISTS etf_benchmark_daily (
    trade_date TEXT PRIMARY KEY,
    close REAL,
    pct_chg REAL
);

CREATE TABLE IF NOT EXISTS etf_index_daily (
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    pct_chg REAL,
    vol REAL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS margin_daily (
    trade_date TEXT PRIMARY KEY,
    rzye_yi REAL,
    rqye_yi REAL,
    rzrqye_yi REAL,
    rzmre_yi REAL,
    rzche_yi REAL,
    source TEXT,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS market_turnover_daily (
    trade_date TEXT PRIMARY KEY,
    sh_yi REAL,
    sz_yi REAL,
    total_yi REAL,
    source TEXT,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS etf_episode (
    episode_id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_date TEXT,
    end_date TEXT,
    peak_date TEXT,
    days INTEGER,
    net_yi_sum REAL,
    idx_start REAL,
    fwd5 REAL,
    fwd20 REAL,
    fwd60 REAL
);
"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def reconfigure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def load_token() -> str:
    # GitHub Actions 用 Secrets；本地用 a-share-agent/.env
    env_token = os.environ.get("TUSHARE_TOKEN")
    if env_token:
        return env_token.strip()
    if ENV_PATH.exists():
        text = ENV_PATH.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"TUSHARE_TOKEN\s*=\s*(.+)", text)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    raise RuntimeError("TUSHARE_TOKEN not found (env or a-share-agent/.env)")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # 兼容已存在的旧表：补 list_date 列
    cols = [row[1] for row in conn.execute("PRAGMA table_info(etf_meta)")]
    if "list_date" not in cols:
        conn.execute("ALTER TABLE etf_meta ADD COLUMN list_date TEXT")
    conn.commit()
    return conn


def ts_code_of(code: str, exchange: str) -> str:
    return f"{code}.{exchange}"


def d8(value: str) -> str:
    return str(value).replace("-", "")[:8]


def date_dash(value: str) -> str:
    value = str(value).replace("-", "")
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 else value


def fmt_yi(value, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value:+,.{digits}f}"


def fmt_pct(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value * 100:+.2f}%"


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------

def fetch_frame(fn, **kwargs) -> pd.DataFrame:
    """带重试的 Tushare 调用；失败返回空表，不中断整轮回填。"""
    last_exc = None
    for attempt in range(3):
        try:
            frame = fn(**kwargs)
            if frame is None:
                return pd.DataFrame()
            return frame
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    print(f"  ! {kwargs.get('ts_code', '')} {last_exc}", file=sys.stderr)
    return pd.DataFrame()


def ingest_one(pro, conn: sqlite3.Connection, ts_code: str, start: str, end: str) -> tuple[int, str]:
    """拉取并计算单只 ETF；返回 (写入行数, 最新日期)。"""
    shares = fetch_frame(
        pro.fund_share, ts_code=ts_code, start_date=start, end_date=end
    )
    if shares.empty:
        return 0, "-"

    nav = fetch_frame(pro.fund_nav, ts_code=ts_code, start_date=start, end_date=end)
    daily = fetch_frame(pro.fund_daily, ts_code=ts_code, start_date=start, end_date=end)

    df = shares.rename(columns={"trade_date": "trade_date", "fd_share": "shares_wan"})
    df = df[["trade_date", "shares_wan"]].copy()
    df["shares_wan"] = pd.to_numeric(df["shares_wan"], errors="coerce")
    df = df.dropna(subset=["shares_wan"]).drop_duplicates("trade_date", keep="last")
    df = df.sort_values("trade_date")

    if not nav.empty and "nav_date" in nav.columns:
        nav = nav[["nav_date", "unit_nav"]].rename(columns={"nav_date": "trade_date"})
        nav = nav.drop_duplicates("trade_date", keep="last")
        nav["unit_nav"] = pd.to_numeric(nav["unit_nav"], errors="coerce")
        df = df.merge(nav, on="trade_date", how="left")
    else:
        df["unit_nav"] = math.nan

    if not daily.empty and "trade_date" in daily.columns:
        dly = daily[["trade_date", "close"]].copy()
        dly["close"] = pd.to_numeric(dly["close"], errors="coerce")
        df = df.merge(dly, on="trade_date", how="left")
    else:
        df["close"] = math.nan

    # 净值/收盘缺失时最多向前补 5 个交易日；份额缺失不补
    df["unit_nav"] = df["unit_nav"].ffill(limit=5)
    df["close"] = df["close"].ffill(limit=5)
    df = df.dropna(subset=["unit_nav"]).reset_index(drop=True)
    if df.empty:
        return 0, "-"

    # 份额折算/合并识别：份额比例与净值比例近似互为倒数
    ratio = df["shares_wan"] / df["shares_wan"].shift(1)
    nav_ratio = df["unit_nav"] / df["unit_nav"].shift(1)
    split = (ratio.sub(1).abs() > 0.15) & ((ratio * nav_ratio - 1).abs() < 0.06)
    k = ratio.where(split, 1.0).fillna(1.0)
    # 份额水平序列按折算比例归一到同一基准（仅用于观察份额水平，不用于算钱）
    df["adj_shares_wan"] = df["shares_wan"] / k.cumprod()
    # 净申赎必须用「当期份额 × 当期净值」：折算日的份额/净值同时跳变，直接置 0；
    # 若用 adj_shares 的差分，会把折算比例带进金额，导致数倍误差。
    df["net_yi"] = df["shares_wan"].diff() * df["unit_nav"] / 1e4
    df.loc[split, "net_yi"] = 0.0
    df["net_yi"] = df["net_yi"].fillna(0.0)
    df["premium_prev"] = df["close"] / df["unit_nav"].shift(1) - 1
    df["premium_same"] = df["close"] / df["unit_nav"] - 1
    df["split_flag"] = split.astype(int)

    now = datetime.now().isoformat(timespec="seconds")
    rows = [
        (
            ts_code,
            date_dash(rec.trade_date),
            float(rec.shares_wan),
            float(rec.adj_shares_wan),
            float(rec.unit_nav),
            None if pd.isna(rec.close) else float(rec.close),
            None if pd.isna(rec.premium_prev) else float(rec.premium_prev),
            None if pd.isna(rec.premium_same) else float(rec.premium_same),
            float(rec.net_yi),
            int(rec.split_flag),
            now,
        )
        for rec in df.itertuples(index=False)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO etf_share_daily("
        "ts_code, trade_date, shares_wan, adj_shares_wan, unit_nav, close, "
        "premium_prev, premium_same, net_yi, split_flag, fetched_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows), date_dash(df["trade_date"].iloc[-1])


def update_meta(conn: sqlite3.Connection) -> None:
    for code, name, bucket, exchange in TARGETS:
        # UPSERT 只更新静态元数据，保留已有的 list_date
        conn.execute(
            "INSERT INTO etf_meta(ts_code, code, name, bucket, exchange) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(ts_code) DO UPDATE SET "
            "code=excluded.code, name=excluded.name, "
            "bucket=excluded.bucket, exchange=excluded.exchange",
            (ts_code_of(code, exchange), code, name, bucket, exchange),
        )
    conn.commit()


def update_list_dates(pro, conn: sqlite3.Connection) -> None:
    """用 Tushare fund_basic 的真实上市日更新 etf_meta.list_date。"""
    frame = fetch_frame(pro.fund_basic, market="E")
    if frame.empty or "list_date" not in frame.columns:
        return
    wanted = {ts_code_of(code, exchange) for code, _, _, exchange in TARGETS}
    for rec in frame.itertuples(index=False):
        if rec.ts_code in wanted and getattr(rec, "list_date", None):
            conn.execute(
                "UPDATE etf_meta SET list_date = ? WHERE ts_code = ?",
                (date_dash(rec.list_date), rec.ts_code),
            )
    conn.commit()


def refresh_list_dates(conn: sqlite3.Connection) -> None:
    """兜底：仅对 fund_basic 没给到的标的，用份额序列首日近似上市日。"""
    conn.execute(
        """
        UPDATE etf_meta
        SET list_date = (
            SELECT MIN(s.trade_date) FROM etf_share_daily s
            WHERE s.ts_code = etf_meta.ts_code
        )
        WHERE list_date IS NULL
        """
    )
    conn.commit()


def ingest_margin(pro, conn: sqlite3.Connection, start: str, end: str) -> None:
    """沪深两市融资余额（融资融券交易汇总），单位亿元。"""
    frame = fetch_frame(pro.margin, start_date=start, end_date=end)
    if frame.empty:
        return
    frame = frame[frame["exchange_id"].isin(["SSE", "SZSE"])].copy()
    if frame.empty:
        return
    frame["trade_date"] = frame["trade_date"].map(date_dash)
    grouped = frame.groupby("trade_date", as_index=False).agg(
        rzye=("rzye", "sum"),
        rqye=("rqye", "sum"),
        rzrqye=("rzrqye", "sum"),
        rzmre=("rzmre", "sum"),
        rzche=("rzche", "sum"),
    )
    now = datetime.now().isoformat(timespec="seconds")
    rows = [
        (
            rec.trade_date,
            float(rec.rzye) / 1e8 if pd.notna(rec.rzye) else None,
            float(rec.rqye) / 1e8 if pd.notna(rec.rqye) else None,
            float(rec.rzrqye) / 1e8 if pd.notna(rec.rzrqye) else None,
            float(rec.rzmre) / 1e8 if pd.notna(rec.rzmre) else None,
            float(rec.rzche) / 1e8 if pd.notna(rec.rzche) else None,
            "tushare_margin",
            now,
        )
        for rec in grouped.itertuples(index=False)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO margin_daily("
        "trade_date, rzye_yi, rqye_yi, rzrqye_yi, rzmre_yi, rzche_yi, "
        "source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    print(f"  融资余额 {len(rows)} 行，最新 {rows[-1][0] if rows else '-'}")


def ingest_turnover(pro, conn: sqlite3.Connection, start: str, end: str) -> None:
    """沪深两市成交额：上证综指(000001.SH) + 深证综指(399106.SZ) 的 amount。"""
    frames = {}
    for code in ("000001.SH", "399106.SZ"):
        frame = fetch_frame(
            pro.index_daily, ts_code=code, start_date=start, end_date=end
        )
        if frame.empty:
            print(f"  ! 成交额 {code} 无数据", file=sys.stderr)
            return
        frames[code] = frame[["trade_date", "amount"]].rename(
            columns={"amount": "sh" if code == "000001.SH" else "sz"}
        )
    merged = frames["000001.SH"].merge(
        frames["399106.SZ"], on="trade_date", how="inner"
    )
    if merged.empty:
        return
    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for rec in merged.itertuples(index=False):
        sh, sz = rec.sh, rec.sz
        if pd.isna(sh) or pd.isna(sz):
            continue
        total = float(sh) + float(sz)
        # Tushare index_daily.amount 单位：千元；1 亿元 = 1e5 千元
        rows.append(
            (
                date_dash(rec.trade_date),
                float(sh) / 1e5,
                float(sz) / 1e5,
                total / 1e5,
                "tushare_index",
                now,
            )
        )
    conn.executemany(
        "INSERT OR REPLACE INTO market_turnover_daily("
        "trade_date, sh_yi, sz_yi, total_yi, source, fetched_at"
        ") VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    print(f"  沪深成交额 {len(rows)} 行，最新 {max(r[0] for r in rows) if rows else '-'}")


def ingest_benchmark(pro, conn: sqlite3.Connection, start: str, end: str) -> None:
    """沪深300（既有图用） + 中证全指（K 线联动图用），均落 OHLC。"""
    for code in (BENCH_CODE, ALLSHARE_CODE):
        frame = fetch_frame(
            pro.index_daily, ts_code=code, start_date=start, end_date=end
        )
        if frame.empty:
            continue
        frame = frame.sort_values("trade_date")
        rows = []
        for rec in frame.itertuples(index=False):
            rows.append(
                (
                    code,
                    date_dash(rec.trade_date),
                    float(rec.open) if pd.notna(rec.open) else None,
                    float(rec.high) if pd.notna(rec.high) else None,
                    float(rec.low) if pd.notna(rec.low) else None,
                    float(rec.close) if pd.notna(rec.close) else None,
                    float(rec.pct_chg) if pd.notna(rec.pct_chg) else None,
                    float(rec.vol) if pd.notna(rec.vol) else None,
                )
            )
        conn.executemany(
            "INSERT OR REPLACE INTO etf_index_daily("
            "ts_code, trade_date, open, high, low, close, pct_chg, vol"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        if code == BENCH_CODE:
            conn.executemany(
                "INSERT OR REPLACE INTO etf_benchmark_daily(trade_date, close, pct_chg) "
                "VALUES (?, ?, ?)",
                [(r[1], r[5], r[6]) for r in rows],
            )
    conn.commit()


# ---------------------------------------------------------------------------
# 聚合与事件
# ---------------------------------------------------------------------------

def rolling_sum(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
        else:
            out.append(sum(values[i + 1 - window : i + 1]))
    return out


def stage_of(last3: list[float], net5: float | None, net20: float | None,
             net_yi: float, breadth: int) -> str:
    # 2 日转弱但 5 日仍为正：本轮最常见的“阶段二后段 → 阶段三”过渡形态
    if len(last3) >= 2 and all(v < 0 for v in last3[-2:]) and (net5 or 0) > 0:
        return "转弱观察"
    if len(last3) >= 3 and all(v > 0 for v in last3) and sum(v > 50 for v in last3) >= 2 and breadth >= 3:
        return "连续流入"
    if net_yi >= 200:
        return "脉冲"
    if len(last3) >= 3 and all(v <= 0 for v in last3):
        return "静默/流出"
    if net5 is not None and net5 > 0:
        return "偏流入"
    return "中性"


def rebuild_flow(conn: sqlite3.Connection) -> None:
    """从 etf_share_daily 重建 etf_flow_daily（分类 + ALL 合计）。"""
    conn.execute("DELETE FROM etf_flow_daily")
    rows = conn.execute(
        """
        SELECT s.trade_date, m.bucket,
               SUM(s.net_yi) AS net_yi,
               SUM(s.shares_wan * s.unit_nav / 1e4) AS aum_yi,
               COUNT(*) AS n_etf,
               SUM(CASE WHEN s.net_yi > 0 THEN 1 ELSE 0 END) AS n_pos
        FROM etf_share_daily s
        JOIN etf_meta m ON m.ts_code = s.ts_code
        JOIN etf_benchmark_daily b ON b.trade_date = s.trade_date
        WHERE m.list_date IS NULL
           OR s.trade_date >= date(m.list_date, '+30 day')
        GROUP BY s.trade_date, m.bucket
        ORDER BY s.trade_date
        """
    ).fetchall()

    by_date: dict[str, dict] = {}
    for row in rows:
        d = row["trade_date"]
        item = by_date.setdefault(
            d,
            {"net": 0.0, "aum": 0.0, "n": 0, "n_pos": 0, "breadth": 0, "cats": []},
        )
        item["net"] += row["net_yi"] or 0.0
        item["aum"] += row["aum_yi"] or 0.0
        item["n"] += row["n_etf"] or 0
        item["n_pos"] += row["n_pos"] or 0
        if (row["net_yi"] or 0.0) > 0:
            item["breadth"] += 1
        item["cats"].append(row)

    dates = sorted(by_date)
    nets = [by_date[d]["net"] for d in dates]
    net5 = rolling_sum(nets, 5)
    net20 = rolling_sum(nets, 20)

    inserts: list[tuple] = []
    for i, d in enumerate(dates):
        item = by_date[d]
        breadth = item["breadth"]
        last3 = nets[max(0, i - 2) : i + 1]
        stage = stage_of(last3, net5[i], net20[i], item["net"], breadth)
        inserts.append(
            (
                d, "ALL", item["net"], item["aum"], item["n"], item["n_pos"],
                breadth, net5[i], net20[i], stage,
            )
        )

    # 分类行：每个分类独立计算 5/20 日累计；stage 留空，由 ALL 行承担阶段判断
    row_map = {(r["trade_date"], r["bucket"]): r for r in rows}
    cat_values: dict[str, list[float]] = {}
    cat_dates: dict[str, list[str]] = {}
    for row in rows:
        bucket = row["bucket"]
        cat_dates.setdefault(bucket, []).append(row["trade_date"])
        cat_values.setdefault(bucket, []).append(row["net_yi"] or 0.0)
    for bucket in cat_dates:
        vals = cat_values[bucket]
        s5 = rolling_sum(vals, 5)
        s20 = rolling_sum(vals, 20)
        for i, d in enumerate(cat_dates[bucket]):
            row = row_map[(d, bucket)]
            inserts.append(
                (
                    d, bucket, row["net_yi"], row["aum_yi"], row["n_etf"],
                    row["n_pos"], None, s5[i], s20[i], None,
                )
            )

    conn.executemany(
        "INSERT OR REPLACE INTO etf_flow_daily("
        "trade_date, bucket, net_yi, aum_yi, n_etf, n_pos, breadth_cat, "
        "net5, net20, stage) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        inserts,
    )
    conn.commit()


def rebuild_episodes(conn: sqlite3.Connection, threshold: float = 100.0) -> None:
    """把连续的大额流入日合并成 episode，并计算事件后 5/20/60 日指数收益。"""
    conn.execute("DELETE FROM etf_episode")
    rows = conn.execute(
        "SELECT trade_date, net_yi FROM etf_flow_daily "
        "WHERE bucket = 'ALL' ORDER BY trade_date"
    ).fetchall()
    bench_rows = conn.execute(
        "SELECT trade_date, close FROM etf_benchmark_daily ORDER BY trade_date"
    ).fetchall()
    bench = {r["trade_date"]: r["close"] for r in bench_rows}
    bench_dates = [r["trade_date"] for r in bench_rows]

    signal_days = [(i, r) for i, r in enumerate(rows) if (r["net_yi"] or 0) >= threshold]
    groups: list[list[tuple[int, sqlite3.Row]]] = []
    current: list[tuple[int, sqlite3.Row]] = []
    for idx, row in signal_days:
        if current and idx - current[-1][0] > 2:
            groups.append(current)
            current = []
        current.append((idx, row))
    if current:
        groups.append(current)

    def forward_return(start_date: str, horizon: int) -> float | None:
        if start_date not in bench:
            return None
        pos = bench_dates.index(start_date)
        if pos + horizon >= len(bench_dates):
            return None
        end_date = bench_dates[pos + horizon]
        start_close, end_close = bench[start_date], bench[end_date]
        if not start_close or not end_close:
            return None
        return end_close / start_close - 1

    inserts = []
    for group in groups:
        start = group[0][1]["trade_date"]
        end = group[-1][1]["trade_date"]
        peak_row = max(group, key=lambda x: x[1]["net_yi"] or 0)
        total = sum((x[1]["net_yi"] or 0) for x in group)
        inserts.append(
            (
                start, end, peak_row[1]["trade_date"], len(group), total,
                bench.get(start),
                forward_return(start, 5),
                forward_return(start, 20),
                forward_return(start, 60),
            )
        )

    conn.executemany(
        "INSERT INTO etf_episode("
        "start_date, end_date, peak_date, days, net_yi_sum, idx_start, "
        "fwd5, fwd20, fwd60) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        inserts,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# SVG 图表
# ---------------------------------------------------------------------------

def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        return [lo]
    step = (hi - lo) / (n - 1)
    return [lo + step * i for i in range(n)]


def svg_daily_bars(df: pd.DataFrame, bench: pd.DataFrame) -> str:
    """净申赎柱状图 + 沪深 300 折线（双轴）。"""
    width, height = 1180, 430
    ml, mr, mt, mb = 74, 78, 34, 44
    x0, x1, y0, y1 = ml, width - mr, mt, height - mb
    dates = df["trade_date"].tolist()
    nets = [float(v or 0) for v in df["net_yi"].tolist()]
    n = max(len(dates), 1)
    m = max(max(abs(v) for v in nets), 1.0)
    zero = (y0 + y1) / 2

    def y(v: float) -> float:
        return zero - v / m * (y1 - y0) / 2

    bmap = dict(zip(bench["trade_date"], bench["close"]))
    idx_vals = [bmap.get(d) for d in dates]
    valid = [v for v in idx_vals if v is not None]
    if valid:
        imin, imax = min(valid), max(valid)
        pad = (imax - imin) * 0.06 or 1
        imin, imax = imin - pad, imax + pad
    else:
        imin, imax = 0, 1

    def iy(v: float) -> float:
        return y1 - (v - imin) / (imax - imin) * (y1 - y0)

    def x(i: int) -> float:
        return x0 + (i + 0.5) * (x1 - x0) / n

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="每日净申赎与沪深300">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="none"/>',
    ]

    for tick in _nice_ticks(-m, m, 5):
        yy = y(tick)
        parts.append(
            f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" '
            f'stroke="var(--line)" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x0-8}" y="{yy+4:.1f}" text-anchor="end" '
            f'fill="var(--muted)" font-size="11">{tick:+.0f}</text>'
        )
    if valid:
        for tick in _nice_ticks(imin, imax, 5):
            yy = iy(tick)
            parts.append(
                f'<text x="{x1+8}" y="{yy+4:.1f}" fill="var(--muted)" '
                f'font-size="11">{tick:,.0f}</text>'
            )

    bw = max(1.0, (x1 - x0) / n * 0.72)
    for i, (d, v) in enumerate(zip(dates, nets)):
        yy = y(max(v, 0))
        hh = abs(y(v) - zero)
        color = "var(--pos)" if v >= 0 else "var(--neg)"
        title = f"{d} 净申赎 {v:+.1f} 亿"
        if idx_vals[i] is not None:
            title += f" · 沪深300 {idx_vals[i]:,.0f}"
        parts.append(
            f'<rect x="{x(i)-bw/2:.1f}" y="{yy:.1f}" width="{bw:.1f}" '
            f'height="{hh:.1f}" fill="{color}" opacity="0.82">'
            f"<title>{title}</title></rect>"
        )

    pts = [
        f"{x(i):.1f},{iy(v):.1f}"
        for i, v in enumerate(idx_vals)
        if v is not None
    ]
    if len(pts) > 1:
        parts.append(
            f'<polyline points="{" ".join(pts)}" fill="none" '
            f'stroke="var(--blue)" stroke-width="1.6" opacity="0.9"/>'
        )

    for i in range(0, n, max(1, n // 8)):
        parts.append(
            f'<text x="{x(i):.1f}" y="{height-16}" text-anchor="middle" '
            f'fill="var(--muted)" font-size="11">{dates[i][2:]}</text>'
        )

    parts.append(
        f'<text x="{x0}" y="18" fill="var(--muted)" font-size="12">'
        f"左轴：净申赎（亿元）　右轴：沪深300　蓝线</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def svg_cum_line(df: pd.DataFrame, window: int = 20) -> str:
    """滚动累计净申赎折线。"""
    width, height = 1180, 300
    ml, mr, mt, mb = 74, 78, 28, 40
    x0, x1, y0, y1 = ml, width - mr, mt, height - mb
    vals = [float(v or 0) for v in df["net_yi"].tolist()]
    dates = df["trade_date"].tolist()
    cum = rolling_sum(vals, window)
    points = [(d, v) for d, v in zip(dates, cum) if v is not None]
    if not points:
        return ""
    n = len(points)
    lo = min(min(v for _, v in points), 0)
    hi = max(max(v for _, v in points), 0)
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad

    def x(i: int) -> float:
        return x0 + i * (x1 - x0) / max(n - 1, 1)

    def y(v: float) -> float:
        return y1 - (v - lo) / (hi - lo) * (y1 - y0)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{window}日累计净申赎">']
    for tick in _nice_ticks(lo, hi, 5):
        yy = y(tick)
        parts.append(
            f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" '
            f'stroke="var(--line)" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x0-8}" y="{yy+4:.1f}" text-anchor="end" '
            f'fill="var(--muted)" font-size="11">{tick:+.0f}</text>'
        )
    yz = y(0)
    parts.append(
        f'<line x1="{x0}" y1="{yz:.1f}" x2="{x1}" y2="{yz:.1f}" '
        f'stroke="var(--muted)" stroke-width="1" stroke-dasharray="4 3"/>'
    )
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(points))
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="var(--blue)" stroke-width="2"/>'
    )
    for i in range(0, n, max(1, n // 8)):
        parts.append(
            f'<text x="{x(i):.1f}" y="{height-14}" text-anchor="middle" '
            f'fill="var(--muted)" font-size="11">{points[i][0][2:]}</text>'
        )
    parts.append(
        f'<text x="{x0}" y="16" fill="var(--muted)" font-size="12">'
        f"{window} 日滚动累计净申赎（亿元）</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def svg_cat_bars(cat_df: pd.DataFrame, asof: str) -> str:
    """最新交易日各分类的 20 日累计净申赎横向条形图。"""
    rows = cat_df[cat_df["trade_date"] == asof].copy()
    if rows.empty:
        return ""
    rows = rows.sort_values("net20", ascending=False)
    width = 1180
    row_h = 30
    top, bottom, left, right = 26, 12, 128, 96
    height = top + bottom + row_h * len(rows)
    x0, x1 = left, width - right
    vmax = max(max(abs(v or 0) for v in rows["net20"]), 1.0)
    zero = x0 + (x1 - x0) / 2

    def x(v: float) -> float:
        return zero + (v / vmax) * (x1 - x0) / 2

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="分类20日累计净申赎">']
    parts.append(
        f'<line x1="{zero}" y1="{top-6}" x2="{zero}" y2="{height-bottom}" '
        f'stroke="var(--muted)" stroke-width="1" stroke-dasharray="4 3"/>'
    )
    for i, rec in enumerate(rows.itertuples(index=False)):
        yy = top + i * row_h
        v = float(rec.net20 or 0)
        color = "var(--pos)" if v >= 0 else "var(--neg)"
        bx = min(zero, x(v))
        bw = abs(x(v) - zero)
        parts.append(
            f'<text x="{left-10}" y="{yy+row_h*0.65:.1f}" text-anchor="end" '
            f'fill="var(--text)" font-size="12.5">{rec.bucket}</text>'
        )
        parts.append(
            f'<rect x="{bx:.1f}" y="{yy+5}" width="{bw:.1f}" height="{row_h-12}" '
            f'fill="{color}" opacity="0.82"><title>{rec.bucket} {v:+.1f} 亿</title></rect>'
        )
        label_x = x(v) + (6 if v >= 0 else -6)
        anchor = "start" if v >= 0 else "end"
        parts.append(
            f'<text x="{label_x:.1f}" y="{yy+row_h*0.65:.1f}" text-anchor="{anchor}" '
            f'fill="var(--muted)" font-size="11.5">{v:+.1f}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# HTML 报表
# ---------------------------------------------------------------------------

def svg_aum_line(df: pd.DataFrame, start_date: str = "2024-01-01") -> str:
    """全表持仓市值（Σ份额×净值）折线图，默认 2024 至今。"""
    d = df[df["trade_date"] >= start_date].copy()
    if d.empty:
        return ""
    width, height = 1180, 300
    ml, mr, mt, mb = 74, 78, 28, 40
    x0, x1, y0, y1 = ml, width - mr, mt, height - mb
    dates = d["trade_date"].tolist()
    vals = [float(v or 0) for v in d["aum_yi"].tolist()]
    n = len(vals)
    if n < 2:
        return ""
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad

    def x(i: int) -> float:
        return x0 + i * (x1 - x0) / (n - 1)

    def y(v: float) -> float:
        return y1 - (v - lo) / (hi - lo) * (y1 - y0)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="持仓金额">']
    for tick in _nice_ticks(lo, hi, 5):
        yy = y(tick)
        parts.append(
            f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" '
            f'stroke="var(--line)" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x0-8}" y="{yy+4:.1f}" text-anchor="end" '
            f'fill="var(--muted)" font-size="11">{tick:,.0f}</text>'
        )

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
    area = f"{x(0):.1f},{y1:.1f} {pts} {x(n-1):.1f},{y1:.1f}"
    parts.append(f'<polygon points="{area}" fill="var(--blue)" opacity="0.08"/>')
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="var(--blue)" stroke-width="2"/>'
    )
    parts.append(
        f'<circle cx="{x(n-1):.1f}" cy="{y(vals[-1]):.1f}" r="3.5" fill="var(--blue)"/>'
    )
    parts.append(
        f'<text x="{x(n-1)-4:.1f}" y="{y(vals[-1])-10:.1f}" text-anchor="end" '
        f'fill="var(--text)" font-size="12" font-weight="600">{vals[-1]:,.0f} 亿</text>'
    )
    for idx, label in ((vals.index(max(vals)), "高"), (vals.index(min(vals)), "低")):
        parts.append(
            f'<text x="{x(idx):.1f}" y="{y(vals[idx])-8:.1f}" text-anchor="middle" '
            f'fill="var(--muted)" font-size="10.5">{label} {vals[idx]:,.0f}</text>'
        )
    for i, v in enumerate(vals):
        parts.append(
            f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="6" fill="transparent">'
            f"<title>{dates[i]} 持仓 {v:,.0f} 亿</title></circle>"
        )
    for i in range(0, n, max(1, n // 8)):
        parts.append(
            f'<text x="{x(i):.1f}" y="{height-14}" text-anchor="middle" '
            f'fill="var(--muted)" font-size="11">{dates[i][2:]}</text>'
        )
    parts.append(
        f'<text x="{x0}" y="16" fill="var(--muted)" font-size="12">'
        f"持仓金额（亿元）· 悬停查看当日</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def kline_section(idx: pd.DataFrame, flow: pd.DataFrame) -> str:
    """中证全指 K 线 + 每日净申赎联动（ECharts，2024 至今）。"""
    if idx.empty:
        return (
            '<section class="card"><h2>指数K线 × 每日净买入联动（2024 至今）</h2>'
            '<p class="note">指数数据缺失：先运行 <code>--refresh-benchmark</code>。</p></section>'
        )
    d = idx.merge(flow[["trade_date", "net_yi"]], on="trade_date", how="left")
    d = d[d["trade_date"] >= "2024-01-01"].sort_values("trade_date")
    d = d.dropna(subset=["open", "high", "low", "close"])
    if d.empty:
        return (
            '<section class="card"><h2>指数K线 × 每日净买入联动（2024 至今）</h2>'
            '<p class="note">2024 年之后没有可用 K 线数据。</p></section>'
        )
    rows = [
        {
            "d": r.trade_date,
            "o": round(float(r.open), 2),
            "h": round(float(r.high), 2),
            "l": round(float(r.low), 2),
            "c": round(float(r.close), 2),
            "q": round(float(r.net_yi or 0), 1),
        }
        for r in d.itertuples(index=False)
    ]
    data_json = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    template = r"""<section class="card">
  <h2>指数K线 × 每日净买入联动（2024 至今）</h2>
  <p class="note">上：中证全指日K；下：29 只 ETF 当日净申赎合计。悬停联动查看；红涨绿跌，红柱净买入、绿柱净卖出。K线图用 ECharts（需联网），其余图表离线可看。</p>
  <div class="klnctl">
    <span class="kp">显示范围</span>
    <button class="rng" data-n="60">60日</button>
    <button class="rng" data-n="120">120日</button>
    <button class="rng" data-n="250">250日</button>
    <button class="rng sel" data-n="0">全部</button>
    <span class="kpt" id="klnDate"></span>
  </div>
  <div id="klineChart" style="height:560px;width:100%"></div>
  <div id="klineFallback" class="note" style="display:none">ECharts 未加载（需联网）；K线图不可用，其余图表正常。</div>
  <script>
  (function () {
    const K = __DATA__;
    const box = document.getElementById('klineChart');
    const fallback = document.getElementById('klineFallback');
    const dateEl = document.getElementById('klnDate');

    function init() {
      if (!window.echarts || !K.length) {
        box.style.display = 'none';
        fallback.style.display = 'block';
        return;
      }
      const chart = echarts.init(box);
      const dates = K.map(function (x) { return x.d; });
      const candles = K.map(function (x) { return [x.o, x.c, x.l, x.h]; });
      const flows = K.map(function (x) { return x.q; });

      function option(n) {
        const total = K.length;
        const start = n > 0 ? Math.max(0, (1 - n / total) * 100) : 0;
        return {
          animation: false,
          axisPointer: { link: [{ xAxisIndex: [0, 1] }], lineStyle: { color: '#98a2b8' } },
          grid: [
            { left: 58, right: 64, top: 18, height: 300 },
            { left: 58, right: 64, top: 348, height: 118 }
          ],
          xAxis: [
            { type: 'category', data: dates, gridIndex: 0, boundaryGap: true,
              axisLabel: { show: false }, axisTick: { show: false },
              axisLine: { lineStyle: { color: '#c9cfdd' } } },
            { type: 'category', data: dates, gridIndex: 1, boundaryGap: true,
              axisLabel: { color: '#7a8194', fontSize: 10 }, axisTick: { show: false },
              axisLine: { lineStyle: { color: '#c9cfdd' } } }
          ],
          yAxis: [
            { scale: true, gridIndex: 0, position: 'right',
              splitLine: { lineStyle: { color: '#eef1f6' } },
              axisLabel: { color: '#7a8194', fontSize: 10 } },
            { scale: true, gridIndex: 1, position: 'right',
              splitLine: { show: false },
              axisLabel: { color: '#7a8194', fontSize: 10 } }
          ],
          dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1], start: start, end: 100 },
            { type: 'slider', xAxisIndex: [0, 1], bottom: 4, height: 18,
              start: start, end: 100, brushSelect: false }
          ],
          tooltip: {
            trigger: 'axis', axisPointer: { type: 'cross' }, confine: true,
            formatter: function (ps) {
              if (!ps || !ps.length) return '';
              const i = ps[0].dataIndex;
              const r = K[i];
              if (!r) return '';
              const col = r.q >= 0 ? '#d64545' : '#2e8b57';
              return '<b>' + r.d + '</b><br>开 ' + r.o + '　高 ' + r.h +
                     '　低 ' + r.l + '　收 ' + r.c +
                     '<br>净申赎 <b style="color:' + col + '">' +
                     (r.q >= 0 ? '+' : '') + r.q.toFixed(1) + ' 亿</b>';
            }
          },
          series: [
            { name: '中证全指', type: 'candlestick', data: candles,
              itemStyle: { color: '#d64545', color0: '#2e8b57',
                           borderColor: '#d64545', borderColor0: '#2e8b57' } },
            { name: '净申赎', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: flows,
              itemStyle: { color: function (p) { return p.value >= 0 ? '#d64545' : '#2e8b57'; } } }
          ]
        };
      }

      let cur = 0;
      function apply(n) {
        cur = n;
        chart.setOption(option(n));
        dateEl.textContent = n > 0 ? ('最近 ' + n + ' 个交易日') : ('全部 ' + K.length + ' 个交易日');
      }
      apply(cur);
      document.querySelectorAll('.rng').forEach(function (b) {
        b.addEventListener('click', function () {
          document.querySelectorAll('.rng').forEach(function (x) {
            x.classList.toggle('sel', x === b);
          });
          apply(parseInt(b.dataset.n, 10));
        });
      });
      window.addEventListener('resize', function () { chart.resize(); });
    }

    const srcs = [
      'https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js',
      'https://unpkg.com/echarts@5/dist/echarts.min.js'
    ];
    let i = 0;
    function next() {
      if (i >= srcs.length) {
        box.style.display = 'none';
        fallback.style.display = 'block';
        return;
      }
      const s = document.createElement('script');
      s.src = srcs[i++];
      s.onload = init;
      s.onerror = next;
      document.head.appendChild(s);
    }
    next();
  })();
  </script>
</section>"""
    return template.replace("__DATA__", data_json)


def kline_section_margin(idx: pd.DataFrame, flow: pd.DataFrame,
                         margin: pd.DataFrame) -> str:
    """三栏联动：中证全指 K 线 / 每日净申赎 / 融资余额。"""
    if idx.empty or margin.empty:
        return kline_section(idx, flow)
    d = idx.merge(flow[["trade_date", "net_yi"]], on="trade_date", how="left")
    d = d.merge(margin[["trade_date", "rzye_yi"]], on="trade_date", how="left")
    d = d[d["trade_date"] >= "2024-01-01"].sort_values("trade_date")
    d = d.dropna(subset=["open", "high", "low", "close"])
    if d.empty or d["rzye_yi"].notna().sum() == 0:
        return kline_section(idx, flow)
    d["dm"] = d["rzye_yi"].diff()

    valid = d.dropna(subset=["net_yi", "dm"])
    corr = valid["net_yi"].corr(valid["dm"]) if len(valid) >= 20 else None
    recent = d.tail(20)
    corr20 = (
        recent["net_yi"].corr(recent["dm"])
        if recent["dm"].notna().sum() >= 10
        else None
    )
    if corr is None or pd.isna(corr):
        corr_text = "融资余额数据不足，暂不计算相关系数"
    else:
        corr_text = f"2024 至今：ETF 净买入 vs Δ融资余额 相关系数 {corr:+.2f}"
        if corr20 is not None and not pd.isna(corr20):
            corr_text += f"；近 20 日 {corr20:+.2f}"

    rows = [
        {
            "d": r.trade_date,
            "o": round(float(r.open), 2),
            "h": round(float(r.high), 2),
            "l": round(float(r.low), 2),
            "c": round(float(r.close), 2),
            "q": round(float(r.net_yi or 0), 1),
            "m": None if pd.isna(r.rzye_yi) else round(float(r.rzye_yi), 1),
            "dm": None if pd.isna(r.dm) else round(float(r.dm), 1),
        }
        for r in d.itertuples(index=False)
    ]
    data_json = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    template = r"""<section class="card">
  <h2>指数K线 × 每日净买入 × 融资余额联动（2024 至今）</h2>
  <p class="note">上：中证全指日K；中：29 只 ETF 当日净申赎；下：沪深两市融资余额。悬停联动查看；红涨绿跌，红柱净买入、绿柱净卖出。K线图用 ECharts（需联网），其余图表离线可看。</p>
  <p class="note"><b>__CORR__</b>　融资余额为沪深两市合计（不含北交所），T+1 披露。</p>
  <div class="klnctl">
    <span class="kp">显示范围</span>
    <button class="rng" data-n="60">60日</button>
    <button class="rng" data-n="120">120日</button>
    <button class="rng" data-n="250">250日</button>
    <button class="rng sel" data-n="0">全部</button>
    <span class="kpt" id="klnDate"></span>
  </div>
  <div id="klineChart" style="height:__HEIGHT__px;width:100%"></div>
  <div id="klineFallback" class="note" style="display:none">ECharts 未加载（需联网）；K线图不可用，其余图表正常。</div>
  <script>
  (function () {
    const K = __DATA__;
    const box = document.getElementById('klineChart');
    const fallback = document.getElementById('klineFallback');
    const dateEl = document.getElementById('klnDate');

    function init() {
      if (!window.echarts || !K.length) {
        box.style.display = 'none';
        fallback.style.display = 'block';
        return;
      }
      const chart = echarts.init(box);
      const dates = K.map(function (x) { return x.d; });
      const candles = K.map(function (x) { return [x.o, x.c, x.l, x.h]; });
      const flows = K.map(function (x) { return x.q; });
      const margins = K.map(function (x) { return x.m; });

      function option(n) {
        const total = K.length;
        const start = n > 0 ? Math.max(0, (1 - n / total) * 100) : 0;
        return {
          animation: false,
          legend: { top: 0, right: 74, itemWidth: 14, itemHeight: 8,
            textStyle: { color: '#7a8194', fontSize: 11 },
            data: ['中证全指', '净申赎', '融资余额'] },
          axisPointer: { link: [{ xAxisIndex: [0, 1, 2] }], lineStyle: { color: '#98a2b8' } },
          grid: [
            { left: 58, right: 70, top: 26, height: 240 },
            { left: 58, right: 70, top: 286, height: 90 },
            { left: 58, right: 70, top: 396, height: 170 }
          ],
          xAxis: [
            { type: 'category', data: dates, gridIndex: 0, boundaryGap: true,
              axisLabel: { show: false }, axisTick: { show: false },
              axisLine: { lineStyle: { color: '#c9cfdd' } } },
            { type: 'category', data: dates, gridIndex: 1, boundaryGap: true,
              axisLabel: { show: false }, axisTick: { show: false },
              axisLine: { lineStyle: { color: '#c9cfdd' } } },
            { type: 'category', data: dates, gridIndex: 2, boundaryGap: true,
              axisLabel: { color: '#7a8194', fontSize: 10 }, axisTick: { show: false },
              axisLine: { lineStyle: { color: '#c9cfdd' } } }
          ],
          yAxis: [
            { scale: true, gridIndex: 0, position: 'right',
              splitLine: { lineStyle: { color: '#eef1f6' } },
              axisLabel: { color: '#7a8194', fontSize: 10 } },
            { scale: true, gridIndex: 1, position: 'right',
              splitLine: { show: false },
              axisLabel: { color: '#7a8194', fontSize: 10 } },
            { scale: true, gridIndex: 2, position: 'right',
              splitLine: { show: false },
              axisLabel: { color: '#7a8194', fontSize: 10,
                formatter: function (v) { return v.toFixed(0); } } }
          ],
          dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1, 2], start: start, end: 100 },
            { type: 'slider', xAxisIndex: [0, 1, 2], bottom: 4, height: 18,
              start: start, end: 100, brushSelect: false }
          ],
          tooltip: {
            trigger: 'axis', axisPointer: { type: 'cross' }, confine: true,
            formatter: function (ps) {
              if (!ps || !ps.length) return '';
              const r = K[ps[0].dataIndex];
              if (!r) return '';
              const qcol = r.q >= 0 ? '#d64545' : '#2e8b57';
              let s = '<b>' + r.d + '</b><br>开 ' + r.o + '　高 ' + r.h +
                      '　低 ' + r.l + '　收 ' + r.c;
              s += '<br>净申赎 <b style="color:' + qcol + '">' +
                   (r.q >= 0 ? '+' : '') + r.q.toFixed(1) + ' 亿</b>';
              if (r.m != null) {
                s += '<br>融资余额 <b>' + r.m.toFixed(0) + ' 亿</b>';
                if (r.dm != null) {
                  const dcol = r.dm >= 0 ? '#d64545' : '#2e8b57';
                  s += '　Δ <b style="color:' + dcol + '">' +
                       (r.dm >= 0 ? '+' : '') + r.dm.toFixed(1) + ' 亿</b>';
                }
              }
              return s;
            }
          },
          series: [
            { name: '中证全指', type: 'candlestick', data: candles,
              itemStyle: { color: '#d64545', color0: '#2e8b57',
                           borderColor: '#d64545', borderColor0: '#2e8b57' } },
            { name: '净申赎', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: flows,
              itemStyle: { color: function (p) { return p.value >= 0 ? '#d64545' : '#2e8b57'; } } },
            { name: '融资余额', type: 'line', xAxisIndex: 2, yAxisIndex: 2,
              data: margins, connectNulls: true, showSymbol: false,
              lineStyle: { width: 1.8, color: '#8e44ad' },
              itemStyle: { color: '#8e44ad' } }
          ]
        };
      }

      let cur = 0;
      function apply(n) {
        cur = n;
        chart.setOption(option(n));
        dateEl.textContent = n > 0 ? ('最近 ' + n + ' 个交易日') : ('全部 ' + K.length + ' 个交易日');
      }
      apply(cur);
      document.querySelectorAll('.rng').forEach(function (b) {
        b.addEventListener('click', function () {
          document.querySelectorAll('.rng').forEach(function (x) {
            x.classList.toggle('sel', x === b);
          });
          apply(parseInt(b.dataset.n, 10));
        });
      });
      window.addEventListener('resize', function () { chart.resize(); });
    }

    const srcs = [
      'https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js',
      'https://unpkg.com/echarts@5/dist/echarts.min.js'
    ];
    let i = 0;
    function next() {
      if (i >= srcs.length) {
        box.style.display = 'none';
        fallback.style.display = 'block';
        return;
      }
      const s = document.createElement('script');
      s.src = srcs[i++];
      s.onload = init;
      s.onerror = next;
      document.head.appendChild(s);
    }
    next();
  })();
  </script>
</section>"""
    return (
        template.replace("__DATA__", data_json)
        .replace("__HEIGHT__", "640")
        .replace("__CORR__", corr_text)
    )


def kline_section_full(idx: pd.DataFrame, flow: pd.DataFrame,
                       margin: pd.DataFrame, turnover: pd.DataFrame) -> str:
    """四栏联动：K线 / 每日净申赎 / 沪深成交额 / 融资余额。"""
    if idx.empty or margin.empty or turnover.empty:
        return kline_section_margin(idx, flow, margin)
    d = idx.merge(flow[["trade_date", "net_yi"]], on="trade_date", how="left")
    d = d.merge(margin[["trade_date", "rzye_yi"]], on="trade_date", how="left")
    d = d.merge(turnover[["trade_date", "total_yi"]], on="trade_date", how="left")
    d = d[d["trade_date"] >= "2024-01-01"].sort_values("trade_date")
    d = d.dropna(subset=["open", "high", "low", "close"])
    if d.empty or d["total_yi"].notna().sum() == 0:
        return kline_section_margin(idx, flow, margin)
    d["dm"] = d["rzye_yi"].diff()
    d["dt"] = d["total_yi"].diff()
    d["tma20"] = d["total_yi"].rolling(20).mean()

    valid = d.dropna(subset=["net_yi", "dm"])
    corr = valid["net_yi"].corr(valid["dm"]) if len(valid) >= 20 else None
    recent = d.tail(20)
    corr20 = (
        recent["net_yi"].corr(recent["dm"])
        if recent["dm"].notna().sum() >= 10
        else None
    )
    if corr is None or pd.isna(corr):
        corr_text = "融资余额数据不足，暂不计算相关系数"
    else:
        corr_text = f"2024 至今：ETF 净买入 vs Δ融资余额 相关系数 {corr:+.2f}"
        if corr20 is not None and not pd.isna(corr20):
            corr_text += f"；近 20 日 {corr20:+.2f}"

    rows = [
        {
            "d": r.trade_date,
            "o": round(float(r.open), 2),
            "h": round(float(r.high), 2),
            "l": round(float(r.low), 2),
            "c": round(float(r.close), 2),
            "q": round(float(r.net_yi or 0), 1),
            "t": None if pd.isna(r.total_yi) else round(float(r.total_yi), 1),
            "dt": None if pd.isna(r.dt) else round(float(r.dt), 1),
            "tma": None if pd.isna(r.tma20) else round(float(r.tma20), 1),
            "m": None if pd.isna(r.rzye_yi) else round(float(r.rzye_yi), 1),
            "dm": None if pd.isna(r.dm) else round(float(r.dm), 1),
        }
        for r in d.itertuples(index=False)
    ]
    data_json = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    template = r"""<section class="card">
  <h2>指数K线 × 每日净买入 × 沪深成交额 × 融资余额联动（2024 至今）</h2>
  <p class="note">上：中证全指日K；中：29 只 ETF 当日净申赎；下：沪深两市成交额（红=放量、绿=缩量，橙虚线=20日均额）；底：沪深两市融资余额。悬停联动查看；红涨绿跌，红柱净买入、绿柱净卖出。K线图用 ECharts（需联网），其余图表离线可看。</p>
  <p class="note"><b>__CORR__</b>　融资余额为沪深两市合计（不含北交所），T+1 披露；成交额为沪深两市合计。</p>
  <div class="klnctl">
    <span class="kp">显示范围</span>
    <button class="rng" data-n="60">60日</button>
    <button class="rng" data-n="120">120日</button>
    <button class="rng" data-n="250">250日</button>
    <button class="rng sel" data-n="0">全部</button>
    <span class="kpt" id="klnDate"></span>
  </div>
  <div id="klineChart" style="height:640px;width:100%"></div>
  <div id="klineFallback" class="note" style="display:none">ECharts 未加载（需联网）；K线图不可用，其余图表正常。</div>
  <script>
  (function () {
    const K = __DATA__;
    const box = document.getElementById('klineChart');
    const fallback = document.getElementById('klineFallback');
    const dateEl = document.getElementById('klnDate');

    function init() {
      if (!window.echarts || !K.length) {
        box.style.display = 'none';
        fallback.style.display = 'block';
        return;
      }
      const chart = echarts.init(box);
      const dates = K.map(function (x) { return x.d; });
      const candles = K.map(function (x) { return [x.o, x.c, x.l, x.h]; });
      const flows = K.map(function (x) { return x.q; });
      const turnovers = K.map(function (x) { return x.t; });
      const turnoverMa = K.map(function (x) { return x.tma; });
      const margins = K.map(function (x) { return x.m; });

      function option(n) {
        const total = K.length;
        const start = n > 0 ? Math.max(0, (1 - n / total) * 100) : 0;
        return {
          animation: false,
          legend: { top: 0, right: 74, itemWidth: 14, itemHeight: 8,
            textStyle: { color: '#7a8194', fontSize: 11 },
            data: ['中证全指', '净申赎', '沪深成交额', '融资余额'] },
          axisPointer: { link: [{ xAxisIndex: [0, 1, 2, 3] }], lineStyle: { color: '#98a2b8' } },
          grid: [
            { left: 58, right: 70, top: 26, height: 220 },
            { left: 58, right: 70, top: 266, height: 80 },
            { left: 58, right: 70, top: 366, height: 90 },
            { left: 58, right: 70, top: 476, height: 110 }
          ],
          xAxis: [
            { type: 'category', data: dates, gridIndex: 0, boundaryGap: true,
              axisLabel: { show: false }, axisTick: { show: false },
              axisLine: { lineStyle: { color: '#c9cfdd' } } },
            { type: 'category', data: dates, gridIndex: 1, boundaryGap: true,
              axisLabel: { show: false }, axisTick: { show: false },
              axisLine: { lineStyle: { color: '#c9cfdd' } } },
            { type: 'category', data: dates, gridIndex: 2, boundaryGap: true,
              axisLabel: { show: false }, axisTick: { show: false },
              axisLine: { lineStyle: { color: '#c9cfdd' } } },
            { type: 'category', data: dates, gridIndex: 3, boundaryGap: true,
              axisLabel: { color: '#7a8194', fontSize: 10 }, axisTick: { show: false },
              axisLine: { lineStyle: { color: '#c9cfdd' } } }
          ],
          yAxis: [
            { scale: true, gridIndex: 0, position: 'right',
              splitLine: { lineStyle: { color: '#eef1f6' } },
              axisLabel: { color: '#7a8194', fontSize: 10 } },
            { scale: true, gridIndex: 1, position: 'right',
              splitLine: { show: false },
              axisLabel: { color: '#7a8194', fontSize: 10 } },
            { scale: true, gridIndex: 2, position: 'right',
              splitLine: { show: false },
              axisLabel: { color: '#7a8194', fontSize: 10,
                formatter: function (v) { return v.toFixed(0); } } },
            { scale: true, gridIndex: 3, position: 'right',
              splitLine: { show: false },
              axisLabel: { color: '#7a8194', fontSize: 10,
                formatter: function (v) { return v.toFixed(0); } } }
          ],
          dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1, 2, 3], start: start, end: 100 },
            { type: 'slider', xAxisIndex: [0, 1, 2, 3], bottom: 4, height: 18,
              start: start, end: 100, brushSelect: false }
          ],
          tooltip: {
            trigger: 'axis', axisPointer: { type: 'cross' }, confine: true,
            formatter: function (ps) {
              if (!ps || !ps.length) return '';
              const r = K[ps[0].dataIndex];
              if (!r) return '';
              const qcol = r.q >= 0 ? '#d64545' : '#2e8b57';
              let s = '<b>' + r.d + '</b><br>开 ' + r.o + '　高 ' + r.h +
                      '　低 ' + r.l + '　收 ' + r.c;
              s += '<br>净申赎 <b style="color:' + qcol + '">' +
                   (r.q >= 0 ? '+' : '') + r.q.toFixed(1) + ' 亿</b>';
              if (r.t != null) {
                const tcol = (r.dt == null || r.dt >= 0) ? '#d64545' : '#2e8b57';
                s += '<br>沪深成交额 <b>' + r.t.toFixed(0) + ' 亿</b>';
                if (r.dt != null) {
                  s += '　Δ <b style="color:' + tcol + '">' +
                       (r.dt >= 0 ? '+' : '') + r.dt.toFixed(0) + ' 亿</b>';
                }
              }
              if (r.m != null) {
                s += '<br>融资余额 <b>' + r.m.toFixed(0) + ' 亿</b>';
                if (r.dm != null) {
                  const dcol = r.dm >= 0 ? '#d64545' : '#2e8b57';
                  s += '　Δ <b style="color:' + dcol + '">' +
                       (r.dm >= 0 ? '+' : '') + r.dm.toFixed(1) + ' 亿</b>';
                }
              }
              return s;
            }
          },
          series: [
            { name: '中证全指', type: 'candlestick', data: candles,
              itemStyle: { color: '#d64545', color0: '#2e8b57',
                           borderColor: '#d64545', borderColor0: '#2e8b57' } },
            { name: '净申赎', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: flows,
              itemStyle: { color: function (p) { return p.value >= 0 ? '#d64545' : '#2e8b57'; } } },
            { name: '沪深成交额', type: 'bar', xAxisIndex: 2, yAxisIndex: 2,
              data: turnovers,
              itemStyle: { color: function (p) {
                const r = K[p.dataIndex];
                return (r && r.dt != null && r.dt < 0) ? '#2e8b57' : '#d64545';
              } } },
            { name: '20日均额', type: 'line', xAxisIndex: 2, yAxisIndex: 2,
              data: turnoverMa, connectNulls: true, showSymbol: false,
              lineStyle: { width: 1.2, color: '#e67e22', type: 'dashed' },
              itemStyle: { color: '#e67e22' } },
            { name: '融资余额', type: 'line', xAxisIndex: 3, yAxisIndex: 3,
              data: margins, connectNulls: true, showSymbol: false,
              lineStyle: { width: 1.8, color: '#8e44ad' },
              itemStyle: { color: '#8e44ad' } }
          ]
        };
      }

      let cur = 0;
      function apply(n) {
        cur = n;
        chart.setOption(option(n));
        dateEl.textContent = n > 0 ? ('最近 ' + n + ' 个交易日') : ('全部 ' + K.length + ' 个交易日');
      }
      apply(cur);
      document.querySelectorAll('.rng').forEach(function (b) {
        b.addEventListener('click', function () {
          document.querySelectorAll('.rng').forEach(function (x) {
            x.classList.toggle('sel', x === b);
          });
          apply(parseInt(b.dataset.n, 10));
        });
      });
      window.addEventListener('resize', function () { chart.resize(); });
    }

    const srcs = [
      'https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js',
      'https://unpkg.com/echarts@5/dist/echarts.min.js'
    ];
    let i = 0;
    function next() {
      if (i >= srcs.length) {
        box.style.display = 'none';
        fallback.style.display = 'block';
        return;
      }
      const s = document.createElement('script');
      s.src = srcs[i++];
      s.onload = init;
      s.onerror = next;
      document.head.appendChild(s);
    }
    next();
  })();
  </script>
</section>"""
    return template.replace("__DATA__", data_json).replace("__CORR__", corr_text)


def render_html(conn: sqlite3.Connection, out_path: Path) -> Path | None:
    all_df = pd.read_sql_query(
        "SELECT * FROM etf_flow_daily WHERE bucket = 'ALL' ORDER BY trade_date", conn
    )
    if all_df.empty:
        print("  ! 没有可渲染的数据", file=sys.stderr)
        return None
    cat_df = pd.read_sql_query(
        "SELECT * FROM etf_flow_daily WHERE bucket != 'ALL' ORDER BY trade_date", conn
    )
    bench = pd.read_sql_query(
        "SELECT trade_date, close FROM etf_benchmark_daily ORDER BY trade_date", conn
    )
    idx = pd.read_sql_query(
        "SELECT * FROM etf_index_daily WHERE ts_code = ? AND trade_date >= '2024-01-01' "
        "ORDER BY trade_date",
        conn,
        params=(ALLSHARE_CODE,),
    )
    margin = pd.read_sql_query(
        "SELECT * FROM margin_daily WHERE trade_date >= '2024-01-01' "
        "ORDER BY trade_date",
        conn,
    )
    turnover = pd.read_sql_query(
        "SELECT * FROM market_turnover_daily WHERE trade_date >= '2024-01-01' "
        "ORDER BY trade_date",
        conn,
    )
    latest = all_df.iloc[-1]
    asof = latest["trade_date"]
    detail = pd.read_sql_query(
        """
        SELECT m.code, m.name, m.bucket, m.exchange, s.shares_wan, s.unit_nav,
               s.close, s.premium_prev, s.premium_same, s.net_yi, s.split_flag
        FROM etf_share_daily s
        JOIN etf_meta m ON m.ts_code = s.ts_code
        WHERE s.trade_date = ?
        ORDER BY ABS(s.net_yi) DESC
        """,
        conn,
        params=(asof,),
    )
    episodes = pd.read_sql_query(
        "SELECT * FROM etf_episode ORDER BY start_date DESC LIMIT 12", conn
    )

    # 最近 250 个交易日用于主图，完整序列用于累计图
    recent = all_df.tail(250).reset_index(drop=True)
    bench_recent = bench[bench["trade_date"] >= recent["trade_date"].iloc[0]]

    def sign_class(v: float) -> str:
        return "pos" if v >= 0 else "neg"

    net = float(latest["net_yi"] or 0)
    net5 = latest["net5"]
    net20 = latest["net20"]
    idx_pct = None
    if not bench.empty and bench["trade_date"].iloc[-1] == asof:
        # psql 里没有 pct_chg，用相邻收盘计算
        tail = bench.tail(2)
        if len(tail) == 2:
            idx_pct = float(tail["close"].iloc[-1] / tail["close"].iloc[0] - 1)
    tag = "—"
    if idx_pct is not None:
        if idx_pct < 0 and net > 0:
            tag = "越跌越买"
        elif idx_pct > 0 and net > 0:
            tag = "顺势加仓"
        elif idx_pct > 0 and net < 0:
            tag = "涨了就卖"
        else:
            tag = "下跌也在卖"

    streak = 0
    direction = 0
    for v in reversed(all_df["net_yi"].tolist()):
        s = 1 if (v or 0) > 0 else (-1 if (v or 0) < 0 else 0)
        if direction == 0:
            direction = s
        if s == direction:
            streak += 1
        else:
            break

    net120 = float(all_df["net_yi"].tail(120).sum())
    net242 = float(all_df["net_yi"].tail(242).sum())
    ytd = float(all_df[all_df["trade_date"] >= f"{asof[:4]}-01-01"]["net_yi"].sum())

    cards = [
        ("最新日净申赎", f"{fmt_yi(net)} 亿", f"{asof} · {tag}"),
        ("近 5 日累计", f"{fmt_yi(net5)} 亿", "滚动 5 个交易日"),
        ("近 20 日累计", f"{fmt_yi(net20)} 亿", "滚动 20 个交易日"),
        ("近半年累计", f"{fmt_yi(net120)} 亿", "约 120 个交易日"),
        ("近一年累计", f"{fmt_yi(net242)} 亿", "约 242 个交易日"),
        ("今年以来", f"{fmt_yi(ytd)} 亿", f"{asof[:4]} 年至今"),
        ("连续同向", f"{streak} 日", "净买入" if direction > 0 else "净卖出"),
        ("全表持仓市值", f"{float(latest['aum_yi'] or 0):,.0f} 亿", f"{int(latest['n_etf'])} 只 ETF"),
        ("当日净买入家数", f"{int(latest['n_pos'])} / {int(latest['n_etf'])}", "按 ETF 只数"),
        ("分类广度", f"{int(latest['breadth_cat'] or 0)} / {cat_df[cat_df['trade_date']==asof]['bucket'].nunique()}", "净流入的分类数"),
        ("当前阶段", str(latest["stage"] or "—"), "按 3 日 / 5 日 / 20 日规则"),
    ]
    card_html = "".join(
        f'<div class="tile"><div class="k">{k}</div><div class="v {sign_class(net) if i==0 else ""}">{v}</div><div class="s">{s}</div></div>'
        for i, (k, v, s) in enumerate(cards)
    )

    ep_rows = "".join(
        f"<tr><td>{r.start_date}</td><td>{r.end_date}</td><td>{r.days}</td>"
        f"<td class='{sign_class(r.net_yi_sum or 0)}'>{fmt_yi(r.net_yi_sum)}</td>"
        f"<td class='{sign_class(r.fwd5 or 0)}'>{fmt_pct(r.fwd5)}</td>"
        f"<td class='{sign_class(r.fwd20 or 0)}'>{fmt_pct(r.fwd20)}</td>"
        f"<td class='{sign_class(r.fwd60 or 0)}'>{fmt_pct(r.fwd60)}</td></tr>"
        for r in episodes.itertuples(index=False)
    ) or "<tr><td colspan='7'>暂无（阈值 100 亿）</td></tr>"

    def num(value, spec: str) -> str:
        if value is None or pd.isna(value):
            return "—"
        return format(float(value), spec)

    detail_rows = "".join(
        f"<tr><td>{r.code}</td><td>{r.name}</td><td>{r.bucket}</td>"
        f"<td class='{sign_class(r.net_yi or 0)}'>{fmt_yi(r.net_yi)}</td>"
        f"<td>{num(None if r.shares_wan is None else r.shares_wan/1e4, ',.1f')}</td>"
        f"<td>{num(r.unit_nav, '.4f')}</td>"
        f"<td>{num(None if r.premium_same is None else r.premium_same*100, '+.2f')}%</td>"
        f"<td>{'是' if r.split_flag else ''}</td></tr>"
        for r in detail.itertuples(index=False)
    )

    if not margin.empty and not turnover.empty:
        kline_html = kline_section_full(idx, all_df, margin, turnover)
    elif not margin.empty:
        kline_html = kline_section_margin(idx, all_df, margin)
    else:
        kline_html = kline_section(idx, all_df)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>国家队 ETF 份额流向 · {asof}</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg:#f6f6f3; --card:#ffffff; --text:#141413; --muted:#6b6b66;
    --line:#e4e4de; --pos:#d64545; --neg:#2e8b57; --blue:#2a78d6;
    --border:rgba(20,20,19,.10);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg:#111110; --card:#1b1b1a; --text:#f0efec; --muted:#9a9993;
      --line:#2e2e2b; --pos:#e66767; --neg:#5fbf8a; --blue:#5b9df0;
      --border:rgba(255,255,255,.10);
    }}
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
    line-height:1.55}}
  .wrap{{max-width:1220px;margin:0 auto;padding:28px 22px 60px}}
  header{{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;margin-bottom:18px}}
  h1{{font-size:22px;font-weight:650;margin:0 0 4px}}
  .sub{{color:var(--muted);font-size:13px;margin:0}}
  .pill{{border:1px solid var(--border);border-radius:999px;padding:6px 12px;
    color:var(--muted);font-size:12px;white-space:nowrap}}
  .kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}}
  .tile{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px 16px}}
  .tile .k{{color:var(--muted);font-size:12px}}
  .tile .v{{font-size:22px;font-weight:600;margin-top:3px;letter-spacing:-.01em}}
  .tile .s{{color:var(--muted);font-size:12px;margin-top:2px}}
  .card{{background:var(--card);border:1px solid var(--border);border-radius:16px;
    padding:18px 20px;margin:16px 0;overflow:hidden}}
  h2{{font-size:15px;font-weight:600;margin:0 0 4px}}
  .note{{color:var(--muted);font-size:12.5px;margin:0 0 12px}}
  .klnctl{{display:flex;align-items:center;gap:8px;margin:0 0 8px;flex-wrap:wrap}}
  .kp{{color:var(--muted);font-size:12px}}
  .kpt{{color:var(--muted);font-size:12px;margin-left:4px}}
  .rng{{border:1px solid var(--border);background:var(--card);color:var(--muted);
    border-radius:999px;padding:4px 10px;font-size:12px;cursor:pointer}}
  .rng.sel{{color:var(--text);border-color:var(--blue);background:rgba(42,120,214,.08)}}
  svg{{display:block;width:100%;height:auto}}
  .pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
  th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
  th{{color:var(--muted);font-weight:600;font-size:12px;position:sticky;top:0;background:var(--card)}}
  tr:hover td{{background:rgba(127,127,127,.06)}}
  .scroll{{max-height:560px;overflow:auto;border:1px solid var(--line);border-radius:10px}}
  .foot{{color:var(--muted);font-size:12px;line-height:1.8;margin-top:18px}}
  @media (max-width:900px){{
    .kpis{{grid-template-columns:repeat(2,1fr)}}
    .wrap{{padding:18px 12px 40px}}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>国家队 ETF 份额流向</h1>
      <p class="sub">29 只核心宽基 ETF · 数据截至 {asof} · 来源 Tushare Pro（份额 / 净值 / 日线）</p>
    </div>
    <div class="pill">净申赎 = Δ份额 × 单位净值</div>
  </header>

  <div class="kpis">{card_html}</div>

  <section class="card">
    <h2>每日净申赎 × 沪深300（最近 {len(recent)} 个交易日）</h2>
    <p class="note">红柱 = 净申购（资金进场），绿柱 = 净赎回；蓝线为沪深300。悬停查看单日数值。</p>
    {svg_daily_bars(recent, bench_recent)}
  </section>

  <section class="card">
    <h2>累计持仓金额（2024 至今）</h2>
    <p class="note">29 只 ETF 的持仓市值 = Σ(份额 × 单位净值)；用于看仓位水平，不是累计净买入。悬停查看当日。</p>
    {svg_aum_line(all_df)}
  </section>

  {kline_html}

  <section class="card">
    <h2>20 日滚动累计净申赎（全历史）</h2>
    <p class="note">用于识别“持续流入 / 持续流出”阶段，单日噪声被平滑。</p>
    {svg_cum_line(all_df, 20)}
  </section>

  <section class="card">
    <h2>最新交易日：各分类 20 日累计净申赎</h2>
    <p class="note">按 20 日累计排序；用于看结构扩散（300 → 500/1000 → 创业板/科创）。</p>
    {svg_cat_bars(cat_df, asof)}
  </section>

  <section class="card">
    <h2>大额流入事件（单日 ≥100 亿，间隔 ≤2 个交易日合并）</h2>
    <p class="note">收益为沪深300从事件首日算起的 5/20/60 个交易日收益；事件高度重叠，样本仅供方向参考。</p>
    <div class="scroll">
      <table>
        <thead><tr><th>开始</th><th>结束</th><th>天数</th><th>累计净申赎（亿）</th>
        <th>后 5 日</th><th>后 20 日</th><th>后 60 日</th></tr></thead>
        <tbody>{ep_rows}</tbody>
      </table>
    </div>
  </section>

  <section class="card">
    <h2>最新交易日明细（{asof}）</h2>
    <p class="note">按当日净申赎绝对值排序；份额单位亿份；“折算”列标记当日是否识别为份额折算/合并。</p>
    <div class="scroll">
      <table>
        <thead><tr><th>代码</th><th>名称</th><th>分类</th><th>净申赎（亿）</th>
        <th>份额（亿份）</th><th>净值</th><th>溢价（同日）</th><th>折算</th></tr></thead>
        <tbody>{detail_rows}</tbody>
      </table>
    </div>
  </section>

  <p class="foot">
    <b>口径：</b>净申赎（亿元）=（当日调整后份额 − 前一日调整后份额）× 当日单位净值 / 1e4，份额单位为万份。<br>
    <b>折算：</b>份额比例与净值比例近似互为倒数（乘积在 0.94–1.06）且份额变化 &gt;15% 时，判定为折算/合并，当日净申赎置 0。<br>
    <b>去噪：</b>份额变化含套利盘、新发建仓、散户/机构申赎，不等于汇金实际持仓；新发 ETF 前 30 个交易日建议剔除。<br>
    <b>阶段：</b>转弱观察（近 2 日净卖出但 5 日仍为正）／连续流入（近 3 日均流入且至少 2 日 &gt;50 亿、分类广度 ≥3）／脉冲（单日 ≥200 亿）／静默流出（近 3 日均 ≤0）／偏流入／中性。<br>
    <b>风险：</b>份额数据 T+1；季报/十大持有人滞后 45–120 天，只能事后归因。本报告仅用于研究，不构成投资建议。
  </p>
</div>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    reconfigure_stdout()
    parser = argparse.ArgumentParser(description="国家队 ETF 份额流向入库与报表")
    parser.add_argument("--start", default="20150101", help="开始日期 YYYYMMDD")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"), help="结束日期 YYYYMMDD")
    parser.add_argument("--codes", default="", help="只跑指定代码，逗号分隔（调试用）")
    parser.add_argument("--report-only", action="store_true", help="跳过取数，只重建聚合/事件/报表")
    parser.add_argument("--refresh-benchmark", action="store_true", help="只刷新指数 K 线（沪深300 / 中证全指）")
    parser.add_argument("--refresh-margin", action="store_true", help="只刷新融资余额（沪深两市）")
    parser.add_argument("--refresh-turnover", action="store_true", help="只刷新沪深两市成交额")
    parser.add_argument("--report", action="store_true", help="取数后生成 HTML 报表")
    parser.add_argument("--no-report", action="store_true", help="只入库，不生成报表")
    parser.add_argument("--sleep", type=float, default=0.35, help="单次 API 调用间隔（秒）")
    args = parser.parse_args()

    start, end = d8(args.start), d8(args.end)
    conn = connect()
    update_meta(conn)

    if args.refresh_benchmark or args.refresh_margin or args.refresh_turnover:
        pro = ts.pro_api(load_token())
        if args.refresh_benchmark:
            print("刷新指数 K 线（沪深300 / 中证全指）…")
            ingest_benchmark(pro, conn, start, end)
            update_list_dates(pro, conn)
        if args.refresh_margin:
            print("刷新融资余额（沪深两市）…")
            ingest_margin(pro, conn, start, end)
        if args.refresh_turnover:
            print("刷新沪深两市成交额…")
            ingest_turnover(pro, conn, start, end)

    if not args.report_only:
        token = load_token()
        pro = ts.pro_api(token)
        wanted = {c.strip() for c in args.codes.split(",") if c.strip()}
        targets = [t for t in TARGETS if not wanted or t[0] in wanted]
        print(f"回填 {len(targets)} 只 ETF，区间 {start} ~ {end}")
        total = 0
        for code, name, bucket, exchange in targets:
            ts_code = ts_code_of(code, exchange)
            count, latest = ingest_one(pro, conn, ts_code, start, end)
            total += count
            print(f"  {code} {name:22} rows={count:>5} latest={latest}")
            time.sleep(args.sleep)
        print(f"合计写入 {total} 行")
        update_list_dates(pro, conn)
        if not args.refresh_benchmark:
            ingest_benchmark(pro, conn, start, end)
        if not args.refresh_margin:
            ingest_margin(pro, conn, start, end)
        if not args.refresh_turnover:
            ingest_turnover(pro, conn, start, end)

    refresh_list_dates(conn)
    print("重建聚合表 etf_flow_daily …")
    rebuild_flow(conn)
    print("重建事件表 etf_episode …")
    rebuild_episodes(conn)

    rows = conn.execute("SELECT COUNT(*) FROM etf_flow_daily WHERE bucket='ALL'").fetchone()[0]
    latest = conn.execute(
        "SELECT trade_date, net_yi, stage FROM etf_flow_daily WHERE bucket='ALL' "
        "ORDER BY trade_date DESC LIMIT 1"
    ).fetchone()
    print(f"etf_flow_daily ALL 行={rows} latest={latest['trade_date']} "
          f"net={latest['net_yi']:+.1f}亿 stage={latest['stage']}")

    if not args.no_report:
        asof = latest["trade_date"]
        out = OUT_DIR / f"国家队ETF份额流向_{asof}.html"
        result = render_html(conn, out)
        if result:
            print(f"报表已生成: {result}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
