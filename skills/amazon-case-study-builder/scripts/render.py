#!/usr/bin/env python3
"""Render a case-study JSON (schema: scripts/schema.md) into ONE self-contained HTML file.

    python3 scripts/render.py case-study.json [-o out.html]

Python 3 stdlib only, no network. Inline CSS, charts as inline SVG, no scripts. Product photos are linked
from Amazon's image CDN (https only). Every string from the JSON is HTML-escaped; links are http(s) or
#anchors only; waithowmuch.com links get the skill's UTM tags, no other link does.

Prints JSON: {"written": <path>, "bytes": N, "sections": [...], "warnings": [...]}. Exit 4 on bad input.
"""
import html
import json
import math
import os
import re
import sys
import urllib.parse
from datetime import date

REPO = "https://github.com/ggballas/waithowmuch-skills"
UTM = {"utm_source": "whm-skills", "utm_medium": "skill", "utm_campaign": "whm-skills",
       "utm_content": "amazon-case-study-builder"}
TIERS = {"given": "Given", "derived": "Derived", "assumed": "Assumed", "inferred": "Inferred"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ORDER = [  # (key, group eyebrow, default title)
    ("timeline", "Overview", "Timeline"),
    ("revenue", "What it earns", "Revenue"),
    ("selling", "What it earns", "How it sells"),
    ("margin", "What it earns", "Margin breakdown"),
    ("advertising", "Where demand comes from", "Advertising"),
    ("traffic", "Where demand comes from", "Socials and traffic"),
    ("tiktok", "Where demand comes from", "TikTok Shop"),
    ("listing", "Where demand comes from", "The listing"),
    ("reviews", "Where demand comes from", "What buyers say"),
    ("owner", "Who and when", "Brand owner"),
    ("valuation", "What it's worth", "Valuation"),
    ("analysis", "The read", "What it adds up to"),
    ("similar", "Further reading", "Similar case studies"),
]
WARN = []


# ─── helpers ─────────────────────────────────────────────────────────

def e(s):
    return html.escape("" if s is None else str(s), quote=True)


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def usd(v, cents=False):
    if not num(v):
        return "–"
    neg = v < 0
    s = f"${abs(v):,.2f}" if cents else f"${abs(round(v)):,}"
    return ("−" if neg else "") + s


def usd_k(v):
    """The card form, as waithowmuch.com renders it: 25197 -> $25.2K, 89988 -> $90K, 840 -> $840."""
    if not num(v):
        return "–"
    a = abs(v)
    if a >= 1e6:
        s = f"{a / 1e6:.1f}".rstrip("0").rstrip(".") + "M"
    elif a >= 1000:
        s = f"{a / 1000:.1f}".rstrip("0").rstrip(".") + "K"
    else:
        s = f"{round(a):,}"
    return ("−" if v < 0 else "") + "$" + s


def pct(v, d=1):
    if not num(v):
        return "–"
    s = f"{v:.{d}f}".rstrip("0").rstrip(".") if d else f"{round(v)}"
    return s + "%"


def month_label(m, short=False):
    try:
        y, mo = m.split("-")[:2]
        return f"{MONTHS[int(mo) - 1]} {y[2:] if short else y}"
    except Exception:  # noqa: BLE001
        return str(m)


def date_label(d):
    try:
        y, mo, da = d.split("-")
        return f"{int(da)} {MONTHS[int(mo) - 1]} {y}"
    except Exception:  # noqa: BLE001
        return month_label(d) if isinstance(d, str) and len(d) == 7 else str(d)


def href(u):
    """http(s) or #anchor only; waithowmuch.com gets UTM tags."""
    if not isinstance(u, str):
        return None
    u = u.strip()
    if u.startswith("#"):
        return u
    p = urllib.parse.urlsplit(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        WARN.append(f"link dropped (not http/https): {u[:60]}")
        return None
    host = p.hostname or ""
    if host == "waithowmuch.com" or host.endswith(".waithowmuch.com"):
        q = dict(urllib.parse.parse_qsl(p.query))
        q.update(UTM)
        u = urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), p.fragment))
    return u


def a(label, url, cls=None):
    h = href(url)
    if not h:
        return e(label)
    ext = "" if h.startswith("#") else ' target="_blank" rel="noopener noreferrer nofollow"'
    return f'<a href="{e(h)}"{ext}{f" class={cls!r}" if cls else ""}>{e(label)}</a>'


def img(src, alt, cls="", w=None):
    if not isinstance(src, str) or not src.startswith("https://"):
        if src:
            WARN.append(f"image dropped (https only): {str(src)[:60]}")
        return ""
    return (f'<img src="{e(src)}" alt="{e(alt)}" loading="lazy" referrerpolicy="no-referrer"'
            f'{f" class={cls!r}" if cls else ""}{f" width={w}" if w else ""}>')


def tier(t):
    if not t:
        return ""
    if t not in TIERS:
        WARN.append(f"unknown tier '{t}' (use given, derived, assumed, inferred)")
        return f'<span class="tier">{e(t)}</span>'
    return f'<span class="tier t-{t}" title="{e(TIER_HELP[t])}">{TIERS[t]}</span>'


TIER_HELP = {"given": "A number the user supplied.", "derived": "Computed from a named source.",
             "assumed": "A default put in to complete the sum; replace it with a real figure.",
             "inferred": "Read from the public record; the first thing to put to the owner."}


def paras(items, cls="prose"):
    return "".join(f'<p class="{cls}">{e(p)}</p>' for p in (items or []) if p)


def lede(s):
    return f'<p class="lede">{e(s)}</p>' if s else ""


def callout(s):
    return f'<div class="callout">{e(s)}</div>' if s else ""


def note(s):
    return f'<p class="note">{e(s)}</p>' if s else ""


def table(head, rows, cls="", aligns=None):
    aligns = aligns or [""] * len(head)
    th = "".join(f'<th class="{al}">{h}</th>' for h, al in zip(head, aligns))
    trs = "".join("<tr>" + "".join(f'<td class="{al}">{c}</td>' for c, al in zip(r, aligns)) + "</tr>" for r in rows)
    return f'<div class="tablewrap"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


# ─── charts (inline SVG) ─────────────────────────────────────────────

