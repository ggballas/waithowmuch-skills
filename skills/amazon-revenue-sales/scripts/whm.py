#!/usr/bin/env python3
"""WaitHowMuch skills data helper, amazon-revenue-sales: sales and revenue OVER TIME for an ASIN,
a brand or a seller's store. One WHM API key, or your own Keepa key.

Shared core (mode, HTTP, Keepa client, badge method) is the same in every skill's scripts/whm.py.
Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key
(Keepa takes its key in the query string, so no URL is ever printed).

Mode, decided per run from the environment:
  1. WHM_API_KEY set   -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
  2. KEEPA_API_KEY set -> Keepa API directly (your tokens)
  3. neither           -> {"error": "no_keys", ...}, exit 2
A WHM route that is not live yet returns {"error": "whm_route_not_live"}; if KEEPA_API_KEY is also
set, the command falls back to Keepa instead.

Commands:
  mode                                     which mode this run would use (no provider call)
  product <ASIN|amazon.com URL> [--months N]        monthly series + current month   (Keepa: 1 token)
  brand "<brand name>" [--max N] [--months N]       brand catalogue series           (Keepa: ~11 + N)
  store <seller ID|seller URL|ASIN> [--max N] [--full] [--months N]
                                           a seller's storefront series     (Keepa: ~21 + N; +3 from an ASIN;
                                           --full prices every storefront ASIN: ~10 + 1 per ASIN)
  api </v1/path?query>                     GET a WaitHowMuch API route (WHM mode only)

Series = each month end's "bought in past month" badge x TODAY's price, from the first whole month of
badge history (Amazon's badge history starts mid-2023) unless --months N cuts it; the current month
is the live badge. Every figure is a floor-bucket range (low/high).

Exit codes: 0 ok, 1 upstream/API error, 2 no keys / wrong mode / route not live, 3 not enough Keepa tokens, 4 bad input.
"""
import gzip
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

VERSION = "0.4.1"
WHM_API = os.environ.get("WHM_API_BASE", "").strip().rstrip("/") or "https://api.waithowmuch.com"
KEEPA = "https://api.keepa.com"
US = 1
KEEPA_EPOCH_MIN = 21_564_000  # Keepa time = minutes since 2011-01-01 UTC
BADGE_THRESHOLD = 50
BADGE_FLOOR = date(2023, 7, 1)  # Amazon's badge (and Keepa's monthlySoldHistory) starts mid-2023
NOT_A_SELLER = {"ATVPDKIKX0DER", "-1", "-2", ""}  # Amazon itself, suppressed, unknown

SKILL = (os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) or "unknown").lower()
TAG = {"client": "whm-skills", "skill": SKILL, "v": VERSION}


# ─── Usage count ─────────────────────────────────────────────────────
# One anonymous GET per command run, in every mode (WHM, your own keys, none), so runs on your own
# keys are counted too: GET /health?client=whm-skills&skill=..&v=..&event=run&cmd=<command>&mode=
# whm|own|none. Nothing else: no arguments, ASINs, brands, prompts or keys; no key header. It runs
# in the background with a 2 s cap and never fails or changes the command. Off: WHM_USAGE=0.
import atexit  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

COMMANDS = {"api", "brand", "mode", "product", "store"}
_USAGE = {}


def usage_mode():
    try:
        md = mode()
        if md == "none" and "keyword_mode" in globals():
            md = globals()["keyword_mode"]() or "none"
    except Exception:  # noqa: BLE001
        return "none"
    return md if md in ("whm", "none") else "own"


