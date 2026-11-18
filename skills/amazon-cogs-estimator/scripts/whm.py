#!/usr/bin/env python3
"""WaitHowMuch skills data helper: one WHM API key, or your own provider keys.

Copied into every skill's scripts/ folder. 0.4.0 adds the landed-cost commands
(freight, duty, quotes, landed) and the demand-test ping (invoke).
Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key
(Keepa takes its key in the query string, so no URL is ever printed).

Mode, decided per run from the environment:
  1. WHM_API_KEY set   -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
  2. KEEPA_API_KEY set -> Keepa API directly (your tokens)
  3. neither           -> {"error": "no_keys", ...}, exit 2
     (freight, duty, quotes and landed need no key unless you pass --asin)

Commands:
  mode                         which mode this run would use (no provider call)
  product <ASIN|amazon.com URL>  monthly units/revenue range, price, fees    (Keepa: 1 token)
  api </v1/path?query>         GET a WaitHowMuch API route (WHM mode only)
  brand <name> [--seller ID] [--max N]   catalogue revenue of any brand   (needs KEEPA_API_KEY: ~11 + N tokens)
  niche "<keywords>" [--max N]           top-selling brands for a keyword (needs KEEPA_API_KEY: ~11 + N tokens)

  quotes "<range>" "<range>" ...  make cost from supplier price ranges, one argument per supplier
                                  (each supplier's LOWEST price, averaged)           (no provider call)
  freight --cbm N --kg N [--cartons N] [--origin CITY,COUNTRY] [--dest CITY,ST] [--mode LCL|air|express]
                               door-to-door estimate for one shipment, Freightos public calculator (free,
                               no key); stored dated rate table if Freightos is unreachable
  duty "<product words>" | --hts NNNN.NN.NN
                               US base (MFN) duty rate from the USITC HTS search (free, no key)
  landed --unit-cost X --qty N [box: --asin A | --unit-cm LxWxH --unit-kg W | --carton-cm LxWxH
         --carton-kg W --per-carton N] [--duty-pct P | --hts CODE] [--origin-country CN]
         [--extra-duty-pct P] [--prep X] [--placement X] [--freight-per-unit X] [--origin ..] [--dest ..]
                               landed cost per unit: make + freight + duty + prep/inbound
  invoke                       count one use of this skill (a free WaitHowMuch call, no key, no input sent)

Exit codes: 0 ok, 1 upstream/API error, 2 no keys / wrong mode, 3 not enough Keepa tokens, 4 bad input.
"""
import json
import math
import os
import re
import sys
import gzip
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VERSION = "0.4.1"
WHM_API = os.environ.get("WHM_API_BASE", "").strip().rstrip("/") or "https://api.waithowmuch.com"
KEEPA = "https://api.keepa.com"
US = 1
KEEPA_EPOCH_MIN = 21_564_000  # Keepa time = minutes since 2011-01-01 UTC
BADGE_THRESHOLD = 50

# Lower-cased: the backend only records skill tags matching ^[a-z0-9][a-z0-9-]*$.
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

COMMANDS = {"api", "brand", "duty", "freight", "invoke", "landed", "mode", "niche", "product", "quotes"}
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


def mode():
    if os.environ.get("WHM_API_KEY", "").strip():
        return "whm"
    if os.environ.get("KEEPA_API_KEY", "").strip():
        return "keepa"
    return "none"


NO_KEYS = {
    "error": "no_keys",
    "message": "Set ONE of: WHM_API_KEY (a WaitHowMuch API key, covers everything) "
               "or KEEPA_API_KEY (your own paid Keepa API plan, https://keepa.com/#!api; "
               "you pay Keepa tokens per lookup). In Claude Code: /plugin > waithowmuch > "
               "Configure options. Elsewhere: an environment variable. "
               "https://github.com/ggballas/waithowmuch-skills#data-providers",
}


# ─── HTTP ────────────────────────────────────────────────────────────

