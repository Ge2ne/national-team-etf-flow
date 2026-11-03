# -*- coding: utf-8 -*-
"""
双源交叉校验（国家队ETF报表 <-> etf-lsi 看板）共用小模块
============================================================
设计原则：
  * 只做「比对 + 留痕」，不参与任何主报表的数值计算；
  * 任何一步失败都只打印日志并降级，绝不阻断主流程（网络异常也不影响出图）；
  * 单位统一用「亿份」——比的是份额变化，天然可比（亿元 vs 亿份的 NAV 口径差被绕开）。

可逐只对账的标的（两站并非全部重叠）：
  * 沪深300：510300 / 510310 / 510330 / 159919 —— 两站完全一致，可逐只 + 类别级对比；
  * 创业板：仅 159915 一致（NT 是 159915/159952/159977，LSI 是 159915/159949/159957/159948），
    故创业板不做类别级对比，只比 159915。

对外三个入口：
  build_payload(source, asof, etfs_by_code)  生成 reconcile.json 内容
  fetch_json(url)                            抓对方仓的 reconcile.json
  compare(mine, peer)                        比对，返回逐条明细（agree/conflict）
  update_history(path, detail)               留痕（冲突记录 + 修好后标「已修正」）
"""
import json
import os
import datetime
import urllib.request

# 对方仓的 reconcile.json（GitHub Pages）
PEER_NT = "https://wj624.github.io/national-team-etf-flow/reconcile.json"
PEER_LSI = "https://wj624.github.io/etf-lsi/reconcile.json"

# 代码 -> 分组（只有这里列出的才参与对账）
OVERLAP = {
    "510300": "沪深300", "510310": "沪深300", "510330": "沪深300", "159919": "沪深300",
    "159915": "创业板",
}

EPS_YI = 0.3   # 亿份：小于此视为噪声，不判分歧


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def fetch_json(url, timeout=25):
    """抓取对方 reconcile.json；失败返回 None（不抛异常）。"""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print("[reconcile] 抓取失败 %s : %s" % (url, str(e)[:90]), flush=True)
        return None


def build_payload(source, asof, etfs_by_code):
    """etfs_by_code: {code: {date('YYYY-MM-DD'): chg_yi}}；只保留重叠标的。"""
    keep = {c: dict(etfs_by_code.get(c) or {}) for c in OVERLAP}
    return {"source": source, "asof": asof, "generated_at": _now(),
            "unit": "亿份", "etfs": keep}


def compare(mine, peer):
    """返回逐条明细：[{date, group, code, mine, peer, status}]，date 降序。
       status: 'agree' 方向一致 / 'conflict' 方向相反。"""
    out = []
    if not mine or not peer:
        return out
    a = mine.get("etfs") or {}
    b = peer.get("etfs") or {}
    for code, grp in OVERLAP.items():
        da = a.get(code) or {}
        db = b.get(code) or {}
        for d in sorted(set(da) & set(db)):
            va, vb = da.get(d), db.get(d)
            if va is None or vb is None:
                continue
            if max(abs(va), abs(vb)) < EPS_YI:
                continue
            status = "agree" if (va > 0) == (vb > 0) else "conflict"
            out.append({"date": d, "group": grp, "code": code,
                        "mine": round(va, 3), "peer": round(vb, 3), "status": status})
    out.sort(key=lambda x: (x["date"], x["code"]), reverse=True)
    return out


def update_history(hist_path, detail):
    """留痕：把本次比对并入 hist_path。
       - 新出现分歧 -> 建记录，保留首次见到的原始值；
       - 历史分歧、本次转一致 -> 标「已修正」，记录修正后的值；
       - 只保留最近 120 条，防止文件膨胀。"""
    hist = {}
    if os.path.exists(hist_path):
        try:
            with open(hist_path, encoding="utf-8-sig") as f:
                hist = json.load(f)
        except Exception:
            hist = {}
    recs = hist.setdefault("records", {})
    now = _now()
    for it in detail:
        key = "%s|%s" % (it["date"], it["code"])
        prev = recs.get(key)
        if it["status"] == "conflict":
            if prev and prev.get("status") == "已修正":
                prev["status"] = "conflict"
                prev["last_mine"] = it["mine"]
                prev["last_peer"] = it["peer"]
                prev["last_check"] = now
            elif prev:
                prev["last_mine"] = it["mine"]
                prev["last_peer"] = it["peer"]
                prev["last_check"] = now
            else:
                recs[key] = {
                    "date": it["date"], "group": it["group"], "code": it["code"],
                    "status": "conflict",
                    "orig_mine": it["mine"], "orig_peer": it["peer"],
                    "last_mine": it["mine"], "last_peer": it["peer"],
                    "first_seen": now, "last_check": now,
                }
        else:  # agree
            if prev and prev.get("status") == "conflict":
                prev["status"] = "已修正"
                prev["fixed_mine"] = it["mine"]
                prev["fixed_peer"] = it["peer"]
                prev["fixed_at"] = now
    if len(recs) > 120:
        items = sorted(recs.items(), key=lambda kv: (kv[1].get("date", ""), kv[0]), reverse=True)[:120]
        hist["records"] = dict(items)
    hist["updated"] = now
    try:
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print("[reconcile] 写留痕失败:", str(e)[:80], flush=True)
    return hist


def common_latest_date(mine, peer, detail):
    """双方都有数据的最近一天（用于标注日期）。"""
    a = (mine or {}).get("etfs") or {}
    b = (peer or {}).get("etfs") or {}
    ds = set()
    for c in OVERLAP:
        ds |= set((a.get(c) or {}).keys()) & set((b.get(c) or {}).keys())
    if ds:
        return max(ds)
    return detail[0]["date"] if detail else None


def history_rows(hist, limit=20):
    """把留痕 dict 转成按日期降序的列表，供页面渲染。"""
    recs = (hist or {}).get("records") or {}
    rows = sorted(recs.values(), key=lambda r: (r.get("date", ""), r.get("code", "")), reverse=True)
    return rows[:limit]