def nice_max(v):
    if v <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp


def perf_chart(series, events):
    months = series.get("months") or []
    n = len(months)
    if n < 2:
        WARN.append("series has under 2 months: no chart")
        return ""
    keys = [("revenue", "Revenue", "var(--s-rev)", ""), ("profit", "Profit", "var(--s-profit)", "6 4"),
            ("adSpend", "Ad spend", "var(--s-ads)", "2 3")]
    vals = {k: (series.get(k) or [None] * n)[:n] for k, *_ in keys}
    hi = (series.get("revenueHigh") or [None] * n)[:n]
    top = nice_max(max([v for k in vals for v in vals[k] if num(v)] + [v for v in hi if num(v)] + [1]) * 1.05)
    W, H, L, R, T, B = 760, 300, 56, 16, 14, 40
    pw, ph = W - L - R, H - T - B
    x = lambda i: L + (pw * i / (n - 1))  # noqa: E731
    y = lambda v: T + ph - ph * (v / top)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Monthly revenue, profit and ad spend">']
    for i in range(5):
        v = top * i / 4
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                   f'<text x="{L - 8}" y="{y(v) + 4:.1f}" class="ax" text-anchor="end">{e(usd_k(v))}</text>')
    step = max(1, math.ceil(n / 12))
    for i, m in enumerate(months):
        if i % step == 0 or i == n - 1:
            out.append(f'<text x="{x(i):.1f}" y="{H - B + 18}" class="ax" text-anchor="middle">{e(month_label(m, True))}</text>')
    # revenue band (badge floor -> bucket top)
    if any(num(v) for v in hi):
        pts = [(x(i), y(vals["revenue"][i])) for i in range(n) if num(vals["revenue"][i]) and num(hi[i])]
        up = [(x(i), y(hi[i])) for i in range(n) if num(vals["revenue"][i]) and num(hi[i])]
        if pts:
            poly = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts + up[::-1])
            out.append(f'<polygon points="{poly}" class="band"/>')
    for k, label, color, dash in keys:
        v = vals[k]
        segs, cur = [], []
        for i in range(n):
            if num(v[i]):
                cur.append(f"{x(i):.1f},{y(v[i]):.1f}")
            elif cur:
                segs.append(cur)
                cur = []
        if cur:
            segs.append(cur)
        for s in segs:
            out.append(f'<polyline points="{" ".join(s)}" fill="none" stroke="{color}" stroke-width="2"'
                       f'{f" stroke-dasharray={dash!r}" if dash else ""} stroke-linejoin="round" stroke-linecap="round"/>')
    # event dots on the baseline
    if events and months:
        for ev in events:
            d = ev.get("date") or ""
            mi = next((i for i, m in enumerate(months) if d.startswith(m)), None)
            if mi is None:
                continue
            try:
                frac = (int(d[8:10]) - 1) / 30 if len(d) >= 10 else 1
            except ValueError:
                frac = 1
            px = x(mi) + (pw / (n - 1)) * (frac - 1) if mi > 0 or frac >= 1 else x(0)
            px = max(L, min(W - R, px))
            filled = (ev.get("tag") or "").lower() == "amazon"
            out.append(f'<g class="ev"><title>{e(date_label(d))}: {e(ev.get("what"))}</title>'
                       f'<circle cx="{px:.1f}" cy="{T + ph:.1f}" r="5" class="{"dot-f" if filled else "dot-h"}"/></g>')
    # hover targets, one per month
    cw = pw / (n - 1)
    for i, m in enumerate(months):
        tip = [month_label(m)]
        r = vals["revenue"][i]
        if num(r):
            tip.append(f"Revenue {usd(r)}" + (f"–{usd(hi[i])}" if num(hi[i]) and hi[i] != r else ""))
        if num(vals["profit"][i]):
            tip.append(f"Profit {usd(vals['profit'][i])}")
        if num(vals["adSpend"][i]):
            tip.append(f"Ad spend {usd(vals['adSpend'][i])}")
        out.append(f'<g class="hit"><title>{e(" · ".join(tip))}</title>'
                   f'<rect x="{x(i) - cw / 2:.1f}" y="{T}" width="{cw:.1f}" height="{ph}" fill="transparent"/>'
                   + (f'<circle cx="{x(i):.1f}" cy="{y(r):.1f}" r="4" class="pt"/>' if num(r) else "") + "</g>")
    out.append("</svg>")
    legend = "".join(f'<span class="lg"><i style="border-top:2px {"dashed" if d == "6 4" else "dotted" if d else "solid"} {c}"></i>{lab}</span>'
                     for k, lab, c, d in keys if any(num(v) for v in vals[k]))
    if any(num(v) for v in hi):
        legend += '<span class="lg"><i class="lg-band"></i>Revenue range (badge bucket)</span>'
    if events:
        legend += '<span class="lg"><i class="lg-dot"></i>Timeline event</span>'
    rows = [[e(month_label(m)), usd(vals["revenue"][i]) + (f"–{usd(hi[i])}" if num(hi[i]) else ""),
             usd(vals["profit"][i]), usd(vals["adSpend"][i])] for i, m in enumerate(months)]
    tbl = table(["Month", "Revenue", "Profit", "Ad spend"], rows, aligns=["", "r", "r", "r"])
    return (f'<figure class="perf">{"".join(out)}<figcaption class="legend">{legend}</figcaption></figure>'
            f'<details class="numbers"><summary>Show the numbers</summary>{tbl}</details>')