def _fetch(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers={"Accept-Encoding": "gzip", "User-Agent": f"whm-skills/{VERSION}",
                                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
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


def whm_get(path):
    if not path.startswith("/v1/"):
        out({"error": "bad_path", "message": "path must start with /v1/"}, 4)
    sep = "&" if "?" in path else "?"
    status, body = _fetch(f"{WHM_API}{path}{sep}{urllib.parse.urlencode(TAG)}",
                          headers={"X-WHM-Key": os.environ["WHM_API_KEY"].strip()})
    if status != 200:
        out({"mode": "whm", "status": status, **(body if isinstance(body, dict) else {})}, 1)
    return body


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
                 "refillInSec": round((res.get("refillIn") or 60000) / 1000)}, 3)
        if status in (401, 402, 403):
            out({"mode": "keepa", "error": "keepa_key_rejected", "status": status,
                 "message": "Keepa refused the key (invalid, or no active API plan)."}, 1)
        if status != 200:
            out({"mode": "keepa", "error": "keepa_error", "status": status}, 1)
        return res

    def ensure(self, need):
        """Refuse up front rather than drain or stall: /token is free."""
        t = self.call("token", {})
        left, rate = t.get("tokensLeft", 0), t.get("refillRate") or 0
        if left < need:
            wait = math.ceil((need - left) / rate) * 60 if rate else None
            out({"mode": "keepa", "error": "keepa_tokens_low", "needed": need, "tokensLeft": left,
                 "refillPerMin": rate, "waitSec": wait}, 3)

    def meta(self):
        return {"tokensConsumed": self.used, "tokensLeft": self.left}


# ─── The method (same as WaitHowMuch's /v1/tools/product-sales) ──────

ASIN_RE = re.compile(r"^(?:B0[A-Z0-9]{8}|\d{9}[\dX])$")
ASIN_IN_PATH = re.compile(r"/(?:dp|gp/product|gp/aw/d|product|d)/([A-Z0-9]{10})(?:[/?]|$)", re.I)


def parse_asin(raw):
    s = raw.strip()
    if ASIN_RE.match(s.upper()):
        return s.upper()
    u = urllib.parse.urlparse(s if re.match(r"^https?://", s, re.I) else "https://" + s)
    host = (u.hostname or "").lower()
    if host in ("a.co", "amzn.to", "amzn.com", "amzn.eu"):
        out({"error": "invalid_asin", "reason": "short_link", "message": "Open the short link and paste the full amazon.com URL."}, 4)
    if not (host == "amazon.com" or host.endswith(".amazon.com")):
        reason = "us_only" if re.search(r"(^|\.)amazon\.[a-z.]+$", host) else "not_amazon"
        out({"error": "invalid_asin", "reason": reason}, 4)
    m = ASIN_IN_PATH.search(u.path)
    asin = (m.group(1) if m else (urllib.parse.parse_qs(u.query).get("asin") or [""])[0]).upper()
    if not ASIN_RE.match(asin):
        out({"error": "invalid_asin", "reason": "no_asin"}, 4)
    return asin


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


def month_series(products, months=12):
    """Each past month end's badge x today's price (the research method; price history is not re-read)."""
    now = datetime.now(timezone.utc)
    ends = []
    y, m = now.year, now.month
    for _ in range(months):
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        nxt = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
        ends.append((f"{y}-{m:02d}", (nxt.timestamp() / 60) - KEEPA_EPOCH_MIN))
    rows = []
    for label, end_min in reversed(ends):
        lo = hi = ulo = uhi = 0
        for p in products:
            price = pick_price(p.get("stats"))
            h = p.get("monthlySoldHistory") or []
            val = None
            for i in range(0, len(h) - 1, 2):
                if h[i] <= end_min:
                    val = h[i + 1]
                else:
                    break
            rng = badge_range(val)
            if rng and price:
                ulo, uhi = ulo + rng[0], uhi + rng[1]
                lo, hi = lo + rng[0] * price["cents"], hi + rng[1] * price["cents"]
        rows.append({"month": label, "unitsLow": ulo, "unitsHigh": uhi, "revenueLowCents": lo, "revenueHighCents": hi})
    return rows


def finder(k, selection):
    q = k.call("query", {}, selection)
    return q.get("asinList") or [], q.get("totalResults")


def products(k, asins, history):
    res = []
    for i in range(0, len(asins), 100):
        r = k.call("product", {"asin": ",".join(asins[i:i + 100]), "stats": 30, "history": 1 if history else 0,
                               **({"days": 400} if history else {})})
        res += r.get("products") or []
    return res


def row(p):
    s = shape(p)
    return {"asin": s["asin"], "title": (s["title"] or "")[:100], "brand": s["brand"], "label": s["units"]["label"],
            "unitsLow": s["units"]["low"], "unitsHigh": s["units"]["high"],
            "priceCents": (s["price"] or {}).get("cents"), "revenue": s["revenue"]}


