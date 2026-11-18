#!/usr/bin/env python3
"""WaitHowMuch skills data helper, amazon-brand-valuation: what an Amazon brand might be worth, as
trailing-twelve net profit x a modelled multiple (WaitHowMuch's valuation model, version 2).
One WHM API key, or your own Keepa key; `value` needs no key at all.

Shared core (mode, HTTP, Keepa client, badge method) is the same as amazon-revenue-sales' scripts/whm.py.
Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key
(Keepa takes its key in the query string, so no URL is ever printed).

Mode, decided per run from the environment:
  1. WHM_API_KEY set   -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
  2. KEEPA_API_KEY set -> Keepa API directly (your tokens)
  3. neither           -> {"error": "no_keys", ...}, exit 2   (`value` runs without a key)
A WHM route that is not live yet returns {"error": "whm_route_not_live", "route": ...}; if KEEPA_API_KEY is
also set, the command falls back to Keepa instead.

Commands:
  mode                                         which mode this run would use (no provider call)
  value --profit-ttm X [--profit-ttm-high Y] [answers] [signals] [--us-only]
                                               score a profit figure you already have      (no key, no provider call)
  brand "<brand>"|<ASIN> (--margin-pct P | --profit-ttm X) [--max N] [--asins A,B,..] [answers] [signals]
                                               WHM: a researched brand's stamped valuation. Keepa: the catalogue's
                                               TTM revenue, age, reviews, rating, seasonality  (~11 + up to 2N; +1 from an
                                               ASIN; --asins skips the brand search: up to 2 per ASIN)
  api </v1/path?query>                         GET a WaitHowMuch API route (WHM mode only)

Answers (owner facts; pass only what the record supports, as inferences, with --answers-tier inferred):
  --method private_label|wholesale|handmade|pod|dropship|arbitrage|merch|kdp
  --catalog dominance|broad|concentrated|flagship|generalist|churn
  --diff-tooling yes|no|some  --diff-custom yes|no  --diff-visible yes|no  --brand-registry yes|no
  --trademark registered|licensed  --hours under5|5to10|10to20|over20  --suppliers 1|2to3|4plus
  --supplier-role redundant|per_product  --supplier-terms exclusive|contract|reseller  --issues none|resolved|open
  --account-health healthy|warnings|at_risk  --violations none|past|recent  --team none|vas|contractors|agency|employees|mixed
  --sku-strategy expanding|consolidating|stable
Signals (override what was read): --selling-since YYYY-MM-DD --reviews N --rating X --feedback-pct P
  --top-marketplace-pct P --marketplaces N --peak-month-pct P --return-rate-pct P --niche-trend-pct P --ahr N
  --off-amazon-pct P --channels both

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

COMMANDS = {"api", "brand", "mode", "value"}
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

FLAGS_WITH_VALUE = set()  # filled at the end of the file from every flag that takes a value


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

def find_business(name):
    """A researched WaitHowMuch case study whose name or slug matches."""
    _, body = whm_get("/v1/businesses?limit=100")
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())  # noqa: E731
    q = norm(name)
    for b in body.get("businesses") or []:
        if q and q in (norm(b.get("name")), norm(b.get("slug"))):
            return b
    return None




# ─── The valuation model ─────────────────────────────────────────────
# A port of WaitHowMuch's valuation model, VALUATION_VERSION 2. Same base, clamp, deltas and labels, so a
# figure here matches a case study's stamp. Annual NET PROFIT x a multiple: 2.6 base, plus or minus each
# factor the evidence supports, clamped to 1.2-8.0. Not SDE: brokers add back owner pay, so this reads
# LOW against a broker listing by roughly what the owner pays themselves.

VALUATION_VERSION = 2
BASE_MULTIPLE, MIN_MULTIPLE, MAX_MULTIPLE = 2.6, 1.2, 8.0

METHOD = {
    "private_label": ("Private label sourcing", 0.3), "wholesale": ("Wholesale sourcing", -0.1),
    "handmade": ("Handmade — production is the owner", -0.3), "pod": ("Print on demand", -0.2),
    "dropship": ("Dropship — no owned supply", -0.4), "arbitrage": ("Arbitrage — no repeatable sourcing", -0.5),
    "merch": ("Merch on Demand — a royalty, not a transferable asset", -0.6),
    "kdp": ("KDP — a royalty, not a transferable asset", -0.5),
}
CATALOG = {
    "dominance": ("Category dominance", 0.3), "broad": ("Broad catalogue, long tail", 0.1),
    "concentrated": ("Few SKUs, each standing alone", 0.1), "flagship": ("One product carries the revenue", -0.1),
    "generalist": ("Unrelated niches, no anchor", -0.2), "churn": ("Trend-dependent catalogue", -0.3),
}
DIFF = {4: ("Differentiation level 4 — hard to copy", 0.7), 3: ("Differentiation level 3 — functional customisation", 0.45),
        2: ("Differentiation level 2 — cosmetic variation", -0.1), 1: ("Differentiation level 1 — standard product", -0.4)}
RATING = [(5, "5.0", 0.35), (4.7, "4.7+", 0.3), (4.5, "4.5+", 0.2), (4.2, "4.2+", 0.05), (4.0, "4.0+", -0.1),
          (3.5, "3.5+", -0.3), (3, "3.0+", -0.5), (0, "Under 3.0", -0.75)]
REVIEWS = [(25000, "25,000+", 0.4), (10000, "10,000+", 0.35), (5000, "5,000+", 0.3), (2500, "2,500+", 0.2),
           (1000, "1,000+", 0.1), (250, "250+", -0.15), (0, "Under 250", -0.3)]
CONCENTRATION = [(95, "95%+", -0.45), (85, "85–94%", -0.25), (75, "75–84%", -0.15), (60, "60–74%", 0.05),
                 (40, "40–59%", 0.2), (0, "under 40%", 0.35)]
AHR = [(800, "800+", 0.25), (500, "500+", 0.15), (200, "200+", 0), (100, "100–199", -0.5), (0, "Under 100", -1)]
FEEDBACK = [(98, "98%+", 0.2), (95, "95%+", 0.1), (90, "90%+", -0.1), (85, "85%+", -0.3), (0, "Under 85%", -0.6)]
STAFFED = {"vas", "contractors", "agency", "employees", "mixed"}

WHY = {
    "age": "Most businesses that fail do so early; years of continuous trading is the cheapest evidence that demand, supply and the account hold up.",
    "rating": "A rating protects conversion and ad cost at once, and is the hardest thing here to repair once it slips.",
    "reviews": "Accumulated reviews are the one asset a competitor cannot buy or copy.",
    "concentration": "One Amazon marketplace carrying the revenue means one suspension or policy change reaches all of it.",
    "peak": "Seasonal revenue means funding a year of inventory to catch a few weeks of sales.",
}


def band(ladder, v):
    return next(b for b in ladder if v >= b[0])


def diff_level(a):
    if a.get("diffTooling") == "yes":
        return 4
    if a.get("diffTooling") not in ("no", "some"):
        return None
    if a.get("diffCustom") == "yes":
        return 3
    if a.get("diffCustom") != "no":
        return None
    return {"yes": 2, "no": 1}.get(a.get("diffVisible"))


def years_since(iso, today):
    try:
        then = datetime.fromisoformat(str(iso)[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (today - then).total_seconds() / (365.25 * 86400)


def value_business(profit, a, d, today):
    """valueBusiness() from the WaitHowMuch model. Returns (multiple, adjustments, missing)."""
    adj, miss = [], []

    def add(label, delta, why=None):
        adj.append({"label": label, "delta": delta, **({"why": why} if why else {})})

    age = years_since(d["sellingSince"], today) if d.get("sellingSince") else None
    if age is None:
        miss.append("sellingSince")
    elif age >= 5:
        add("Trading 5+ years", 0.5, WHY["age"])
    elif age >= 3:
        add("Trading 3+ years", 0.3, WHY["age"])
    elif age < 1.5:
        add("Under 18 months of history", -0.4, "Too short a record to tell a durable business from a lucky launch.")

    h = a.get("hoursPerWeek")
    if h == "under5":
        add("Under 5 hours a week", 0.4)
    elif h == "5to10":
        add("5–10 hours a week", 0.2)
    elif h == "over20":
        add("Over 20 hours a week", -0.4)
    elif h is None:
        miss.append("hoursPerWeek")

    sc = a.get("supplierCount")
    if sc == "1":
        add("Single supplier", -0.5)
    elif sc == "4plus":
        add("Four or more suppliers", 0.2)
    elif sc is None:
        miss.append("supplierCount")
    sr = a.get("supplierRole")
    if sr == "redundant":
        add("Suppliers can cover each other", 0.25)
    elif sr == "per_product":
        add("One supplier per product", -0.15)
    elif sc != "1" and sr is None:
        miss.append("supplierRole")
    st = a.get("supplierTerms")
    if st == "exclusive":
        add("Exclusive supply agreement", 0.4)
    elif st == "contract":
        add("Contracted supply", 0.2)
    elif st == "reseller":
        add("Resold stock, not exclusive", -0.5)

    m = METHOD.get(a.get("primaryMethod") or "")
    if m:
        if m[1]:
            add(*m)
    elif a.get("primaryMethod") is None:
        miss.append("primaryMethod")
    c = CATALOG.get(a.get("catalogStructure") or "")
    if c:
        add(*c)
    else:
        miss.append("catalogStructure")
    lvl = diff_level(a)
    if lvl:
        add(*DIFF[lvl])
    else:
        miss.append("diffTooling")

    br = a.get("brandRegistry")
    if br == "yes":
        add("Brand Registry", 0.3)
    elif br == "no":
        add("No Brand Registry", -0.3)
    else:
        miss.append("brandRegistry")
    tm = a.get("trademark")
    if tm == "registered":
        add("Registered trademark", 0.2)
    elif tm == "licensed":
        add("Licensed brand, not owned", -0.4)

    if isinstance(d.get("ratingWeighted"), (int, float)):
        b = band(RATING, d["ratingWeighted"])
        add(f"{b[1]}★ average product rating", b[2], WHY["rating"])
    else:
        miss.append("ratingWeighted")
    if isinstance(d.get("reviewTotal"), (int, float)):
        b = band(REVIEWS, d["reviewTotal"])
        add(f"{b[1]} reviews across the catalogue", b[2], WHY["reviews"])

    if (d.get("marketplaces") or 0) >= 3:
        add("3+ marketplaces", 0.2)
    if d.get("channels") == "both":
        add("FBA and FBM", 0.1)
    top = d.get("topMarketplaceSharePct")
    if isinstance(top, (int, float)):
        b = band(CONCENTRATION, top)
        add(f"{round(top)}% of revenue in one marketplace", b[2], WHY["concentration"])
    else:
        miss.append("topMarketplaceSharePct")
    off = d.get("offAmazonSharePct")
    if isinstance(off, (int, float)) and off > 0:
        add(f"{round(off)}% of revenue off Amazon", 0.35) if off >= 20 else add("Some revenue off Amazon", 0.15)

    peak = d.get("peakMonthSharePct")
    if isinstance(peak, (int, float)):
        if peak >= 25:
            add(f"{round(peak)}% of revenue in one month", -0.3, WHY["peak"])
        elif peak <= 12:
            add("Revenue spread evenly across the year", 0.2)
    else:
        miss.append("peakMonthSharePct")
    ret = d.get("returnRatePct")
    if isinstance(ret, (int, float)):
        if ret <= 3:
            add(f"{ret:.1f}% return rate", 0.2)
        elif ret >= 10:
            add(f"{ret:.1f}% return rate", -0.35)
    tr = d.get("nicheTrendPct")
    if isinstance(tr, (int, float)):
        if tr >= 10:
            add("Niche demand growing", 0.25)
        elif tr <= -10:
            add("Niche demand shrinking", -0.35)

    iss = a.get("issues")
    if iss == "open":
        add("Unresolved account or IP issue", -0.8)
    elif iss == "resolved":
        add("Past issue, resolved", -0.1)
    elif iss is None:
        miss.append("issues")
    ahr = d.get("accountHealthScore")
    if isinstance(ahr, (int, float)):
        b = band(AHR, ahr)
        if b[2]:
            add(f"Account Health Rating {b[1]}", b[2])
    else:
        miss.append("accountHealthScore")
    fb = d.get("sellerFeedbackPct")
    if isinstance(fb, (int, float)):
        b = band(FEEDBACK, fb)
        add(f"{b[1]} positive seller feedback", b[2])
    else:
        miss.append("sellerFeedbackPct")
    ah = a.get("accountHealth")
    if ah == "healthy":
        add("Account health clear", 0.2)
    elif ah == "warnings":
        add("Open account warnings", -0.4)
    elif ah == "at_risk":
        add("Account at risk of deactivation", -1)
    elif not isinstance(ahr, (int, float)):
        miss.append("accountHealth")
    v = a.get("violations")
    if v == "recent":
        add("Recent policy violations", -0.5)
    elif v == "past":
        add("Older policy violations", -0.15)
    t = a.get("team")
    if t == "none":
        add("Owner-operated", 0.1)
    elif t in STAFFED:
        add("Contractors or team in place", 0.2)
    elif t is None:
        miss.append("team")
    sk = a.get("skuStrategy")
    if sk == "expanding":
        add("Still launching new products", 0.2)
    elif sk == "consolidating":
        add("Cutting back to best sellers", -0.1)

    raw = BASE_MULTIPLE + sum(x["delta"] for x in adj)
    return min(MAX_MULTIPLE, max(MIN_MULTIPLE, round(raw, 2))), adj, miss


# The owner-only answers a public record can't settle, at their most and least favourable options.
SWING = {
    "hoursPerWeek": ("under5", "over20"), "supplierCount": ("4plus", "1"), "supplierRole": ("redundant", "per_product"),
    "primaryMethod": ("private_label", "dropship"), "catalogStructure": ("dominance", "churn"),
    "brandRegistry": ("yes", "no"), "issues": ("none", "open"), "accountHealth": ("healthy", "at_risk"),
    "team": ("contractors", "none"),
}


def sensitivity(a, d, today):
    best, worst = dict(a), dict(a)
    for k, (b, w) in SWING.items():
        if a.get(k) is None:
            best[k], worst[k] = b, w
    if a.get("diffTooling") is None:
        best["diffTooling"] = "yes"
        worst.update({"diffTooling": "no", "diffCustom": "no", "diffVisible": "no"})
    if worst.get("supplierCount") == "1":
        worst.pop("supplierRole", None)
    return value_business(1, best, d, today)[0], value_business(1, worst, d, today)[0]


ANSWER_FLAGS = {  # flag -> (answer key, allowed values)
    "--method": ("primaryMethod", set(METHOD)), "--catalog": ("catalogStructure", set(CATALOG)),
    "--diff-tooling": ("diffTooling", {"yes", "no", "some"}), "--diff-custom": ("diffCustom", {"yes", "no"}),
    "--diff-visible": ("diffVisible", {"yes", "no"}), "--brand-registry": ("brandRegistry", {"yes", "no"}),
    "--trademark": ("trademark", {"registered", "licensed", "none"}),
    "--hours": ("hoursPerWeek", {"under5", "5to10", "10to20", "over20"}),
    "--suppliers": ("supplierCount", {"1", "2to3", "4plus"}), "--supplier-role": ("supplierRole", {"redundant", "per_product"}),
    "--supplier-terms": ("supplierTerms", {"exclusive", "contract", "reseller", "none"}),
    "--issues": ("issues", {"none", "resolved", "open"}),
    "--account-health": ("accountHealth", {"healthy", "warnings", "at_risk"}),
    "--violations": ("violations", {"none", "past", "recent"}),
    "--team": ("team", {"none"} | STAFFED), "--sku-strategy": ("skuStrategy", {"expanding", "consolidating", "stable"}),
}
DERIVED_FLAGS = {  # flag -> (derived key, type)
    "--selling-since": ("sellingSince", str), "--reviews": ("reviewTotal", float), "--rating": ("ratingWeighted", float),
    "--feedback-pct": ("sellerFeedbackPct", float), "--top-marketplace-pct": ("topMarketplaceSharePct", float),
    "--marketplaces": ("marketplaces", int), "--peak-month-pct": ("peakMonthSharePct", float),
    "--return-rate-pct": ("returnRatePct", float), "--niche-trend-pct": ("nicheTrendPct", float),
    "--ahr": ("accountHealthScore", float), "--off-amazon-pct": ("offAmazonSharePct", float), "--channels": ("channels", str),
}


def num_arg(flag, typ=float):
    v = arg(flag)
    if v is None:
        return None
    try:
        return typ(str(v).replace("$", "").replace(",", "").replace("%", ""))
    except ValueError:
        out({"error": "bad_number", "flag": flag, "value": v}, 4)


def read_inputs(derived=None, tiers=None):
    """Answers (all inferences or the owner's) and derived signals (flags override what was read)."""
    a, d, tiers = {}, dict(derived or {}), dict(tiers or {})
    for flag, (key, allowed) in ANSWER_FLAGS.items():
        v = arg(flag)
        if v is not None:
            if v not in allowed:
                out({"error": "bad_value", "flag": flag, "value": v, "allowed": sorted(allowed)}, 4)
            a[key] = v
            tiers[key] = arg("--answers-tier", "given")
    for flag, (key, typ) in DERIVED_FLAGS.items():
        v = num_arg(flag, typ) if typ is not str else arg(flag)
        if v is not None:
            d[key] = v
            tiers[key] = "given"
    return a, d, tiers


def score(profit_lo, profit_hi, a, d, tiers, today, extra):
    mult, adj, miss = value_business(profit_lo, a, d, today)
    best, worst = sensitivity(a, d, today)
    res = {**extra,
           "valuation": {
               "value": round(profit_lo * mult) if profit_lo and profit_lo > 0 else None,
               "valueRange": {"low": round(profit_lo * mult), "high": round(profit_hi * mult)}
               if profit_lo and profit_hi and profit_lo > 0 and profit_hi != profit_lo else None,
               "multiple": mult if profit_lo and profit_lo > 0 else None,
               "netProfitTtm": profit_lo, "netProfitTtmHigh": profit_hi if profit_hi != profit_lo else None,
               "base": BASE_MULTIPLE, "clamp": [MIN_MULTIPLE, MAX_MULTIPLE],
               "adjustments": adj, "missingSignals": miss,
               "ifOwnerAnswersBest": best, "ifOwnerAnswersWorst": worst,
               "asOf": today.date().isoformat(), "version": VALUATION_VERSION},
           "inputs": {"answers": a, "derived": d, "tiers": tiers},
           "basis": "Trailing-twelve NET profit x a modelled multiple (WaitHowMuch valuation model v2). Not SDE: a "
                    "broker's figure adds back owner pay, so this reads low against a broker listing.",
           "disclaimer": "An estimate from public data and stated assumptions, not an appraisal and not financial, "
                         "investment or legal advice. A buyer prices due diligence, the books and terms."}
    if not (profit_lo and profit_lo > 0):
        res["valuation"]["note"] = "No positive trailing-twelve profit: unvalued (not the same as worthless)."
    out(res)


def cmd_value():
    lo = num_arg("--profit-ttm")
    if lo is None:
        out({"error": "usage", "message": "value --profit-ttm X [--profit-ttm-high Y] [answers/signals]; "
                                          "get X from amazon-profit-calculator's ttm.profitLow"}, 4)
    hi = num_arg("--profit-ttm-high") or lo
    a, d, tiers = read_inputs(tiers={"netProfitTtm": arg("--profit-tier", "given")})
    if "topMarketplaceSharePct" not in d and "--us-only" in sys.argv:
        d["topMarketplaceSharePct"], tiers["topMarketplaceSharePct"] = 100.0, "assumed"
    today = datetime.fromisoformat(arg("--as-of")).replace(tzinfo=timezone.utc) if arg("--as-of") else datetime.now(timezone.utc)
    score(lo, hi, a, d, tiers, today, {"mode": "inputs_only", "what": "value"})


def researched_valuation(b):
    _, body = whm_get(f"/v1/businesses/{urllib.parse.quote(b['slug'])}")
    biz = body.get("business") or body
    v = biz.get("valuation")
    return {"mode": "whm", "researched": True, "name": biz.get("name"), "valuation": v,
            "latestMonthlyProfit": biz.get("latestMonthlyProfit"), "latestMarginPct": biz.get("latestMarginPct"),
            "confidence": biz.get("confidence"),
            "caseStudy": f"https://waithowmuch.com/business/{b['slug']}/?utm_source=whm-skills&utm_medium=skill"
                         f"&utm_campaign=whm-skills&utm_content={SKILL}",
            "basis": (v or {}).get("basis") or "Trailing-twelve net profit at a modelled multiple.",
            "disclaimer": "WaitHowMuch's researched estimate, stamped at the case study's snapshot month. Not an "
                          "appraisal and not financial, investment or legal advice."}


VALUATION_ROUTE = "GET /v1/tools/valuation?brand=|asin=&marginPct="   # proposed; not in API-PROXY.md


def products_rated(k, asins):
    """products() plus rating=1, so stats.current carries RATING [16] and COUNT_REVIEWS [17]
    (Keepa may charge up to 1 extra token per product for it)."""
    since_days = (date.today() - BADGE_FLOOR).days
    res = []
    for i in range(0, len(asins), 100):
        r = k.call("product", {"asin": ",".join(asins[i:i + 100]), "stats": 30, "history": 1, "rating": 1, "days": since_days})
        res += r.get("products") or []
    return res


def cmd_brand():
    raw = positional()
    n = int_arg("--max", 50, 1, 300)
    if not raw:
        out({"error": "empty", "message": "give a brand name as on Amazon, or one of its ASINs"}, 4)
    md = need_mode()
    if md == "whm":
        b = find_business(raw)
        if b:
            out(researched_valuation(b))
        status, body = whm_get("/v1/tools/valuation?" + urllib.parse.urlencode({"brand": raw}), allow=(404,))
        if status == 200:
            out({"mode": "whm", **body})
        if not has("KEEPA_API_KEY"):
            if not route_missing(status, body):
                out({"mode": "whm", "status": status, **body}, 1)
            out(not_live(VALUATION_ROUTE,
                         f"'{raw}' is not a researched WaitHowMuch case study, and WaitHowMuch has no valuation route for "
                         "other brands yet. Without Keepa: run amazon-profit-calculator for a trailing-twelve profit and "
                         "use `value --profit-ttm X`."), 2)
    margin, profit_given = num_arg("--margin-pct"), num_arg("--profit-ttm")
    if margin is None and profit_given is None:
        out({"error": "usage", "message": "pass --margin-pct (net margin after ads, from amazon-profit-calculator) "
                                          "or --profit-ttm X"}, 4)
    k = Keepa()
    given = [a for a in (parse_asin(x, fatal=False) for x in (arg("--asins") or "").split(",") if x.strip()) if a]
    if given:
        # The catalogue named by the user (e.g. amazon-revenue-sales' product rows): no Product Finder query.
        k.ensure(2 * len(given))
        prods = products_rated(k, given[:n])
        brand, found = raw, len(prods)
    else:
        asin = parse_asin(raw, fatal=False)
        if asin:
            k.ensure(12 + 2 * n)
            r = k.call("product", {"asin": asin, "stats": 0})
            brand = ((r.get("products") or [{}])[0] or {}).get("brand")
            if not brand:
                out({"mode": "keepa", "error": "asin_not_found", "asin": asin, **k.meta()}, 1)
        else:
            brand = raw
            k.ensure(11 + 2 * n)
        q = k.call("query", {}, {"brand": [brand], "monthlySold_gte": 1, "sort": [["monthlySold", "desc"]],
                                 "perPage": max(50, n), "page": 0})
        found = q.get("totalResults")
        prods = products_rated(k, (q.get("asinList") or [])[:n])
    if not prods:
        out({"mode": "keepa", "error": "no_badged_listings", "brand": brand, **k.meta()}, 1)
    hist = series(prods)
    full = [r for r in hist if not r.get("live")][-12:]
    ttm_lo = sum(r["revenueLowCents"] for r in full) / 100
    ttm_hi = sum(r["revenueHighCents"] for r in full) / 100
    d, tiers = {}, {}
    listed = [kdate(p["listedSince"]).date().isoformat() for p in prods if (p.get("listedSince") or 0) > 0]
    if listed:
        d["sellingSince"], tiers["sellingSince"] = min(listed), "derived"
    rev_w = rat_w = reviews = 0
    for p in prods:
        cur = (p.get("stats") or {}).get("current") or []
        s = shape(p)
        rv = (s["revenue"] or {}).get("lowCents") or 0
        rating = cur[16] / 10 if len(cur) > 16 and (cur[16] or 0) > 0 else None
        if len(cur) > 17 and (cur[17] or 0) > 0:
            reviews += cur[17]
        if rating and rv:
            rev_w, rat_w = rev_w + rv, rat_w + rating * rv
    if reviews:
        d["reviewTotal"], tiers["reviewTotal"] = reviews, "derived"
    if rev_w:
        d["ratingWeighted"], tiers["ratingWeighted"] = round(rat_w / rev_w, 2), "derived"
    if len(full) == 12 and ttm_lo:
        d["peakMonthSharePct"] = round(100 * max(r["revenueLowCents"] for r in full) / 100 / ttm_lo, 1)
        tiers["peakMonthSharePct"] = "derived"
    d["topMarketplaceSharePct"], tiers["topMarketplaceSharePct"] = 100.0, "assumed"
    a, d, tiers = read_inputs(d, tiers)
    meta = {"mode": "keepa", "what": "brand", "brand": brand, "badgedListings": found, "pricedListings": len(prods),
            "capped": bool(found and found > n),
            "ttmRevenue": {"months": len(full), "low": round(ttm_lo), "high": round(ttm_hi),
                           "window": f"{full[0]['month']}..{full[-1]['month']}" if full else None},
            "retrievedAt": retrieved(), "source": "Keepa", **k.meta()}
    if profit_given is not None:
        lo, hi = profit_given, num_arg("--profit-ttm-high") or profit_given
        tiers["netProfitTtm"] = arg("--profit-tier", "given")
    else:
        if len(full) < 12:
            out({**meta, "error": "under_12_months",
                 "message": f"Only {len(full)} full months of badge history: the research values nothing on less than "
                            "twelve (a 'TTM' from fewer months is the most misleading number a valuation can carry). "
                            "Pass --profit-ttm if you have the real figure."}, 4)
        lo, hi = ttm_lo * margin / 100, ttm_hi * margin / 100
        tiers["netProfitTtm"] = f"derived (TTM revenue x {margin:g}% margin, {arg('--margin-tier', 'derived')})"
    score(round(lo, 2), round(hi, 2), a, d, tiers, datetime.now(timezone.utc), meta)


def cmd_api():
    if need_mode() != "whm":
        out({"error": "wrong_mode", "mode": mode(), "message": "api runs in WHM mode (WHM_API_KEY)"}, 2)
    out({"mode": "whm", **whm_get(positional())[1]})


FLAGS_WITH_VALUE.update(set(ANSWER_FLAGS) | set(DERIVED_FLAGS) | {
    "--max", "--asins", "--margin-pct", "--margin-tier", "--profit-ttm", "--profit-ttm-high", "--profit-tier", "--answers-tier", "--as-of"})


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    usage_ping(cmd)
    if cmd == "mode":
        md = mode()
        out({"mode": md, "keys": {"WHM_API_KEY": has("WHM_API_KEY"), "KEEPA_API_KEY": has("KEEPA_API_KEY")},
             **({} if md != "none" else NO_KEYS), "skill": SKILL, "version": VERSION})
    {"value": cmd_value, "brand": cmd_brand, "api": cmd_api}.get(
        cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