def waterfall(rev, lines, result):
    """Revenue bar, each cost stepping down, what is left in the accent."""
    items = [(l.get("label"), l.get("pct")) for l in lines if num(l.get("pct")) and l.get("pct") != 0]
    if not items or not result:
        return ""
    W, rowh, L = 760, 30, 210
    H = rowh * (len(items) + 2) + 10
    pw = W - L - 70
    x = lambda p: L + pw * p / 100  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart wf" role="img" aria-label="Margin waterfall">']
    yy = 4
    out.append(f'<text x="{L - 10}" y="{yy + 19}" class="lab" text-anchor="end">Revenue</text>'
               f'<rect x="{x(0)}" y="{yy + 4}" width="{pw:.1f}" height="{rowh - 10}" rx="4" class="wf-rev"/>'
               f'<text x="{x(100) + 6}" y="{yy + 19}" class="val">100%</text>')
    level = 100.0
    for i, (lab, p) in enumerate(items):
        yy += rowh
        c = abs(p)
        new = level - c
        shade = 4 if c >= 15 else 3 if c >= 8 else 2 if c >= 2 else 1
        out.append(f'<g><title>{e(lab)}: {e(pct(-c, 2))} of revenue</title>'
                   f'<text x="{L - 10}" y="{yy + 19}" class="lab" text-anchor="end">{e(lab)}</text>'
                   f'<rect x="{x(new):.1f}" y="{yy + 4}" width="{max(pw * c / 100, 2):.1f}" height="{rowh - 10}" rx="4" '
                   f'class="wf-c{shade}"/><text x="{x(level) + 6:.1f}" y="{yy + 19}" class="val">−{e(pct(c, 1))}</text></g>')
        level = new
    yy += rowh
    rp = result.get("pct")
    if num(rp):
        out.append(f'<text x="{L - 10}" y="{yy + 19}" class="lab strong" text-anchor="end">{e(result.get("label") or "Profit")}</text>'
                   f'<rect x="{x(0)}" y="{yy + 4}" width="{max(pw * rp / 100, 2):.1f}" height="{rowh - 10}" rx="4" class="wf-left"/>'
                   f'<text x="{x(max(rp, 0)) + 6:.1f}" y="{yy + 19}" class="val strong">{e(pct(rp, 1))}</text>')
        if abs(level - rp) > 0.6:
            WARN.append(f"margin: the lines leave {level:.1f}% but the result says {rp}%")
    out.append("</svg>")
    return "".join(out)


def bars_svg(labels, values, unit=""):
    n = len(values)
    if not n:
        return ""
    W, H, B = 760, 120, 22
    top = nice_max(max([v for v in values if num(v)] + [1]))
    bw = (W - 20) / n
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Monthly series">']
    for i, (lab, v) in enumerate(zip(labels, values)):
        h = (H - B - 14) * ((v or 0) / top)
        xx = 10 + i * bw
        out.append(f'<g><title>{e(lab)}: {e(f"{v:,}" if num(v) else "–")}{e(unit)}</title>'
                   f'<rect x="{xx + 3:.1f}" y="{H - B - h:.1f}" width="{bw - 6:.1f}" height="{max(h, 1):.1f}" rx="3" class="bar"/>'
                   + (f'<text x="{xx + bw / 2:.1f}" y="{H - 6}" class="ax" text-anchor="middle">{e(lab)}</text>'
                      if n <= 14 or i % 2 == 0 else "") + "</g>")
    out.append("</svg>")
    return "".join(out)


# ─── sections ────────────────────────────────────────────────────────

def detail(o, k="detail"):
    return f"<p>{e(o.get(k))}</p>" if o.get(k) else ""


def sec_timeline(s, d):
    evs = d.get("events") or []
    if not evs:
        return ""
    items = "".join(
        f'<li class="{"amz" if (ev.get("tag") or "").lower() == "amazon" else ""}"><div class="when">{e(date_label(ev.get("date")))}'
        f'<span class="tag">{e(ev.get("tag"))}</span></div><div><strong>{e(ev.get("what"))}</strong> {tier(ev.get("tier"))}'
        f'{detail(ev)}</div></li>'
        for ev in sorted(evs, key=lambda v: v.get("date") or ""))
    return lede(s.get("lede")) + f'<ol class="timeline">{items}</ol>'


def sec_revenue(s, d):
    h = lede(s.get("lede")) + paras(s.get("prose"))
    bd = s.get("breakdown") or {}
    items = sorted(bd.get("items") or [], key=lambda i: -(i.get("revenue") or 0))
    if items:
        total = sum(i.get("revenue") or 0 for i in items)
        segs = "".join(f'<span style="flex:{max(i.get("revenue") or 0, 0.0001)}" class="seg s{min(k, 5)}" '
                       f'title="{e(i.get("title"))}: {e(usd(i.get("revenue")))}"></span>' for k, i in enumerate(items))
        rows = []
        for i in items:
            share = 100 * (i.get("revenue") or 0) / total if total else None
            units = f'{i["units"]:,}' if num(i.get("units")) else "–"
            if num(i.get("unitsHigh")) and i.get("unitsHigh") != i.get("units"):
                units += f'–{i["unitsHigh"]:,}'
            rows.append([
                f'<div class="prod">{img(i.get("image"), i.get("title") or i.get("asin"), "thumb", 48)}<div>'
                f'{a(i.get("title") or i.get("asin"), "https://www.amazon.com/dp/" + str(i.get("asin")) if i.get("asin") else None)}'
                f'<span class="asin">{e(i.get("asin"))}</span></div></div>',
                units, usd(i.get("price"), True), usd(i.get("revenue")), pct(share)])
        cap = f"The {len(items)} largest of {bd['partialOf']}" if bd.get("partialOf") else "Every listing that sold"
        h += (f'<h3>Sales breakdown</h3><p class="note">{e(cap)}, {e(bd.get("month") or month_label(d.get("snapshotMonth")))}.</p>'
              f'<div class="stack">{segs}</div>'
              + table(["Listing", "Units a month", "Price", "Revenue", "Share"], rows, "bd", ["", "r", "r", "r", "r"])
              + note(bd.get("note")))
    return h + callout(s.get("callout"))


def sec_selling(s, d):
    h = lede(s.get("lede")) + paras(s.get("prose"))
    groups = {}
    for m in s.get("methods") or []:
        groups.setdefault(m.get("group") or "Other", []).append(m)
    for g, ms in groups.items():
        yes = [m for m in ms if m.get("status") == "yes"]
        no = [m for m in ms if m.get("status") == "no"]
        unk = [m for m in ms if m.get("status") not in ("yes", "no")]
        h += f'<div class="sell"><h3>{e(g)}</h3>'
        h += ("<ul>" + "".join(f'<li><span class="tick" aria-hidden="true">✓</span><strong>{e(m.get("label"))}</strong>'
                               f'{detail(m, "note")}</li>'
                               for m in yes) + "</ul>") if yes else '<p class="note">Nothing here is confirmed.</p>'
        if no:
            h += f'<p class="rest"><span>Not present</span>{e(", ".join(m.get("label") for m in no))}</p>'
        if unk:
            h += f'<p class="rest"><span>Not checked</span>{e(", ".join(m.get("label") for m in unk))}</p>'
        h += "</div>"
    return h + callout(s.get("callout"))