def usage_ping(cmd):
    """Start the one usage ping for this run (event=invoke for the invoke command). Never raises."""
    if _USAGE or os.environ.get("WHM_USAGE", "").strip() == "0":
        return
    try:
        q = urllib.parse.urlencode({**TAG, "event": "invoke" if cmd == "invoke" else "run",
                                    "cmd": cmd if cmd in COMMANDS else "usage", "mode": usage_mode()})
        req = urllib.request.Request(f"{WHM_API}/health?{q}", headers={"User-Agent": f"whm-skills/{VERSION}"})

        def send():
            try:
                with urllib.request.urlopen(req, timeout=2) as r:
                    _USAGE["status"] = r.status
            except urllib.error.HTTPError as e:
                _USAGE["status"] = e.code
            except Exception:  # noqa: BLE001
                _USAGE["status"] = 0

        t = threading.Thread(target=send, daemon=True)
        _USAGE.update(thread=t, deadline=time.monotonic() + 2)
        t.start()
        atexit.register(usage_wait)
    except Exception:  # noqa: BLE001
        pass


def usage_wait():
    """Let the ping finish, at most 2 s after it started. Returns its status (0 = not reached, None = off)."""
    t = _USAGE.get("thread")
    if t:
        t.join(max(0.0, _USAGE["deadline"] - time.monotonic()))
    return _USAGE.get("status")


def out(obj, code=0):
    print(json.dumps(obj, indent=1, ensure_ascii=False))
    sys.exit(code)


def has(var):
    return bool(os.environ.get(var, "").strip())


def mode():
    if has("WHM_API_KEY"):
        return "whm"
    if has("KEEPA_API_KEY"):
        return "keepa"
    return "none"


NO_KEYS = {
    "error": "no_keys",
    "message": "Set ONE of: WHM_API_KEY (Option B: one WaitHowMuch API key, covers everything) "
               "or KEEPA_API_KEY (Option A: your own paid Keepa API plan, https://keepa.com/#!api; "
               "you pay Keepa tokens per lookup). In Claude Code: /plugin > waithowmuch > "
               "Configure options. Elsewhere: an environment variable. "
               "https://github.com/ggballas/waithowmuch-skills#data-providers",
}


# ─── HTTP ────────────────────────────────────────────────────────────