def total(rows):
    r = [x for x in rows if x["revenue"]]
    return {"unitsLow": sum(x["unitsLow"] for x in r), "unitsHigh": sum(x["unitsHigh"] for x in r),
            "revenueLowCents": sum(x["revenue"]["lowCents"] for x in r),
            "revenueHighCents": sum(x["revenue"]["highCents"] for x in r)}


# ─── Commands ────────────────────────────────────────────────────────

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
            skip = True
            continue
        res.append(a)
    return " ".join(res).strip()


def need_keepa():
    """brand / niche have no WHM route: they need the user's own Keepa key, whatever the mode."""
    if not os.environ.get("KEEPA_API_KEY", "").strip():
        out({"error": "needs_keepa_key", "mode": mode(),
             "message": "This lookup runs on your own Keepa key only (KEEPA_API_KEY); "
                        "WaitHowMuch has no API route for it."}, 2)
    return "keepa"


def need_mode(allowed):
    md = mode()
    if md == "none":
        out(NO_KEYS, 2)
    if md not in allowed:
        out({"error": "wrong_mode", "mode": md, "message": f"this command runs in {' or '.join(allowed)} mode"}, 2)
    return md


def cmd_product():
    raw = positional()
    if not raw:
        out({"error": "invalid_asin", "reason": "empty"}, 4)
    md = need_mode(("whm", "keepa"))
    if md == "whm":
        out({"mode": "whm", **whm_get("/v1/tools/product-sales?" + urllib.parse.urlencode({"asin": raw}))})
    asin = parse_asin(raw)
    k = Keepa()
    r = k.call("product", {"asin": asin, "stats": 30, "history": 1, "days": 400})
    p = (r.get("products") or [None])[0]
    if not p or (not p.get("title") and not p.get("categoryTree")):
        out({"mode": "keepa", "error": "asin_not_found", "asin": asin, **k.meta()}, 1)
    out({"mode": "keepa", **shape(p), "comparables": None,
         "comparablesNote": "WaitHowMuch case-study matches need WHM mode",
         "retrievedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "Keepa", **k.meta()})


def cmd_api():
    need_mode(("whm",))
    out({"mode": "whm", **whm_get(positional())})


def cap():
    try:
        return max(1, min(int(arg("--max", "50")), 300))
    except ValueError:
        out({"error": "bad_max"}, 4)


def cmd_brand():
    name, seller, n = positional(), arg("--seller"), cap()
    if not name and not seller:
        out({"error": "empty", "message": "give a brand name or --seller <seller ID>"}, 4)
    md = need_keepa()
    k = Keepa()
    k.ensure(11 + n)
    sel = {"monthlySold_gte": 1, "sort": [["monthlySold", "desc"]], "perPage": max(50, n), "page": 0}
    sel.update({"sellerIds": [seller.upper()]} if seller else {"brand": [name]})
    asins, found = finder(k, sel)
    prods = products(k, asins[:n], history=True)
    rows = sorted((row(p) for p in prods), key=lambda x: -((x["revenue"] or {}).get("lowCents") or 0))
    brands = {}
    for p in prods:
        b = p.get("brand") or "?"
        brands[b] = brands.get(b, 0) + 1
    out({"mode": md, "query": {"seller": seller} if seller else {"brand": name},
         "badgedListings": found, "pricedListings": len([r for r in rows if r["revenue"]]),
         "capped": bool(found and found > n), "cap": n, "brandStrings": brands,
         "monthly": total(rows), "history": month_series(prods), "products": rows[:25],
         "method": "sum over badged listings of Amazon's 'bought in past month' bucket x current buy box; "
                   "history = each month end's badge x today's price; unbadged listings (<~50/mo each) excluded",
         "source": "Keepa", **k.meta()})


def cmd_niche():
    kw, n = positional(), cap()
    if len(kw) < 3:
        out({"error": "empty", "message": "give a product keyword, e.g. \"party card game\""}, 4)
    md = need_keepa()
    k = Keepa()
    k.ensure(11 + n)
    asins, found = finder(k, {"title": kw, "monthlySold_gte": 50, "sort": [["monthlySold", "desc"]],
                              "perPage": max(50, n), "page": 0})
    rows = [row(p) for p in products(k, asins[:n], history=False)]
    by = {}
    for r in rows:
        b = by.setdefault(r["brand"] or "?", {"brand": r["brand"] or "?", "listings": 0, "unitsLow": 0, "unitsHigh": 0,
                                              "revenueLowCents": 0, "revenueHighCents": 0, "topProduct": r["title"], "topAsin": r["asin"]})
        if r["revenue"]:
            b["listings"] += 1
            b["unitsLow"] += r["unitsLow"]
            b["unitsHigh"] += r["unitsHigh"]
            b["revenueLowCents"] += r["revenue"]["lowCents"]
            b["revenueHighCents"] += r["revenue"]["highCents"]
    out({"mode": md, "keywords": kw, "matchingBadgedListings": found, "scanned": len(rows),
         "brands": sorted(by.values(), key=lambda b: -b["revenueLowCents"]),
         "method": "Keepa Product Finder title match, listings with a 50+ badge, top N by badge; revenue = badge bucket x buy box. "
                   "Only the scanned listings count toward each brand, so a brand's figure is a floor, not its store total.",
         "source": "Keepa", **k.meta()})


# ─── Landed cost (0.4.0) ─────────────────────────────────────────────
#
# WaitHowMuch's case-study method, for one seller's own order:
#   landed per unit = make cost + freight + duty (+ MPF) + prep + inbound placement
# Freight is door-to-door from Freightos' public calculator (free, no key, beta,
# rate-limited). Its licence requires a visible credit with a link to
# www.freightos.com, so every freight figure carries ATTRIBUTION.

import time  # noqa: E402

FREIGHTOS = "https://ship.freightos.com/api/shippingCalculator"
ATTRIBUTION = "Freight estimate from the Freightos public shipping calculator (https://www.freightos.com), beta, as-is."
HTS_SEARCH = "https://hts.usitc.gov/reststop/search"
LANDED_ROUTE = "/v1/tools/landed-cost"   # proposed WaitHowMuch route; not live yet
WAITLIST = "https://api.waithowmuch.com/go/waitlist-supplier-contact?from=skill"

# Fallback when Freightos is unreachable: dated LCL readings, low end of the band,
# door-to-door incl. customs clearance and delivery, priced on a 2 cbm shipment.
# Linear in cbm, so it UNDERSTATES a small shipment (fixed charges dominate).
STORED_RATES = {
    "CN-USWC": {"route": "Shanghai -> Los Angeles", "usdPerCbm": 373.75, "high": 4261.33, "readAt": "2026-11-17"},
    "CN-USEC": {"route": "Shanghai -> New York", "usdPerCbm": 546.01, "high": 6794.10, "readAt": "2026-09-28"},
}
STALE_AFTER_DAYS = 180
EAST = {"NY", "NJ", "PA", "MD", "DE", "VA", "NC", "SC", "GA", "FL", "MA", "CT", "RI", "NH", "ME", "VT",
        "OH", "IN", "KY", "TN", "AL", "MI", "WV", "DC"}

# Merchandise Processing Fee on a formal entry (FY2026): 0.3464% of value, min/max per entry.
MPF_PCT, MPF_MIN, MPF_MAX = 0.3464, 33.58, 651.50


def num(flag, default=None, positive=False):
    v = arg(flag)
    if v is None:
        return default
    try:
        f = float(str(v).replace("$", "").replace(",", ""))
    except ValueError:
        out({"error": "bad_number", "flag": flag, "value": v}, 4)
    if positive and f <= 0:
        out({"error": "bad_number", "flag": flag, "message": "must be above 0"}, 4)
    return f


def dims(flag):
    v = arg(flag)
    if v is None:
        return None
    parts = re.split(r"[x×*, ]+", v.strip().lower())
    try:
        L, W, H = (float(x) for x in parts if x)
    except ValueError:
        out({"error": "bad_dims", "flag": flag, "message": "give L x W x H in cm, e.g. 40x30x25"}, 4)
    if min(L, W, H) <= 0:
        out({"error": "bad_dims", "flag": flag}, 4)
    return L, W, H


def r2(x):
    return None if x is None else round(x + 1e-9, 2)


def _get_text(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": f"whm-skills/{VERSION}", "Accept": "application/json",
                                               **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, type(e).__name__


def lane_for(dest):
    st = (dest or "").replace(" ", "").split(",")[-1].upper()
    return "CN-USEC" if st in EAST else "CN-USWC"


def stored_freight(cbm, dest):
    lane = lane_for(dest)
    r = STORED_RATES[lane]
    age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(r["readAt"]).date()).days
    return {"source": "stored_rate", "lane": lane, "route": r["route"], "usdPerCbm": r["usdPerCbm"],
            "readAt": r["readAt"], "ageDays": age, "stale": age > STALE_AFTER_DAYS,
            "shipmentUsd": {"low": r2(cbm * r["usdPerCbm"]), "high": r2(cbm * r["high"])},
            "note": "Stored China->US LCL reading (low end of Freightos' band, door to door), times this "
                    "shipment's cbm. Linear, so it understates a shipment under ~2 cbm, where fixed "
                    "customs and delivery charges dominate.",
            "attribution": ATTRIBUTION}


def freightos(cbm, kg, cartons=None, carton_cm=None, origin="Shanghai,China", dest="LosAngeles,CA", mode_="LCL"):
    """One shipment, door to door. Returns a dict, or None when Freightos can't be read."""
    if carton_cm and cartons:
        L, W, H = carton_cm
        qty, per_kg = int(cartons), max(1.0, kg / cartons)
    else:
        qty = max(1, math.ceil(cbm))
        side = (cbm / qty) ** (1 / 3) * 100
        L = W = H = max(10.0, side)
        per_kg = max(1.0, kg / qty)
    params = urllib.parse.urlencode({"loadtype": "boxes", "weight": round(per_kg, 1), "width": round(W, 1),
                                     "length": round(L, 1), "height": round(H, 1), "quantity": qty,
                                     "origin": origin, "destination": dest})
    last = None
    for attempt in range(3):
        if attempt:
            time.sleep(8 * attempt)  # Cloudflare answers a burst with "error code: 1015"
        status, text = _get_text(f"{FREIGHTOS}?{params}")
        if status != 200 or re.search(r"error code:\s*\d+", text):
            last = f"HTTP {status}: {text.strip()[:40]}"
            continue
        try:
            modes = (json.loads(text).get("response") or {}).get("estimatedFreightRates", {}).get("mode") or []
        except ValueError:
            last = "unparseable response"
            continue
        want = mode_.lower()
        pick = next((m for m in modes if (m.get("mode") or "").lower() == want), None)
        if not pick and want == "lcl":
            pick = next((m for m in modes if re.search(r"ocean|sea|lcl|fcl", m.get("mode") or "", re.I)), None)
        if not pick:
            return {"source": "freightos", "error": "mode_not_offered", "wanted": mode_,
                    "offered": [m.get("mode") for m in modes], "attribution": ATTRIBUTION}
        amt = lambda side: (((pick.get("price") or {}).get(side) or {}).get("moneyAmount") or {}).get("amount")  # noqa: E731
        lo, hi = amt("min"), amt("max")
        if not isinstance(lo, (int, float)):
            last = "no price in response"
            continue
        t = pick.get("transitTimes") or {}
        return {"source": "freightos", "mode": pick.get("mode"), "origin": origin, "destination": dest,
                "shipment": {"cbm": round(cbm, 3), "kg": round(kg, 1), "boxes": qty},
                "shipmentUsd": {"low": lo, "high": hi}, "transitDays": {"min": t.get("min"), "max": t.get("max")},
                "rateChoice": "Use the LOW end: the band spans every service level; its top prices expedited "
                              "options a first order would not buy. Keep the spread visible.",
                "scope": "door to door, incl. origin handling, customs clearance and delivery; excludes duty",
                "retrievedAt": datetime.now(timezone.utc).date().isoformat(), "attribution": ATTRIBUTION}
    return {"source": "freightos", "error": "unreachable", "detail": last}


def cmd_freight():
    cbm, kg = num("--cbm", positive=True), num("--kg", positive=True)
    if cbm is None or kg is None:
        out({"error": "usage", "message": "freight --cbm <total cbm> --kg <total kg> [--cartons N --carton-cm LxWxH]"}, 4)
    origin, dest = arg("--origin", "Shanghai,China"), arg("--dest", "LosAngeles,CA")
    res = freightos(cbm, kg, num("--cartons"), dims("--carton-cm"), origin, dest, arg("--mode", "LCL"))
    if res.get("error") == "unreachable":
        out({**stored_freight(cbm, dest), "freightosError": res.get("detail")})
    out(res, 1 if res.get("error") else 0)


def rate_pct(general):
    """'Free' -> 0, '6.5%' -> 6.5, '2.4¢/kg + 5%' -> 5 (ad valorem part only, flagged)."""
    g = (general or "").strip()
    if not g:
        return None, False
    if g.lower().startswith("free"):
        return 0.0, False
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", g)
    specific = bool(re.search(r"¢|\$|/kg|/doz|/pr|/no|/m2|/l\b", g))
    return (float(m.group(1)) if m else None), specific


def hts_search(q):
    status, text = _get_text(f"{HTS_SEARCH}?{urllib.parse.urlencode({'keyword': q})}")
    if status != 200:
        out({"error": "hts_unreachable", "status": status}, 1)
    try:
        rows = json.loads(text)
    except ValueError:
        out({"error": "hts_unreadable"}, 1)
    res = []
    for r in rows if isinstance(rows, list) else []:
        if not r.get("htsno") or str(r.get("htsno")).startswith(("98", "99")):
            continue  # chapter 98/99: special provisions and the add-on duties, not a product line
        pct, specific = rate_pct(r.get("general"))
        notes = " ".join(str(f.get("value", "")) for f in (r.get("footnotes") or []) if isinstance(f, dict))
        res.append({"htsno": r["htsno"], "description": re.sub(r"\s+", " ", r.get("description") or "")[:200],
                    "general": r.get("general") or None, "generalPct": pct, "specificDuty": specific,
                    "footnoteAddOns": sorted(set(re.findall(r"99\d\d\.\d\d\.\d\d", notes)))})
    return res


def cmd_duty():
    code = arg("--hts")
    q = code or positional()
    if not q or len(q) < 3:
        out({"error": "usage", "message": 'duty "<product words>" or duty --hts 9503.00.00'}, 4)
    rows = hts_search(q)
    if code:
        c = code.replace(".", "")
        rows = [r for r in rows if r["htsno"].replace(".", "").startswith(c[:8])] or rows
    out({"query": q, "matches": rows[:10], "source": "USITC Harmonized Tariff Schedule search (hts.usitc.gov)",
         "note": "generalPct is the base (MFN) rate only. Add-on duties by origin (China: Section 301 and "
                 "others in chapter 99) are NOT included and change often: check them before relying on the total. "
                 "Rows with no rate are headings: use a more specific line."})


def lowest_avg(ranges):
    per = []
    for i, raw in enumerate(ranges):
        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(raw).replace(",", ""))]
        if not nums:
            out({"error": "bad_quote", "supplier": i + 1, "value": raw}, 4)
        per.append({"supplier": i + 1, "quoted": raw, "lowest": min(nums)})
    avg = sum(p["lowest"] for p in per) / len(per)
    return per, avg