def sec_margin(s, d):
    h = lede(s.get("lede")) + paras(s.get("prose"))
    c = s.get("cogs")
    if c and c.get("rows"):
        rows = [[e(r.get("line")), usd(r.get("perUnit"), True), tier(r.get("tier")), e(r.get("note"))] for r in c["rows"]]
        if num(c.get("total")):
            rows.append(["<strong>Landed cost per unit</strong>", f'<strong>{usd(c["total"], True)}</strong>', "", ""])
        h += f'<h3 id="landed-cost">Cost of goods, landed</h3>' + table(["Line", "Per unit", "Tier", "Basis"], rows, "", ["", "r", "", ""])
        h += note(c.get("note"))
        if c.get("freightos"):
            h += '<p class="credit">Freight estimate: <a href="https://www.freightos.com" target="_blank" rel="noopener noreferrer">Freightos</a></p>'
    lines = s.get("lines") or []
    rev, res = s.get("revenue") or {}, s.get("result")
    if lines:
        h += '<h3>The waterfall</h3>' + waterfall(rev, lines, res)
        rows = [[f'<strong>Revenue</strong>', usd(rev.get("monthly")), "100%", usd(rev.get("perUnit"), True),
                 tier(rev.get("tier")), e(rev.get("basis"))]]
        for l in lines:
            links = " ".join(a(k.get("label"), k.get("href")) for k in l.get("links") or [])
            rows.append([e(l.get("label")), usd(l.get("monthly")), pct(l.get("pct"), 2), usd(l.get("perUnit"), True),
                         tier(l.get("tier")), e(l.get("basis")) + (f'<div class="links">{links}</div>' if links else "")])
        if res:
            rows.append([f'<strong>{e(res.get("label") or "Profit")}</strong>', f'<strong>{usd(res.get("monthly"))}</strong>',
                         f'<strong class="acc">{pct(res.get("pct"), 1)}</strong>', usd(res.get("perUnit"), True),
                         tier(res.get("tier")), e(res.get("note"))])
        h += table(["Line", "A month", "Of revenue", "Per unit", "Tier", "Basis"], rows, "margin", ["", "r", "r", "r", "", ""])
    return h + callout(s.get("callout"))


def sec_advertising(s, d):
    h = ""
    st = s.get("strategy")
    if st:
        h += (f'<div class="strategy"><span class="eyebrow">Strategy</span><strong>{e(st.get("label"))}</strong>'
              f'<ul>{"".join(f"<li>{e(p)}</li>" for p in st.get("points") or [])}</ul></div>')
    b = s.get("band")
    if b:
        h += (f'<div class="kpis"><div><span>Modelled ad spend a month</span><strong>{usd(b.get("central"))}</strong>'
              f'<em>band {usd(b.get("low"))}–{usd(b.get("high"))}</em></div>'
              + (f'<div><span>Of revenue</span><strong>{pct(b.get("ratePct"), 2)}</strong><em>central</em></div>' if num(b.get("ratePct")) else "")
              + f'<div><span>Tier</span><strong>{tier(b.get("tier") or "derived")}</strong><em>{e(b.get("basis") or "modelled, a floor")}</em></div></div>')
    tk = s.get("topKeywords")
    if tk and tk.get("rows"):
        rows = [[e(r.get("keyword")), f'{r["searches"]:,}' if num(r.get("searches")) else "–", e(r.get("organicRank") or "–"),
                 e(r.get("sponsoredRank") or "–"), usd(r.get("bid"), True) if num(r.get("bid")) else "–"] for r in tk["rows"]]
        h += '<h3>Top keywords</h3>' + table(["Keyword", "Searches a month", "Organic rank", "Their ad rank", "Bid"], rows, "",
                                              ["", "r", "r", "r", "r"]) + note(tk.get("note"))
    pk = s.get("paidKeywords")
    if pk and pk.get("rows"):
        rows = [[e(r.get("keyword")), f'{r["searches"]:,}' if num(r.get("searches")) else "–",
                 pct(100 * r["share"], 1) if num(r.get("share")) else "–", usd(r.get("bid"), True) if num(r.get("bid")) else "–",
                 usd(r.get("spend"), True) if num(r.get("spend")) else "–"] for r in pk["rows"]]
        h += '<h3>Keywords they pay for</h3>' + table(["Keyword", "Searches a month", "Their share of ads", "Bid", "Ad spend a month"],
                                                      rows, "", ["", "r", "r", "r", "r"]) + note(pk.get("note"))
    h += paras(s.get("prose")) + channels(s.get("channels"))
    return h + callout(s.get("callout"))


def channels(items):
    if not items:
        return ""
    lis = "".join(
        f'<li><div class="ch-head"><span>{a(c.get("label"), c.get("href")) if c.get("href") else e(c.get("label"))}</span>'
        f'<strong>{e(c.get("value"))}</strong>{tier(c.get("tier"))}</div>'
        + (f'<p class="counted"><span>Counted</span> {e(c.get("counted"))}</p>' if c.get("counted") else "")
        + (f'<p class="note">{e(c.get("note"))}{" · " + e(c.get("source")) if c.get("source") else ""}</p>'
           if c.get("note") or c.get("source") else "") + "</li>" for c in items)
    return f'<ul class="channels">{lis}</ul>'


def sec_traffic(s, d):
    h = lede(s.get("lede")) + channels(s.get("channels"))
    bs = s.get("brandSearch")
    if bs and bs.get("values"):
        h += (f'<h3>Google searches for “{e(bs.get("keyword"))}”</h3>'
              + bars_svg([month_label(m, True) for m in bs.get("months") or []], bs["values"], " searches") + note(bs.get("note")))
    return h + paras(s.get("prose")) + callout(s.get("callout"))


def sec_tiktok(s, d):
    return lede(s.get("lede")) + channels(s.get("channels")) + paras(s.get("prose")) + callout(s.get("callout"))