def _fetch(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers={"Accept-Encoding": "gzip", "User-Agent": f"whm-skills/{VERSION}",
                                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return r.status, json.loads(raw or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            if e.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            body = json.loads(raw or b"{}")
        except Exception:  # noqa: BLE001
            body = {}
        return e.code, body
    except Exception as e:  # noqa: BLE001  (network: never echo the URL, it may hold a key)
        return 0, {"error": "unreachable", "detail": type(e).__name__}


def whm_get(path, allow=()):
    """GET a WHM route. Non-200 exits, except statuses in `allow`, which are returned as (status, body)."""
    if not path.startswith("/v1/"):
        out({"error": "bad_path", "message": "path must start with /v1/"}, 4)
    sep = "&" if "?" in path else "?"
    status, body = _fetch(f"{WHM_API}{path}{sep}{urllib.parse.urlencode(TAG)}",
                          headers={"X-WHM-Key": os.environ["WHM_API_KEY"].strip()})
    if status == 200 or status in allow:
        return status, body
    out({"mode": "whm", "status": status, **(body if isinstance(body, dict) else {})}, 1)


def route_missing(status, body):
    """The API answers an unknown route with a bare 404 {"error": "not_found"}."""
    return status == 404 and isinstance(body, dict) and body == {"error": "not_found"}


def not_live(route, note):
    return {"mode": "whm", "error": "whm_route_not_live", "route": route, "note": note,
            "fallback": "Set KEEPA_API_KEY too (Option A) and this command runs on your own Keepa key."}


class Keepa:
    def __init__(self):
        self.key = os.environ["KEEPA_API_KEY"].strip()
        self.used = 0
        self.left = None

    def call(self, path, params, body=None):
        qs = urllib.parse.urlencode({"key": self.key, "domain": US, **params})
        data = json.dumps(body).encode() if body is not None else None
        status, res = _fetch(f"{KEEPA}/{path}?{qs}", headers={"Content-Type": "application/json"} if data else None, data=data)
        self.used += res.get("tokensConsumed") or 0
        if isinstance(res.get("tokensLeft"), int):
            self.left = res["tokensLeft"]
        if status == 429:
            out({"mode": "keepa", "error": "keepa_tokens_low", "tokensLeft": res.get("tokensLeft"),
                 "refillInSec": round((res.get("refillIn") or 60000) / 1000), **self.meta()}, 3)
        if status in (401, 402, 403):
            out({"mode": "keepa", "error": "keepa_key_rejected", "status": status,
                 "message": "Keepa refused the key (invalid, or no active API plan)."}, 1)
        if status != 200:
            out({"mode": "keepa", "error": "keepa_error", "status": status, **self.meta()}, 1)
        return res

    def ensure(self, need):
        """Refuse up front rather than drain or stall: /token is free."""
        t = self.call("token", {})
        left, rate = t.get("tokensLeft", 0), t.get("refillRate") or 0
        if left < need:
            wait = math.ceil((need - left) / rate) * 60 if rate else None
            out({"mode": "keepa", "error": "keepa_tokens_low", "needed": need, "tokensLeft": left,
                 "refillPerMin": rate, "waitSec": wait, **self.meta()}, 3)

    def meta(self):
        return {"tokensConsumed": self.used, "tokensLeft": self.left}


# ─── The badge method (same as WaitHowMuch's /v1/tools/product-sales) ─

ASIN_RE = re.compile(r"^(?:B0[A-Z0-9]{8}|\d{9}[\dX])$")
ASIN_IN_PATH = re.compile(r"/(?:dp|gp/product|gp/aw/d|product|d)/([A-Z0-9]{10})(?:[/?]|$)", re.I)
SELLER_RE = re.compile(r"^A[A-Z0-9]{9,20}$")


def parse_asin(raw, fatal=True):
    s = raw.strip()
    if ASIN_RE.match(s.upper()):
        return s.upper()
    u = urllib.parse.urlparse(s if re.match(r"^https?://", s, re.I) else "https://" + s)
    host = (u.hostname or "").lower()
    err = None
    if host in ("a.co", "amzn.to", "amzn.com", "amzn.eu"):
        err = {"error": "invalid_asin", "reason": "short_link", "message": "Open the short link and paste the full amazon.com URL."}
    elif not (host == "amazon.com" or host.endswith(".amazon.com")):
        err = {"error": "invalid_asin", "reason": "us_only" if re.search(r"(^|\.)amazon\.[a-z.]+$", host) else "not_amazon"}
    else:
        m = ASIN_IN_PATH.search(u.path)
        asin = (m.group(1) if m else (urllib.parse.parse_qs(u.query).get("asin") or [""])[0]).upper()
        if ASIN_RE.match(asin):
            return asin
        err = {"error": "invalid_asin", "reason": "no_asin"}
    if fatal:
        out(err, 4)
    return None


def badge_range(v):
    """Amazon's "N+ bought in past month" is a floor bucket, ends inclusive: 1K+ = 1,000-1,999."""
    if not v or v <= 0:
        return None
    if v < 100:
        return v, 99
    step = 10 ** int(math.floor(math.log10(v)))
    return v, v + step - 1


def badge_label(v):
    return f"{v / 1_000_000:g}M+" if v >= 1_000_000 else f"{v / 1000:g}K+" if v >= 1000 else f"{v}+"


def kdate(minute):
    return datetime.fromtimestamp((minute + KEEPA_EPOCH_MIN) * 60, timezone.utc)


def kminutes(dt):
    return int(dt.timestamp() // 60) - KEEPA_EPOCH_MIN


def last_badge(hist):
    hist = hist or []
    for i in range(len(hist) - 2, -1, -2):
        if isinstance(hist[i + 1], int) and hist[i + 1] > 0:
            return {"units": hist[i + 1], "label": badge_label(hist[i + 1]), "seenAt": kdate(hist[i]).date().isoformat()}
    return None


def pick_price(stats):
    """Buy box, then lowest new, then Amazon's own offer. Cents. Keepa uses -1/-2 for none/unknown."""
    st = stats or {}
    if (st.get("buyBoxPrice") or 0) > 0:
        return {"cents": st["buyBoxPrice"], "source": "buy_box"}
    cur = st.get("current") or []
    for idx, src in ((18, "buy_box"), (1, "new"), (0, "amazon")):
        if len(cur) > idx and (cur[idx] or 0) > 0:
            return {"cents": cur[idx], "source": src}
    return None


def pos(v):
    return v if isinstance(v, (int, float)) and v > 0 else None


def shape(p):
    rng, price = badge_range(p.get("monthlySold")), pick_price(p.get("stats"))
    L, W, H, G = (pos(p.get(k)) for k in ("packageLength", "packageWidth", "packageHeight", "packageWeight"))
    root = p.get("rootCategory")
    series = (p.get("salesRanks") or {}).get(str(root)) if root is not None else None
    return {
        "asin": p["asin"], "marketplace": "us", "url": f"https://www.amazon.com/dp/{p['asin']}",
        "title": p.get("title"), "brand": p.get("brand"), "manufacturer": p.get("manufacturer"),
        "categoryPath": [c.get("name") for c in (p.get("categoryTree") or [])],
        "listedSince": kdate(p["listedSince"]).date().isoformat() if (p.get("listedSince") or 0) > 0 else None,
        "salesRank": pos(series[-1]) if series and len(series) >= 2 else None,
        "units": ({"source": "amazon_badge", "badge": rng[0], "label": badge_label(rng[0]), "low": rng[0], "high": rng[1], "lastBadge": None}
                  if rng else {"source": "none", "badge": None, "label": None, "low": 0, "high": BADGE_THRESHOLD - 1,
                               "lastBadge": last_badge(p.get("monthlySoldHistory"))}),
        "price": price,
        "revenue": {"lowCents": rng[0] * price["cents"], "highCents": rng[1] * price["cents"]} if rng and price else None,
        "package": {"lengthMm": L, "widthMm": W, "heightMm": H, "weightG": G} if L and W and H and G else None,
        "amazonFbaFeeCents": pos((p.get("fbaFees") or {}).get("pickAndPackFee")),
        "referralFeePercent": pos(p.get("referralFeePercentage")),
    }


def badge_at(hist, minute):
    v = None
    for i in range(0, len(hist) - 1, 2):
        if hist[i] > minute:
            break
        v = hist[i + 1]
    return v


def month_ends(n, now):
    """The last n month ends BEFORE the current month, oldest first: [(YYYY-MM, keepa minute)]."""
    res, y, m = [], now.year, now.month
    for _ in range(n):
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        nxt = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
        res.append((f"{y}-{m:02d}", kminutes(nxt) - 1))
    return list(reversed(res))


def series(products, months=None):
    """research-amazon-store's method: each month end's badge in effect x TODAY's price, summed.
    Starts at the first WHOLE month after the oldest badge reading (a month the badge began partway
    through would count its unbadged days as zero), unless `months` cuts it (current month included).
    The last row is the current month, from the live badge."""
    now = datetime.now(timezone.utc)
    priced = [(p, pick_price(p.get("stats"))) for p in products]
    priced = [(p, pr) for p, pr in priced if pr]
    if months:
        n = max(months - 1, 0)
    else:
        first = min((p["monthlySoldHistory"][0] for p, _ in priced if p.get("monthlySoldHistory")), default=None)
        if first is None:
            n = 0
        else:
            f = kdate(first)
            y, m = (f.year + 1, 1) if f.month == 12 else (f.year, f.month + 1)
            n = max((now.year - y) * 12 + now.month - m, 0)
    rows = []

    def add(label, val_of, live=False):
        ulo = uhi = lo = hi = badged = 0
        for p, pr in priced:
            rng = badge_range(val_of(p))
            if rng:
                badged += 1
                ulo, uhi = ulo + rng[0], uhi + rng[1]
                lo, hi = lo + rng[0] * pr["cents"], hi + rng[1] * pr["cents"]
        rows.append({"month": label, "unitsLow": ulo, "unitsHigh": uhi, "revenueLowCents": lo, "revenueHighCents": hi,
                     "badgedAsins": badged, **({"live": True} if live else {})})

    for label, end in month_ends(n, now):
        add(label, lambda p, e=end: badge_at(p.get("monthlySoldHistory") or [], e))
    add(now.strftime("%Y-%m"), lambda p: p.get("monthlySold"), live=True)
    return rows


def trend(rows):
    """Trailing twelve full months (never this month x 12) and the peak month."""
    full = [r for r in rows if not r.get("live")]
    ttm = full[-12:]
    peak = max(full, key=lambda r: r["revenueLowCents"], default=None)
    return {
        "ttmMonths": len(ttm),
        "ttmRevenueLowCents": sum(r["revenueLowCents"] for r in ttm),
        "ttmRevenueHighCents": sum(r["revenueHighCents"] for r in ttm),
        "peakMonth": peak["month"] if peak and peak["revenueLowCents"] else None,
    }


METHOD = ("Units = Amazon's 'N+ bought in past month' badge as Keepa records it (a floor bucket, so a range); "
          "revenue = units x today's price (buy box, else lowest new, else Amazon). Each past month = the badge in effect "
          "at that month's end x today's price; the current month is the live badge. Listings without a badge "
          "(under ~50/month each) count as zero, so every total is a floor.")


def products(k, asins, history=True):
    since_days = (date.today() - BADGE_FLOOR).days
    res = []
    for i in range(0, len(asins), 100):
        r = k.call("product", {"asin": ",".join(asins[i:i + 100]), "stats": 30, "history": 1 if history else 0,
                               **({"days": since_days} if history else {})})
        res += r.get("products") or []
    return res


def row(p):
    s = shape(p)
    return {"asin": s["asin"], "title": (s["title"] or "")[:100], "brand": s["brand"], "label": s["units"]["label"],
            "unitsLow": s["units"]["low"] if s["units"]["source"] == "amazon_badge" else 0,
            "unitsHigh": s["units"]["high"] if s["units"]["source"] == "amazon_badge" else 0,
            "priceCents": (s["price"] or {}).get("cents"), "revenue": s["revenue"], "listedSince": s["listedSince"]}


def total(rows):
    r = [x for x in rows if x["revenue"]]
    return {"unitsLow": sum(x["unitsLow"] for x in r), "unitsHigh": sum(x["unitsHigh"] for x in r),
            "revenueLowCents": sum(x["revenue"]["lowCents"] for x in r),
            "revenueHighCents": sum(x["revenue"]["highCents"] for x in r)}


# ─── Args ────────────────────────────────────────────────────────────

FLAGS_WITH_VALUE = {"--max", "--months"}


def arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def positional():
    skip, res = False, []
    for a in sys.argv[2:]:
        if skip:
            skip = False
            continue
        if a.startswith("--"):
            skip = a in FLAGS_WITH_VALUE
            continue
        res.append(a)
    return " ".join(res).strip()


def int_arg(flag, default, lo, hi):
    try:
        v = arg(flag)
        return default if v is None else max(lo, min(int(v), hi))
    except ValueError:
        out({"error": "bad_" + flag.strip("-")}, 4)


def need_mode():
    md = mode()
    if md == "none":
        out(NO_KEYS, 2)
    return md


def retrieved():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─── Commands ────────────────────────────────────────────────────────

def cmd_product():
    raw, months = positional(), int_arg("--months", None, 1, 60)
    if not raw:
        out({"error": "invalid_asin", "reason": "empty"}, 4)
    if need_mode() == "whm":
        _, body = whm_get("/v1/tools/product-sales?" + urllib.parse.urlencode({"asin": raw}))
        if not has("KEEPA_API_KEY"):
            now = datetime.now(timezone.utc).strftime("%Y-%m")
            u, rv = body.get("units") or {}, body.get("revenue") or {}
            cur = {"month": now, "unitsLow": u.get("low", 0) if u.get("source") == "amazon_badge" else 0,
                   "unitsHigh": u.get("high", 0) if u.get("source") == "amazon_badge" else 0,
                   "revenueLowCents": rv.get("lowCents", 0), "revenueHighCents": rv.get("highCents", 0), "live": True}
            out({"mode": "whm", **body, "current": cur, "history": None,
                 "historyNote": {"error": "whm_route_not_live", "route": "GET /v1/tools/product-sales?asin=&history=1",
                                 "note": "WaitHowMuch serves the current month only; the monthly series is not a live "
                                         "route yet (not in the API-PROXY proposal either). Set KEEPA_API_KEY for the series."},
                 "method": METHOD})
        comparables = body.get("comparables")
    else:
        comparables = None
    asin = parse_asin(raw)
    k = Keepa()
    r = k.call("product", {"asin": asin, "stats": 30, "history": 1, "days": (date.today() - BADGE_FLOOR).days})
    p = (r.get("products") or [None])[0]
    if not p or (not p.get("title") and not p.get("categoryTree")):
        out({"mode": "keepa", "error": "asin_not_found", "asin": asin, **k.meta()}, 1)
    hist = series([p], months)
    out({"mode": "keepa", **shape(p), "current": hist[-1], "history": hist[:-1], "trend": trend(hist),
         "comparables": comparables, "method": METHOD, "retrievedAt": retrieved(), "source": "Keepa", **k.meta()})


def find_business(name):
    """A researched WaitHowMuch case study whose name or slug matches."""
    _, body = whm_get("/v1/businesses?limit=100")
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())  # noqa: E731
    q = norm(name)
    for b in body.get("businesses") or []:
        if q and q in (norm(b.get("name")), norm(b.get("slug"))):
            return b
    return None


def researched(b):
    _, m = whm_get(f"/v1/businesses/{urllib.parse.quote(b['slug'])}/metrics?type=revenue")
    rows = [{"month": x["periodStart"][:7], "revenueCents": round(float(x["value"]) * 100),
             "isEstimated": x.get("isEstimated"), "source": (x.get("meta") or {}).get("source")}
            for x in m.get("metrics") or [] if x.get("type") == "revenue"]
    full = rows[-12:]
    return {"mode": "whm", "researched": True, "business": {k: b.get(k) for k in (
        "slug", "name", "tagline", "latestPeriod", "latestMonthlyRevenue", "latestMonthlyProfit", "latestMarginPct", "confidence")},
        "currency": m.get("currency"), "history": rows,
        "trend": {"ttmMonths": len(full), "ttmRevenueCents": sum(r["revenueCents"] for r in full)},
        "caseStudy": f"https://waithowmuch.com/business/{b['slug']}/?utm_source=whm-skills&utm_medium=skill"
                     f"&utm_campaign=whm-skills&utm_content={SKILL}",
        "method": "WaitHowMuch's researched case study (hand-checked catalogue, every holder of the brand). "
                  "Point figures, not ranges; see the case study for how each was built."}


def cmd_brand():
    name, n, months = positional(), int_arg("--max", 50, 1, 300), int_arg("--months", None, 1, 60)
    if not name:
        out({"error": "empty", "message": "give a brand name as it appears on Amazon"}, 4)
    if need_mode() == "whm":
        b = find_business(name)
        if b:
            out(researched(b))
        status, body = whm_get("/v1/tools/brand-revenue?" + urllib.parse.urlencode({"brand": name, "max": min(n, 50)}),
                               allow=(404,))
        if status == 200:
            out({"mode": "whm", **body})
        if not has("KEEPA_API_KEY"):
            if route_missing(status, body):
                out(not_live("GET /v1/tools/brand-revenue?brand=&max=",
                             f"'{name}' is not a researched WaitHowMuch case study, and the brand-revenue route "
                             "(API-PROXY.md, Phase 2) is not live yet."), 2)
            out({"mode": "whm", "status": status, **body}, 1)
    k = Keepa()
    k.ensure(11 + n)
    q = k.call("query", {}, {"brand": [name], "monthlySold_gte": 1, "sort": [["monthlySold", "desc"]],
                             "perPage": max(50, n), "page": 0})
    asins, found = q.get("asinList") or [], q.get("totalResults")
    prods = products(k, asins[:n])
    out(catalogue_result({"brand": name}, prods, found, n, months, k))


def catalogue_result(query, prods, badged, n, months, k, extra=None):
    rows = sorted((row(p) for p in prods), key=lambda x: -((x["revenue"] or {}).get("lowCents") or 0))
    brands = {}
    for p in prods:
        b = p.get("brand") or "?"
        brands[b] = brands.get(b, 0) + 1
    hist = series(prods, months)
    return {"mode": "keepa", "query": query, **(extra or {}),
            "badgedListings": badged, "pricedListings": len([r for r in rows if r["revenue"]]),
            "capped": bool(badged and badged > n), "cap": n, "brandStrings": brands,
            "current": hist[-1], "history": hist[:-1], "trend": trend(hist), "products": rows[:25],
            "method": METHOD + " Brand/store totals cover the listings priced here (top sellers first); capped=true means more exist.",
            "retrievedAt": retrieved(), "source": "Keepa", **k.meta()}


def parse_seller(raw):
    s = raw.strip()
    if SELLER_RE.match(s.upper()) and not ASIN_RE.match(s.upper()):
        return s.upper(), None
    if re.match(r"^https?://|amazon\.", s, re.I):
        u = urllib.parse.urlparse(s if re.match(r"^https?://", s, re.I) else "https://" + s)
        qs = urllib.parse.parse_qs(u.query)
        sid = (qs.get("seller") or qs.get("me") or [""])[0].upper()
        if SELLER_RE.match(sid):
            return sid, None
        if "/stores/" in u.path:
            out({"error": "invalid_seller", "reason": "brand_store_url",
                 "message": "A brand-store URL carries no seller ID. Give one of the brand's ASINs (or product URLs) instead."}, 4)
    asin = parse_asin(s, fatal=False)
    if asin:
        return None, asin
    out({"error": "invalid_seller", "reason": "unrecognised",
         "message": "Give a seller ID (A...), an amazon.com seller/storefront URL with ?seller=, or one of its ASINs."}, 4)


def seller_of(k, asin):
    """Buy-box seller of one product. Needs buybox=1 (+2 tokens), else Keepa reports Amazon for every row."""
    r = k.call("product", {"asin": asin, "stats": 30, "history": 1, "buybox": 1, "days": 90})
    p = (r.get("products") or [{}])[0]
    votes = {}
    h = p.get("buyBoxSellerIdHistory") or []
    for i in range(1, len(h), 2):
        if h[i] not in NOT_A_SELLER:
            votes[h[i]] = votes.get(h[i], 0) + 1
    cur = (p.get("stats") or {}).get("buyBoxSellerId")
    if cur and cur not in NOT_A_SELLER:
        votes[cur] = votes.get(cur, 0) + 1
    return max(votes, key=votes.get) if votes else None


def cmd_store():
    full = "--full" in sys.argv
    raw, n, months = positional(), int_arg("--max", 500 if full else 50, 1, 1000 if full else 300), int_arg("--months", None, 1, 60)
    if not raw:
        out({"error": "empty", "message": "give a seller ID, seller URL, or one of the store's ASINs"}, 4)
    sid, asin = parse_seller(raw)
    if need_mode() == "whm":
        status, body = whm_get("/v1/tools/store-revenue?" + urllib.parse.urlencode({"seller": raw}), allow=(401,))
        if status == 200:
            out({"mode": "whm", **body, "history": None,
                 "historyNote": {"error": "whm_route_not_live", "route": "GET /v1/tools/store-revenue?seller=&history=1",
                                 "note": "store-revenue is a current-month snapshot; no WHM route serves a store's monthly "
                                         "series yet (not in the API-PROXY proposal). Set KEEPA_API_KEY for the series."}})
        if not has("KEEPA_API_KEY"):
            out({"mode": "whm", "status": status, **body,
                 "note": "store-revenue gives one free lookup per IP, then needs a waithowmuch.com sign-in; "
                         "API keys do not lift that gate yet (API-PROXY.md Phase 1)."}, 1)
    k = Keepa()
    k.ensure((3 if asin else 0) + 10 + (0 if full else 11 + n))
    if asin:
        sid = seller_of(k, asin)
        if not sid:
            out({"mode": "keepa", "error": "seller_not_found", "asin": asin,
                 "message": "No third-party buy-box seller (Amazon holds it, or the offer is suppressed).", **k.meta()}, 1)
    s = (k.call("seller", {"seller": sid, "storefront": 1}).get("sellers") or {}).get(sid) or {}
    if not s.get("sellerName") and not s.get("asinList"):
        out({"mode": "keepa", "error": "seller_not_found", "sellerId": sid, **k.meta()}, 1)
    catalogue = s.get("asinList") or []
    addr = s.get("address") or []
    seller = {"id": sid, "name": s.get("sellerName"), "businessName": s.get("businessName"),
              "country": addr[-1] if addr and re.fullmatch(r"[A-Z]{2}", addr[-1] or "") else None,
              "rating": s.get("currentRating"), "ratingCount": s.get("currentRatingCount"),
              "firstSeen": kdate(s["trackedSince"]).date().isoformat() if s.get("trackedSince") else None,
              "url": f"https://www.amazon.com/sp?seller={sid}", "storefrontAsins": len(catalogue)}
    if full:
        # research-amazon-store's way: the WHOLE storefront with history, so listings badged in past
        # months but not now still count in those months.
        todo = catalogue[:n]
        k.ensure(len(todo))
        prods = products(k, todo)
        badged = sum(1 for p in prods if (p.get("monthlySold") or 0) > 0)
        res = catalogue_result({"seller": sid}, prods, badged, n, months, k,
                               {"seller": seller, "resolvedFrom": {"asin": asin} if asin else None, "full": True})
        res["capped"] = len(catalogue) > n
    else:
        q = k.call("query", {}, {"sellerIds": [sid], "monthlySold_gte": 1, "sort": [["monthlySold", "desc"]],
                                 "perPage": max(50, n), "page": 0})
        page = q.get("asinList") or []
        cat = set(catalogue)
        keep = [a for a in page if a in cat] if cat else page  # Finder matches any offer; keep the storefront's own
        prods = products(k, keep[:n])
        tot = q.get("totalResults") or len(page)
        badged = len(keep) if tot <= len(page) or not page else round(tot * len(keep) / len(page))
        res = catalogue_result({"seller": sid}, prods, badged, n, months, k,
                               {"seller": seller, "resolvedFrom": {"asin": asin} if asin else None, "full": False})
        res["note"] = ("Priced today's badged listings only; a listing badged in an earlier month but not now is missing "
                       "from that month. --full prices the whole storefront (1 token per ASIN).")
    out(res)


def cmd_api():
    if need_mode() != "whm":
        out({"error": "wrong_mode", "mode": mode(), "message": "api runs in WHM mode (WHM_API_KEY)"}, 2)
    out({"mode": "whm", **whm_get(positional())[1]})


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    usage_ping(cmd)
    if cmd == "mode":
        md = mode()
        out({"mode": md, "keys": {"WHM_API_KEY": has("WHM_API_KEY"), "KEEPA_API_KEY": has("KEEPA_API_KEY")},
             **({} if md != "none" else NO_KEYS), "skill": SKILL, "version": VERSION})
    {"product": cmd_product, "brand": cmd_brand, "store": cmd_store, "api": cmd_api}.get(
        cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