def cmd_quotes():
    ranges = [a for a in sys.argv[2:] if not a.startswith("--")]
    if not ranges:
        out({"error": "usage", "message": 'quotes "$1.20-2.50" "$0.95-1.80" ... (one argument per supplier)'}, 4)
    per, avg = lowest_avg(ranges)
    out({"perSupplier": per, "makeCostPerUnit": r2(avg), "suppliers": len(per),
         "method": "Each supplier's LOWEST listed price (its volume price), averaged across suppliers. "
                   "Never the middle or top of a range. With real tiered quotes, use the tier nearest your order "
                   "quantity instead.",
         "warning": None if len(per) >= 2 else "One supplier only: the research minimum is two quotes "
                                               "(one for a custom-tooled product)."})


def package_for_asin(asin_raw):
    """The shipping box of a similar listing: WHM product-sales (WHM mode) or Keepa (1 token)."""
    md = need_mode(("whm", "keepa"))
    if md == "whm":
        body = whm_get("/v1/tools/product-sales?" + urllib.parse.urlencode({"asin": asin_raw}))
        pkg = body.get("package")
    else:
        asin = parse_asin(asin_raw)
        k = Keepa()
        r = k.call("product", {"asin": asin, "stats": 0})
        p = (r.get("products") or [None])[0] or {}
        pkg = shape(p).get("package") if p.get("asin") else None
    return md, pkg