def sec_listing(s, d):
    h = lede(s.get("lede"))
    if s.get("rows"):
        h += table(["", ""], [[e(r.get("label")), e(r.get("value"))] for r in s["rows"]], "kv")
    if s.get("strengths") or s.get("weaknesses"):
        h += ('<div class="two"><div><h3>What it does well</h3><ul>' + "".join(f"<li>{e(x)}</li>" for x in s.get("strengths") or [])
              + '</ul></div><div><h3>Where it is weak</h3><ul>' + "".join(f"<li>{e(x)}</li>" for x in s.get("weaknesses") or [])
              + "</ul></div></div>")
    return h + paras(s.get("prose")) + callout(s.get("callout"))


def sec_reviews(s, d):
    h = lede(s.get("lede"))
    hist = s.get("histogram") or {}
    if hist:
        h += '<div class="hist">' + "".join(
            f'<div><span>{k}★</span><i><b style="width:{min(max(hist.get(k) or 0, 0), 100)}%"></b></i><em>{e(pct(hist.get(k), 0))}</em></div>'
            for k in ("5", "4", "3", "2", "1") if k in hist) + "</div>"
    if s.get("customersSay"):
        h += f'<blockquote>{e(s["customersSay"])}<cite>Amazon’s “Customers say” summary</cite></blockquote>'
    if s.get("aspects"):
        rows = [[e(x.get("aspect")), e(x.get("mentions")),
                 f'<span class="pn"><b style="flex:{x.get("positive") or 0}"></b><i style="flex:{x.get("negative") or 0}"></i></span>'
                 f'{e(x.get("positive"))} / {e(x.get("negative"))}', f'<em>“{e(x.get("quote"))}”</em>' if x.get("quote") else ""]
                for x in s["aspects"]]
        h += table(["Aspect", "Mentions", "Positive / negative", "One quote"], rows, "aspects", ["", "r", "", ""])
    return h + note(s.get("sampleNote")) + paras(s.get("prose"))


def sec_owner(s, d):
    h = ""
    if s.get("facts"):
        h += '<dl class="facts">' + "".join(f'<div><dt>{e(f.get("label"))}</dt><dd>{e(f.get("value"))} {tier(f.get("tier"))}</dd></div>'
                                            for f in s["facts"]) + "</dl>"
    return h + paras(s.get("prose"))


def sec_valuation(s, d):
    h = lede(s.get("lede"))
    rng = f'{usd_k(s.get("value"))}' + (f'–{usd_k(s.get("valueHigh"))}' if num(s.get("valueHigh")) and s.get("valueHigh") != s.get("value") else "")
    h += (f'<div class="kpis"><div><span>Estimated value</span><strong>{e(rng)}</strong><em>an estimate, not an appraisal</em></div>'
          f'<div><span>Multiple</span><strong>{e(s.get("multiple"))}×</strong><em>of trailing-twelve net profit</em></div>'
          f'<div><span>Trailing-twelve profit</span><strong>{usd_k(s.get("profitTtm"))}'
          + (f'–{usd_k(s.get("profitTtmHigh"))}' if num(s.get("profitTtmHigh")) else "")
          + f'</strong><em>{tier(s.get("profitTier") or "derived")}</em></div></div>')
    adj = s.get("adjustments") or []
    if adj:
        mx = max([abs(x.get("delta") or 0) for x in adj] + [0.1])
        rows = "".join(
            f'<li><span class="lab">{e(x.get("label"))} {tier(x.get("tier"))}</span><span class="dv">'
            f'<i class="{"pos" if (x.get("delta") or 0) >= 0 else "neg"}" style="width:{50 * abs(x.get("delta") or 0) / mx:.1f}%;'
            f'{"left:50%" if (x.get("delta") or 0) >= 0 else "right:50%"}"></i></span>'
            f'<em>{"+" if (x.get("delta") or 0) >= 0 else "−"}{abs(x.get("delta") or 0):g}</em></li>' for x in adj)
        h += (f'<h3>Why the multiple</h3><p class="note">Starts at {e(s.get("base", 2.6))}×; each factor the evidence supports moves it.</p>'
              f'<ul class="adj">{rows}</ul>')
    if s.get("missingSignals"):
        h += ('<p class="rest"><span>Only the owner can answer</span>' + e(", ".join(s["missingSignals"])) + "</p>"
              + (f'<p class="note">Their answers could move the multiple from {e(s.get("worst"))}× to {e(s.get("best"))}×.</p>'
                 if s.get("worst") is not None else ""))
    return h + paras(s.get("prose")) + callout(s.get("disclaimer"))


def sec_analysis(s, d):
    return paras(s.get("paragraphs"), "prose big")


def sec_similar(s, d):
    items = s.get("items") or []
    if not items:
        return ""
    cards = "".join(
        f'<li>{a(i.get("name"), i.get("href"))}<span>{e(i.get("tagline"))}</span>'
        f'<em>{e(" · ".join(x for x in [usd_k(i.get("revenue")) + "/mo revenue" if num(i.get("revenue")) else "", usd_k(i.get("profit")) + "/mo profit" if num(i.get("profit")) else "", pct(i.get("marginPct")) + " margin" if num(i.get("marginPct")) else ""] if x))}</em></li>'
        for i in items)
    return lede(s.get("lede")) + f'<ul class="similar">{cards}</ul>'


SECTIONS = {"timeline": sec_timeline, "revenue": sec_revenue, "selling": sec_selling, "margin": sec_margin,
            "advertising": sec_advertising, "traffic": sec_traffic, "tiktok": sec_tiktok, "listing": sec_listing,
            "reviews": sec_reviews, "owner": sec_owner, "valuation": sec_valuation, "analysis": sec_analysis,
            "similar": sec_similar}


# ─── page ────────────────────────────────────────────────────────────

