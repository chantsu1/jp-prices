"""東証銘柄の日次終値を Yahoo Finance から取得し、テーマ予兆用の指標を data/ に書き出す。

出力:
  data/metrics.csv  銘柄ごとの最新値と指標（上昇率・高値からの距離・移動平均など）
  data/prices.csv   直近約300営業日の終値（縦持ち: date,code,close）
  data/ohlc.csv.gz  直近約120営業日の始値・高値・安値・終値・出来高（date,code,open,high,low,close,volume）
  data/global.csv   米国ETF・資源・金利などの直近約300営業日の終値（date,symbol,close）
  data/updated.txt  更新日時と取得結果の要約
"""
import csv
import datetime as dt
import math
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
OHLC = {}  # code ごとの始値・高値・安値・終値・出来高（fetch が埋める）
GLOBAL = ["SPY", "QQQ", "SOXX", "XLE", "XLF", "XLK", "^SOX", "^VIX", "^TNX", "CL=F", "HG=F", "GC=F", "DX-Y.NYB", "JPY=X"]
DATA = ROOT / "data"
BENCH = "1306"  # 市場全体の基準（TOPIX連動ETF）


def to_yahoo(code: str) -> str:
    code = code.strip()
    return code if code.startswith("^") else f"{code}.T"


def load_tickers():
    with open(ROOT / "tickers.csv", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("code")]


def fetch(symbols):
    df = yf.download(symbols, period="2y", interval="1d", auto_adjust=True,
                     group_by="ticker", threads=True, progress=False)
    closes = {}
    for s in symbols:
        try:
            sub = df[s] if isinstance(df.columns, pd.MultiIndex) else df
            c = sub["Close"].dropna()
            c = c[c > 0]
            # Yahoo のデータにまれに混じる一時的な異常値（株式分割の反映漏れなど）を取り除く
            med = c.rolling(9, center=True, min_periods=1).median()
            c = c[(c / med).between(0.6, 1.6)]
            if len(c):
                closes[s] = c
                try:
                    o = sub[["Open", "High", "Low", "Close", "Volume"]].loc[c.index]
                    OHLC[s] = o
                except Exception:
                    pass
        except KeyError:
            pass
    return closes


def ret(c: pd.Series, days: int):
    if len(c) <= days:
        return None
    return float(c.iloc[-1] / c.iloc[-1 - days] - 1)


def r(x, n=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, n)


def metrics(c: pd.Series, bench: pd.Series | None):
    last = float(c.iloc[-1])
    y = c[c.index >= c.index[-1] - pd.Timedelta(days=365)]
    hi, lo = float(y.max()), float(y.min())
    ma = {n: (float(c.iloc[-n:].mean()) if len(c) >= n else None) for n in (25, 75, 200)}
    m = {
        "date": c.index[-1].strftime("%Y-%m-%d"),
        "close": r(last, 2),
        "ret_1m": r(ret(c, 21)), "ret_3m": r(ret(c, 63)), "ret_6m": r(ret(c, 126)), "ret_12m": r(ret(c, 250)),
        "high_52w": r(hi, 2), "low_52w": r(lo, 2),
        "from_high": r(last / hi - 1), "x_from_low": r(last / lo),
        "ma25": r(ma[25], 2), "ma75": r(ma[75], 2), "ma200": r(ma[200], 2),
        "dev25": r(last / ma[25] - 1) if ma[25] else None,
        "above75": (last > ma[75]) if ma[75] else None,
        "above200": (last > ma[200]) if ma[200] else None,
        "n_days": len(c),
    }
    if bench is not None:
        b6 = ret(bench, 126)
        m["rel_6m"] = r(m["ret_6m"] - b6) if m["ret_6m"] is not None and b6 is not None else None
    else:
        m["rel_6m"] = None
    return m


def write_extra(tickers, symbols):
    """始値・高値・安値・出来高と、米国ETF・資源などの終値。失敗しても本体の出力には影響させない。"""
    try:
        rows = []
        for t, s in zip(tickers, symbols):
            o = OHLC.get(s)
            if o is None:
                continue
            for d, v in o.iloc[-120:].iterrows():
                rows.append([d.strftime("%Y-%m-%d"), t["code"], round(float(v["Open"]), 2), round(float(v["High"]), 2),
                             round(float(v["Low"]), 2), round(float(v["Close"]), 2), int(v["Volume"]) if v["Volume"] == v["Volume"] else 0])
        pd.DataFrame(rows, columns=["date", "code", "open", "high", "low", "close", "volume"]).to_csv(
            DATA / "ohlc.csv.gz", index=False, compression="gzip")
        print("ohlc rows", len(rows))
    except Exception as e:
        print("ohlc failed:", e)
    try:
        g = fetch(GLOBAL)
        rows = []
        for s, c in g.items():
            for d, v in c.iloc[-300:].items():
                rows.append([d.strftime("%Y-%m-%d"), s, round(float(v), 4)])
        pd.DataFrame(rows, columns=["date", "symbol", "close"]).to_csv(DATA / "global.csv", index=False)
        print("global rows", len(rows), "symbols", len(g))
    except Exception as e:
        print("global failed:", e)


def main():
    tickers = load_tickers()
    symbols = [to_yahoo(t["code"]) for t in tickers]
    closes = fetch(symbols)
    bench = closes.get(to_yahoo(BENCH))
    DATA.mkdir(exist_ok=True)
    cols = ["code", "name", "group", "date", "close", "ret_1m", "ret_3m", "ret_6m", "ret_12m", "rel_6m",
            "high_52w", "low_52w", "from_high", "x_from_low", "ma25", "ma75", "ma200", "dev25",
            "above75", "above200", "n_days", "status"]
    ok = ng = 0
    with open(DATA / "metrics.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for t, s in zip(tickers, symbols):
            row = {"code": t["code"], "name": t.get("name", ""), "group": t.get("group", "")}
            c = closes.get(s)
            if c is None or len(c) < 2:
                row["status"] = "取得失敗"
                ng += 1
            else:
                row.update(metrics(c, bench))
                row["status"] = "ok"
                ok += 1
            w.writerow(row)
    with open(DATA / "prices.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "code", "close"])
        for t, s in zip(tickers, symbols):
            c = closes.get(s)
            if c is None:
                continue
            for d, v in c.iloc[-300:].items():
                w.writerow([d.strftime("%Y-%m-%d"), t["code"], round(float(v), 2)])
    write_extra(tickers, symbols)
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    (DATA / "updated.txt").write_text(f"{now} 取得成功 {ok} / 失敗 {ng}\n", encoding="utf-8")
    print(f"done ok={ok} ng={ng}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