def cmd_landed():
    unit = num("--unit-cost", positive=True)
    if unit is None:
        out({"error": "usage", "message": "landed --unit-cost <factory price per unit> --qty <order units> ..."}, 4)
    qty_given = arg("--qty") is not None
    qty = int(num("--qty", 500, positive=True))
    origin_country = (arg("--origin-country", "CN") or "CN").upper()
    origin = arg("--origin", "Shanghai,China")
    dest = arg("--dest", "LosAngeles,CA")
    lines, notes, extra = [], [], {}

    # 0. WHM mode: the proposed route first (not live yet: said, then computed directly).
    if mode() == "whm":
        st, _ = _fetch(f"{WHM_API}{LANDED_ROUTE}?{urllib.parse.urlencode(TAG)}",
                       headers={"X-WHM-Key": os.environ["WHM_API_KEY"].strip()})
        if st == 200:
            notes.append("WaitHowMuch landed-cost route answered, but this helper still computes locally.")
        else:
            extra["whm"] = {"error": "whm_route_not_live", "route": LANDED_ROUTE, "status": st,
                            "message": f"WaitHowMuch has no {LANDED_ROUTE} route yet; computed directly from "
                                       "Freightos and the USITC tariff schedule instead (both free, no key)."}

    # 1. Make cost.
    lines.append({"line": "make (factory price)", "perUnit": r2(unit), "tier": arg("--unit-basis", "given"),
                  "note": "per saleable unit, EXW/FOB at the supplier"})

    # 2. The shipment: cartons > unit box > a similar ASIN's box.
    carton_cm, unit_cm = dims("--carton-cm"), dims("--unit-cm")
    cbm = kg = cartons = None
    box_src = None
    if carton_cm:
        per_carton = num("--per-carton", positive=True)
        ckg = num("--carton-kg", positive=True)
        if not per_carton or not ckg:
            out({"error": "usage", "message": "--carton-cm needs --per-carton N and --carton-kg W"}, 4)
        cartons = math.ceil(qty / per_carton)
        cbm = cartons * carton_cm[0] * carton_cm[1] * carton_cm[2] / 1e6
        kg = cartons * ckg
        box_src = f"supplier carton {carton_cm[0]:g}x{carton_cm[1]:g}x{carton_cm[2]:g} cm, {per_carton:g}/carton, {ckg:g} kg"
    elif unit_cm:
        ukg = num("--unit-kg", positive=True)
        if not ukg:
            out({"error": "usage", "message": "--unit-cm needs --unit-kg"}, 4)
        cbm = qty * unit_cm[0] * unit_cm[1] * unit_cm[2] / 1e6
        kg = qty * ukg
        box_src = f"unit box {unit_cm[0]:g}x{unit_cm[1]:g}x{unit_cm[2]:g} cm, {ukg:g} kg (no carton overhead)"
    elif arg("--asin") and arg("--freight-per-unit") is None:
        md, pkg = package_for_asin(arg("--asin"))
        if pkg:
            cbm = qty * pkg["lengthMm"] * pkg["widthMm"] * pkg["heightMm"] / 1e9
            kg = qty * pkg["weightG"] / 1000
            box_src = (f"package of similar listing {arg('--asin')} ({md}): {pkg['lengthMm']}x{pkg['widthMm']}x"
                       f"{pkg['heightMm']} mm, {pkg['weightG']} g (no carton overhead)")
        else:
            notes.append(f"{arg('--asin')} has no package dimensions; freight fell back to an assumption.")

    # 3. Freight.
    fpu = num("--freight-per-unit")
    if fpu is not None:
        lines.append({"line": "freight to Amazon", "perUnit": r2(fpu), "tier": "given", "note": "your figure"})
    elif cbm:
        fr = freightos(cbm, kg, cartons, carton_cm, origin, dest, arg("--mode", "LCL"))
        if fr.get("error") == "unreachable":
            fr = {**stored_freight(cbm, dest), "freightosError": fr.get("detail")}
        if fr.get("error"):
            out({"error": "freight_failed", **fr}, 1)
        lo, hi = fr["shipmentUsd"]["low"], fr["shipmentUsd"]["high"]
        lines.append({"line": "freight to Amazon (door to door)", "perUnit": r2(lo / qty),
                      "rangePerUnit": [r2(lo / qty), r2(hi / qty)],
                      "tier": "derived" if fr["source"] == "freightos" else "derived (stored rate)",
                      "note": f"${lo:,.0f} for {cbm:.2f} cbm / {kg:.0f} kg / {qty} units, {fr.get('mode') or 'LCL'}, "
                              f"{origin} -> {dest}; {box_src}"})
        extra["freight"] = fr
    else:
        lines.append({"line": "freight to Amazon", "perUnit": r2(unit * 0.10), "tier": "assumed",
                      "note": "10% of unit cost: no box size given. Ask the supplier for carton size, weight "
                              "and units per carton, or pass a similar ASIN."})

    # 4. Duty: base (MFN) + origin add-on, on the factory price.
    duty_pct = num("--duty-pct")
    if duty_pct is not None:
        lines.append({"line": "import duty", "perUnit": r2(unit * duty_pct / 100), "tier": "given",
                      "note": f"{duty_pct:g}% of unit cost, your rate"})
    else:
        base, base_note, base_tier = 0.0, "base rate unknown, taken as 0% (no HTS code)", "assumed"
        if arg("--hts"):
            code = arg("--hts").replace(".", "")
            rows = [r for r in hts_search(arg("--hts")) if r["htsno"].replace(".", "").startswith(code[:8])
                    and r["generalPct"] is not None]
            if rows:
                base, base_tier = rows[0]["generalPct"], "derived"
                base_note = f"HTS {rows[0]['htsno']} general rate {rows[0]['general']}" + \
                            (" (plus a specific per-kg/per-item part not counted)" if rows[0]["specificDuty"] else "")
            else:
                base_note = f"HTS {arg('--hts')} not found with a rate; base taken as 0%"
        add = num("--extra-duty-pct", 20.0 if origin_country == "CN" else 0.0)
        add_note = (f"+ {add:g}% origin add-on" + (" (assumed for China: Section 301 plus the current additional "
                    "rate; these change often, check before you order)" if arg("--extra-duty-pct") is None and
                    origin_country == "CN" else ""))
        pct = base + add
        lines.append({"line": "import duty", "perUnit": r2(unit * pct / 100),
                      "tier": "assumed" if (base_tier == "assumed" or arg("--extra-duty-pct") is None and add) else "derived",
                      "note": f"{pct:g}% of unit cost: {base_note} {add_note}".strip()})
    value = unit * qty
    mpf = min(max(value * MPF_PCT / 100, MPF_MIN), MPF_MAX)
    lines.append({"line": "customs processing fee (MPF)", "perUnit": r2(mpf / qty), "tier": "derived",
                  "note": f"{MPF_PCT}% of ${value:,.0f} order value, min ${MPF_MIN} / max ${MPF_MAX} per entry; "
                          "under $2,500 an informal entry pays less"})

    # 5. Prep and Amazon inbound.
    prep = num("--prep", 0.0)
    lines.append({"line": "prep and FNSKU labels", "perUnit": r2(prep), "tier": "given" if arg("--prep") else "assumed",
                  "note": "your figure" if arg("--prep") else "$0: the supplier applies FNSKU labels (ask for it in "
                                                              "the quote). A prep center or Amazon labelling costs more."})
    place = num("--placement", 0.30)
    lines.append({"line": "Amazon inbound placement fee", "perUnit": r2(place),
                  "tier": "given" if arg("--placement") else "assumed",
                  "note": "your figure" if arg("--placement") else "$0.30 assumed for a standard-size unit sent to a "
                          "single inbound location; $0 if you accept Amazon's split. Check Send to Amazon."})

    total = sum(l["perUnit"] or 0 for l in lines)
    out({"landedPerUnit": r2(total), "orderUnits": qty, "orderUnitsAssumed": not qty_given,
         "firstOrderCash": r2(total * qty), "lines": lines,
         "shares": {l["line"]: round(100 * (l["perUnit"] or 0) / total, 1) for l in lines} if total else None,
         **extra, "notes": notes,
         "excludes": "Amazon referral and FBA fees, storage, ads, returns, samples, tooling/moulds (one-time)."})