CSS = """
:root{color-scheme:light;--bg:#fff;--surface:#fbfbfd;--fg:#14141b;--muted:#f3f3f7;--mfg:#5f6072;--border:#e4e4ec;
--accent:#5b3df5;--tint:#efecfe;--warn:#8a5a00;--warn-t:#fdf3e1;--s-rev:#5b3df5;--s-profit:#a08ff0;--s-ads:#c2378f;
--c1:#b0b0c2;--c2:#9596a9;--c3:#78798d;--c4:#5f6072;--r:10px}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:880px;margin:0 auto;padding:24px 16px 48px}
a{color:var(--accent);text-decoration:underline;text-decoration-color:rgba(91,61,245,.35);text-underline-offset:2px}
h1{font-size:1rem;margin:0;font-weight:650}h2{font-size:1.3rem;font-weight:650;margin:.2rem 0 .8rem;letter-spacing:-.01em}
h3{font-size:1rem;font-weight:650;margin:1.4rem 0 .5rem}
.eyebrow{display:block;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--mfg);font-weight:600}
.top{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.tagline{color:var(--mfg)}
.headline h2{font-size:1.65rem;line-height:1.2;margin:.9rem 0 .5rem;letter-spacing:-.02em}
.headline .sub{font-size:1.05rem;color:#2c2c38;margin:0 0 .5rem}.asof{font-size:.8rem;color:var(--mfg)}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:20px 0}
.card{border:1px solid var(--border);border-radius:var(--r);padding:12px;background:var(--surface);min-width:0}
.card>span{font-size:.75rem;color:var(--mfg);display:block}.card strong{font-size:1.4rem;display:block;font-variant-numeric:tabular-nums}
.card em{font-style:normal;font-size:.72rem;color:var(--mfg);display:block;line-height:1.35}.card.acc strong{color:var(--accent)}
.facts{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px 18px;margin:12px 0}
.facts dt{font-size:.75rem;color:var(--mfg)}.facts dd{margin:0;font-weight:600}
nav.toc{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0 8px}nav.toc a{font-size:.8rem;text-decoration:none;border:1px solid var(--border);border-radius:99px;padding:3px 10px;color:var(--fg)}
section{border-top:1px solid var(--border);padding-top:22px;margin-top:30px}
.photos{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:14px 0}
.photos figure{margin:0;border:1px solid var(--border);border-radius:var(--r);overflow:hidden;background:#fff}
.photos img{width:100%;aspect-ratio:1/1;object-fit:contain;display:block}
.photos figcaption{font-size:.72rem;color:var(--mfg);padding:4px 8px;border-top:1px solid var(--border)}
.lede{font-size:1.02rem}.prose{margin:.6rem 0}.prose.big{font-size:1.02rem}
.note{font-size:.8rem;color:var(--mfg);margin:.4rem 0}.credit{font-size:.8rem;margin:.3rem 0}
.callout{border-left:3px solid var(--accent);background:var(--tint);padding:10px 14px;border-radius:0 var(--r) var(--r) 0;margin:14px 0;font-size:.9rem}
.tablewrap{overflow-x:auto;margin:8px 0}table{border-collapse:collapse;width:100%;font-size:.86rem}
th{font-size:.72rem;color:var(--mfg);font-weight:600;text-align:left;border-bottom:1px solid var(--border);padding:6px 8px}
td{border-bottom:1px solid var(--border);padding:7px 8px;vertical-align:top}td.r,th.r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
table.kv td:first-child{color:var(--mfg);width:34%}table.kv thead{display:none}
.tier{display:inline-block;font-size:.66rem;font-weight:650;border-radius:99px;padding:1px 7px;vertical-align:middle;white-space:nowrap;border:1px solid var(--border)}
.t-given{background:#e7f2ec;color:#10683f;border-color:#cde5d7}.t-derived{background:var(--tint);color:#3f28c8;border-color:#ddd6fd}
.t-assumed{background:var(--warn-t);color:var(--warn);border-color:#f1dcb4}.t-inferred{background:var(--muted);color:var(--mfg)}
.chart{width:100%;height:auto;display:block}.chart .grid{stroke:var(--border);stroke-width:1}.chart .ax{font-size:11px;fill:var(--mfg)}
.chart .band{fill:var(--s-rev);opacity:.12}.chart .pt{fill:var(--s-rev);stroke:#fff;stroke-width:2;opacity:0}.chart .hit:hover .pt{opacity:1}
.chart .hit:hover rect{fill:rgba(91,61,245,.05)}.dot-f{fill:var(--fg);stroke:#fff;stroke-width:2}.dot-h{fill:#fff;stroke:var(--fg);stroke-width:2}
.chart .lab{font-size:12px;fill:var(--fg)}.chart .val{font-size:12px;fill:var(--mfg);font-variant-numeric:tabular-nums}.chart .strong{font-weight:700;fill:var(--fg)}
.wf-rev{fill:var(--c1)}.wf-c1{fill:var(--c1)}.wf-c2{fill:var(--c2)}.wf-c3{fill:var(--c3)}.wf-c4{fill:var(--c4)}.wf-left{fill:var(--accent)}
.chart .bar{fill:var(--s-profit)}
figure.perf{margin:10px 0 0}.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.78rem;color:var(--mfg);margin-top:6px}
.lg{display:inline-flex;align-items:center;gap:6px}.lg i{display:inline-block;width:22px}.lg-band{height:10px;background:rgba(91,61,245,.15)}
.lg-dot{width:10px!important;height:10px;border-radius:50%;border:2px solid var(--fg)}
details.numbers{margin:6px 0}details summary{cursor:pointer;font-size:.8rem;color:var(--accent)}
.stack{display:flex;gap:2px;height:14px;border-radius:4px;overflow:hidden;margin:8px 0}
.seg.s0{background:#5b3df5}.seg.s1{background:#7d66f3}.seg.s2{background:#a08ff0}.seg.s3{background:#bfb3f5}.seg.s4,.seg.s5{background:#dcd5fa}
.prod{display:flex;gap:10px;align-items:center}.thumb{width:48px;height:48px;object-fit:contain;border:1px solid var(--border);border-radius:6px;background:#fff;flex:none}
.asin{display:block;font-size:.7rem;color:var(--mfg)}
.sell h3{margin-bottom:.3rem}.sell ul{list-style:none;padding:0;margin:0}.sell li{padding:6px 0;border-bottom:1px solid var(--border)}
.sell li p{margin:.15rem 0 0 1.4rem;font-size:.84rem;color:var(--mfg)}.tick{color:var(--accent);font-weight:700;margin-right:.5rem}
.rest{font-size:.84rem;color:var(--mfg);margin:.4rem 0}.rest span{font-weight:650;color:var(--fg);margin-right:.5rem}
table.margin td:first-child{white-space:nowrap}.links{margin-top:3px;display:flex;flex-wrap:wrap;gap:2px 12px;font-size:.78rem}.acc{color:var(--accent)}
.strategy{border:1px solid var(--border);border-radius:var(--r);padding:12px 14px;background:var(--surface)}.strategy strong{font-size:1.1rem}
.strategy ul{margin:.4rem 0 0;padding-left:1.1rem}
.kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}.kpis div{border:1px solid var(--border);border-radius:var(--r);padding:10px 12px}
.kpis div>span{font-size:.75rem;color:var(--mfg);display:block}.kpis strong{font-size:1.25rem;display:block}.kpis em{font-style:normal;font-size:.75rem;color:var(--mfg)}
.channels{list-style:none;padding:0;margin:8px 0}.channels li{border-bottom:1px solid var(--border);padding:9px 0}
.ch-head{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.ch-head span{font-weight:600;flex:1;min-width:150px}.ch-head strong{font-variant-numeric:tabular-nums}
.counted{font-size:.8rem;margin:.2rem 0;color:var(--mfg)}.counted span{font-weight:650;color:var(--fg)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:18px}.two ul{padding-left:1.1rem;margin:0}.two li{margin:.25rem 0}
.hist{max-width:420px}.hist div{display:grid;grid-template-columns:32px 1fr 40px;gap:8px;align-items:center;font-size:.82rem}
.hist i{display:block;height:9px;background:var(--muted);border-radius:4px;overflow:hidden}.hist b{display:block;height:100%;background:var(--accent);border-radius:4px}
.hist em{font-style:normal;color:var(--mfg);text-align:right}
blockquote{margin:14px 0;padding:10px 14px;border-left:3px solid var(--border);color:#2c2c38}blockquote cite{display:block;font-size:.75rem;color:var(--mfg);font-style:normal;margin-top:4px}
table.aspects td:nth-child(3){white-space:nowrap}
.pn{display:inline-flex;width:70px;height:8px;gap:2px;margin-right:8px;vertical-align:middle}.pn b{background:var(--accent);border-radius:3px}.pn i{background:var(--s-ads);border-radius:3px}
.adj{list-style:none;padding:0;margin:0}.adj li{display:grid;grid-template-columns:minmax(0,1.3fr) 1fr 44px;gap:10px;align-items:center;padding:5px 0;border-bottom:1px solid var(--border);font-size:.86rem}
.adj .dv{position:relative;height:10px;background:linear-gradient(var(--border),var(--border)) center/1px 100% no-repeat}
.adj .dv i{position:absolute;top:0;height:100%;border-radius:3px}.adj .pos{background:var(--accent)}.adj .neg{background:var(--c3)}.adj em{font-style:normal;text-align:right;font-variant-numeric:tabular-nums}
.similar{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.similar li{border:1px solid var(--border);border-radius:var(--r);padding:10px 12px}.similar span{display:block;font-size:.82rem;color:var(--mfg)}.similar em{font-style:normal;font-size:.8rem}
.na{font-size:.86rem;color:var(--mfg);border:1px dashed var(--border);border-radius:var(--r);padding:8px 12px;margin-top:22px}
.na strong{color:var(--fg)}
.timeline{list-style:none;padding:0;margin:0}.timeline li{display:grid;grid-template-columns:150px 1fr;gap:12px;padding:8px 0;border-bottom:1px solid var(--border)}
.timeline .when{font-size:.84rem;font-variant-numeric:tabular-nums}.timeline .tag{display:block;font-size:.7rem;color:var(--mfg)}.timeline p{margin:.15rem 0 0;font-size:.84rem;color:var(--mfg)}
footer{border-top:1px solid var(--border);margin-top:36px;padding-top:14px;font-size:.8rem;color:var(--mfg)}
@media (max-width:680px){.cards,.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.two{grid-template-columns:1fr}
.photos{grid-template-columns:1fr 1fr}.timeline li{grid-template-columns:1fr}
.headline h2{font-size:1.35rem}.adj li{grid-template-columns:1fr 80px 40px}}
@media print{nav.toc,details summary{display:none}section{break-inside:avoid-page}}
"""