def cmd_invoke():
    """Count one use of this skill: main() already sent the usage ping as event=invoke. No key,
    nothing from the conversation is sent."""
    if os.environ.get("WHM_USAGE", "").strip() == "0":
        out({"reached": False, "skipped": "WHM_USAGE=0", "waitlist": WAITLIST})
    status = usage_wait() or 0
    out({"reached": status == 200, "status": status, "route": "/health",
         "sent": {"client": "whm-skills", "skill": SKILL, "v": VERSION, "event": "invoke",
                  "cmd": "invoke", "mode": usage_mode()}, "waitlist": WAITLIST})


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    usage_ping(cmd)
    if cmd == "mode":
        md = mode()
        out({"mode": md, "keys": {"WHM_API_KEY": bool(os.environ.get("WHM_API_KEY", "").strip()),
                                  "KEEPA_API_KEY": bool(os.environ.get("KEEPA_API_KEY", "").strip())},
             **({} if md != "none" else NO_KEYS), "skill": SKILL, "version": VERSION})
    {"product": cmd_product, "api": cmd_api, "brand": cmd_brand, "niche": cmd_niche, "quotes": cmd_quotes,
     "freight": cmd_freight, "duty": cmd_duty, "landed": cmd_landed, "invoke": cmd_invoke}.get(
        cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