def render(d):
    WARN.clear()
    for k in ("brand", "snapshotMonth"):
        if not d.get(k):
            raise ValueError(f"missing required field: {k}")
    snap = d["snapshotMonth"]
    secs = d.get("sections") or {}
    na = {x.get("section"): x.get("why") for x in d.get("notAvailable") or []}
    hd = d.get("headline") or {}
    cards = d.get("cards") or []

    # headline parity: the title's figure is the card's figure, as the card renders it
    if hd.get("title"):
        basis = hd.get("figureBasis", "profit")
        card = next((c for c in cards if c.get("key") == basis), None)
        if card and num(card.get("value")) and usd_k(card["value"]) not in hd["title"]:
            WARN.append(f"headline parity: the title should carry {usd_k(card['value'])} (the {basis} card), it does not")
        if re.search(r"\b(I|we|We|my|our|Our)\b", hd.get("title", "") + " " + hd.get("subtitle", "")):
            WARN.append("headline voice: first person found; the copy is observational ('they'), never the founder's voice")
    for f in d.get("figures") or []:
        if f.get("tier") not in TIERS:
            WARN.append(f"figure without a valid tier: {f.get('figure')}")
        if f.get("tier") in ("derived", "given") and not f.get("source"):
            WARN.append(f"figure without a source: {f.get('figure')}")

    p = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
         f'<title>{e(d["brand"])} case study</title><meta name="description" content="{e(hd.get("title") or d.get("tagline"))}">',
         f'<style>{CSS}</style></head><body><main>']
    p.append(f'<header><div class="top"><h1>{e(d["brand"])}</h1><span class="tagline">{e(d.get("tagline"))}</span></div>'
             + (f'<span class="eyebrow" style="margin-top:6px">{e(d.get("eyebrow"))}</span>' if d.get("eyebrow") else ""))
    if hd.get("title"):
        p.append(f'<div class="headline"><h2>{e(hd["title"])}</h2><p class="sub">{e(hd.get("subtitle"))}</p></div>')
    p.append(f'<p class="asof">Read {e(month_label(snap))}. Figures here are a reading taken then from public data, not a live '
             f'feed and not the seller’s books. Each one is marked given, derived or assumed.</p></header>')

    if cards:
        p.append('<div class="cards">' + "".join(
            f'<div class="card{" acc" if c.get("key") == "profit" else ""}"><span>{e(c.get("label"))}</span>'
            f'<strong>{e(fmt_card(c))}</strong><em>{e(c.get("basis"))} {tier(c.get("tier"))}</em></div>' for c in cards) + "</div>")

    present = [(k, g, t) for k, g, t in ORDER if secs.get(k) or k in na or (k == "timeline" and d.get("events"))]
    toc = "".join(f'<a href="#{k}">{e((secs.get(k) or {}).get("title") or t)}</a>' for k, g, t in present if secs.get(k) or k == "timeline")
    p.append(f'<nav class="toc">{toc}<a href="#figures">How each figure was built</a><a href="#sources">Sources</a></nav>')

    # overview: intro, photos, performance chart, additional metrics
    p.append('<section id="overview" style="border-top:none;margin-top:8px;padding-top:0">')
    if d.get("intro"):
        p.append(f'<p class="lede">{e(d["intro"])}</p>')
    photos = [x for x in d.get("photos") or [] if x.get("src")][:5]
    if photos:
        p.append('<div class="photos">' + "".join(
            f'<figure>{img(x["src"], x.get("alt") or d["brand"])}<figcaption>{e(x.get("caption") or x.get("asin"))}</figcaption></figure>'
            for x in photos) + "</div>")
    if d.get("series"):
        p.append('<h3>Revenue, profit and ad spend, month by month</h3>' + perf_chart(d["series"], d.get("events")) + note(d["series"].get("note")))
    if d.get("facts"):
        p.append('<h3>Additional metrics</h3><dl class="facts">' + "".join(
            f'<div><dt>{e(f.get("label"))}</dt><dd>{e(f.get("value"))} {tier(f.get("tier"))}</dd></div>' for f in d["facts"]) + "</dl>")
    p.append("</section>")

    rendered, group = [], None
    for k, g, t in present:
        s = secs.get(k) or {}
        body = SECTIONS[k](s, d) if (s or k == "timeline") else ""
        if not body.strip():
            if k in na:
                p.append(f'<p class="na"><strong>{e(t)}</strong> — {e(na[k])}</p>')
            continue
        rendered.append(k)
        eb = g if g != group else ""
        group = g
        p.append(f'<section id="{k}">' + (f'<span class="eyebrow">{e(eb)}</span>' if eb else "")
                 + f'<h2>{e(s.get("title") or t)}</h2>{body}</section>')
    for k, why in na.items():
        if k not in SECTIONS:
            p.append(f'<p class="na"><strong>{e(k)}</strong> — {e(why)}</p>')

    figs = d.get("figures") or []
    if figs:
        rows = [[e(f.get("figure")), e(f.get("value")), tier(f.get("tier")), e(f.get("source")), e(f.get("note"))] for f in figs]
        p.append('<section id="figures"><span class="eyebrow">Provenance</span><h2>How each figure was built</h2>'
                 '<p class="note"><strong>Given</strong>: a number the user supplied. <strong>Derived</strong>: computed from the named '
                 'source. <strong>Assumed</strong>: a default put in so the sum completes; replace it first. <strong>Inferred</strong>: '
                 'read from the public record, to put to the owner. Revenue is a floor (Amazon’s sales badge, unbadged listings count '
                 'as zero); profit is a ceiling (returns, storage and overhead are not counted).</p>'
                 + table(["Figure", "Value", "Tier", "Source", "Note"], rows) + "</section>")
    srcs, links = d.get("sources") or [], d.get("links") or []
    p.append('<section id="sources"><span class="eyebrow">Links &amp; sources</span><h2>Links and sources</h2>')
    if links:
        p.append("<h3>Links</h3><ul>" + "".join(f"<li>{a(l.get('label'), l.get('href'))}</li>" for l in links) + "</ul>")
    if srcs:
        p.append("<h3>Sources</h3><ul>" + "".join(
            f"<li>{a(x.get('label'), x.get('url')) if x.get('url') else e(x.get('label'))}"
            f"{' · ' + e(x.get('retrievedAt')) if x.get('retrievedAt') else ''}{' · ' + e(x.get('cost')) if x.get('cost') else ''}</li>"
            for x in srcs) + "</ul>")
    if d.get("spend"):
        p.append(note("Spent on this case study: " + ", ".join(f"{k} {v}" for k, v in d["spend"].items())))
    p.append("</section>")
    p.append(f'<footer><p>An estimate from public data, not the seller’s books, an appraisal or financial advice. Built '
             f'{e(d.get("builtAt") or date.today().isoformat())}.</p><p><a href="{REPO}" target="_blank" rel="noopener noreferrer">'
             f'Built with WaitHowMuch skills</a> · {a("waithowmuch.com", "https://waithowmuch.com/")}</p></footer>')
    p.append("</main></body></html>")
    return "".join(p), rendered


def fmt_card(c):
    v, f = c.get("value"), c.get("format", "usd")
    if f == "pct":
        return pct(v, 1)
    if f == "text":
        return str(v)
    s = usd_k(v)
    if num(c.get("high")) and c.get("high") != v:
        s += "–" + usd_k(c["high"]).lstrip("$")
    return s


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(4)
    src = args[0]
    dst = args[args.index("-o") + 1] if "-o" in args else os.path.splitext(src)[0] + ".html"
    try:
        with open(src, encoding="utf-8") as f:
            d = json.load(f)
        doc, rendered = render(d)
    except (OSError, ValueError, json.JSONDecodeError) as ex:
        print(json.dumps({"error": "bad_input", "message": str(ex)}))
        sys.exit(4)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(doc)
    print(json.dumps({"written": os.path.abspath(dst), "bytes": len(doc.encode()), "sections": rendered,
                      "warnings": WARN}, indent=1))


if __name__ == "__main__":
    main()
