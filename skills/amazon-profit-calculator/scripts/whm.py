#!/usr/bin/env python3
"""WaitHowMuch skills data helper, amazon-profit-calculator: a monthly P&L and margin waterfall for an
Amazon ASIN, a brand, or the user's own numbers. One WHM API key, or your own Keepa key.

Shared core (mode, HTTP, Keepa client, badge method) is the same as amazon-revenue-sales' scripts/whm.py.
Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key
(Keepa takes its key in the query string, so no URL is ever printed).

Mode, decided per run from the environment:
  1. WHM_API_KEY set   -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
  2. KEEPA_API_KEY set -> Keepa API directly (your tokens)
  3. neither           -> {"error": "no_keys", ...}, exit 2   (pnl --price/--units needs no key)
A WHM route that is not live yet returns {"error": "whm_route_not_live", "route": ...}; if KEEPA_API_KEY is
also set, the command falls back to Keepa instead.

Commands:
  mode                                   which mode this run would use (no provider call)
  pnl <ASIN|amazon.com URL> [costs]      one listing's month + monthly series     (Keepa: 1 token)
  pnl --brand "<brand>" [--max N] [costs]  a brand's badged listings              (Keepa: ~11 + N)
  pnl --price P --units N --fba-fee F [costs]   your own numbers                  (no key, no provider call)
  api </v1/path?query>                   GET a WaitHowMuch API route (WHM mode only)

Costs (all optional; a missing cost of goods or ad line is reported in `missing`, never invented):
  cost of goods  --landed X [--landed-tier derived] | --cogs-pct P |
                 --unit-cost X [--freight-per-unit F] [--duty-pct P] [--placement X] [--dest-coast east]
  advertising    --ads-band LOW,CENTRAL,HIGH (monthly $, from amazon-adspend-estimator) | --ads-monthly X | --ads-pct P
  returns        --returns-pct P            (default $0: not modelled, profit is a ceiling)
  storage        --storage-monthly X | --storage-per-unit X   (default $0, same)
  overrides      --price P --units N --fba-fee F --referral-pct R

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

COMMANDS = {"api", "mode", "pnl"}
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




# ─── The P&L (research-amazon-store §8 / build-ecom-biz-page "Margin breakdown") ─
#
# Lines, in the case studies' order: cost of goods (landed), Amazon referral, FBA fulfilment,
# advertising, then returns and storage, which the research does NOT model (zero, so profit is a
# ceiling) unless the user gives a figure. Every line carries a tier: given / derived / assumed.

# Dated China->US LCL readings (low end of Freightos' band, door to door), the same table as the
# amazon-cogs-estimator skill. Freight per unit = the listing's package volume x $/cbm, which is how
# the case studies price their shipping table.
STORED_RATES = {
    "CN-USWC": {"route": "Shanghai -> Los Angeles", "usdPerCbm": 373.75, "readAt": "2026-11-17"},
    "CN-USEC": {"route": "Shanghai -> New York", "usdPerCbm": 546.01, "readAt": "2026-09-28"},
}
CHINA_EXTRA_DUTY_PCT = 20.0   # the research's assumed Section 301 + additional rate on China-origin goods
PLACEMENT_PER_UNIT = 0.30     # assumed Amazon inbound placement, standard size, single location
DEFAULT_REFERRAL_PCT = 15.0   # most categories
ADSPEND_SKILL = "amazon-adspend-estimator"
COGS_SKILL = "amazon-cogs-estimator"


def money_arg(flag):
    v = arg(flag)
    if v is None:
        return None
    try:
        return float(str(v).replace("$", "").replace(",", "").replace("%", ""))
    except ValueError:
        out({"error": "bad_number", "flag": flag, "value": v}, 4)


def band_arg(flag):
    """--ads-band 800,1200,1600 (low,central,high monthly $) or 800-1600 (central = midpoint)."""
    v = arg(flag)
    if v is None:
        return None
    parts = [p for p in re.split(r"[,\s/]+|(?<=\d)-(?=\d)", v.replace("$", "")) if p]
    try:
        nums = [float(p.replace("k", "e3").replace("K", "e3")) for p in parts]
    except ValueError:
        out({"error": "bad_band", "flag": flag, "message": "give low,central,high monthly dollars, e.g. 800,1200,1600"}, 4)
    if len(nums) == 2:
        nums = [nums[0], (nums[0] + nums[1]) / 2, nums[1]]
    if len(nums) == 1:
        nums = nums * 3
    if len(nums) != 3 or not nums[0] <= nums[1] <= nums[2]:
        out({"error": "bad_band", "flag": flag, "message": "low <= central <= high"}, 4)
    return {"low": nums[0], "central": nums[1], "high": nums[2]}


def r2(x):
    return None if x is None else round(x + 1e-9, 2)


def pct(part, whole):
    return (round(100 * part / whole, 2) + 0.0) if whole else None


def cogs_from_options(price, package):
    """Landed cost per unit. Returns (perUnit or None, tier, basis, parts)."""
    landed, unit, cogs_pct = money_arg("--landed"), money_arg("--unit-cost"), money_arg("--cogs-pct")
    if landed is not None:
        return landed, arg("--landed-tier", "given"), (
            "landed cost per unit you gave" + (" (from amazon-cogs-estimator)" if arg("--landed-tier") == "derived" else "")), None
    if cogs_pct is not None:
        return price * cogs_pct / 100, "given", f"{cogs_pct:g}% of the selling price, your figure", None
    if unit is None:
        return None, "missing", (f"no cost of goods given: pass --landed (run {COGS_SKILL} for it), "
                                 "--unit-cost (factory price) or --cogs-pct"), None
    parts = [{"part": "make (factory price)", "perUnit": r2(unit), "tier": arg("--unit-basis", "given")}]
    fpu = money_arg("--freight-per-unit")
    if fpu is not None:
        parts.append({"part": "freight to Amazon", "perUnit": r2(fpu), "tier": "given"})
    elif package:
        lane = "CN-USEC" if arg("--dest-coast", "west").lower().startswith("e") else "CN-USWC"
        rate = STORED_RATES[lane]
        cbm = package["lengthMm"] * package["widthMm"] * package["heightMm"] / 1e9
        parts.append({"part": "freight to Amazon", "perUnit": r2(cbm * rate["usdPerCbm"]), "tier": "derived",
                      "basis": f"listing package {package['lengthMm']}x{package['widthMm']}x{package['heightMm']} mm = "
                               f"{cbm:.4f} cbm x ${rate['usdPerCbm']}/cbm ({rate['route']} LCL, low end of Freightos' band, "
                               f"read {rate['readAt']}). Freight estimate: Freightos (https://www.freightos.com)"})
    else:
        parts.append({"part": "freight to Amazon", "perUnit": r2(unit * 0.10), "tier": "assumed",
                      "basis": "10% of factory price: no package size"})
    duty = money_arg("--duty-pct")
    if duty is not None:
        parts.append({"part": "import duty", "perUnit": r2(unit * duty / 100), "tier": "given", "basis": f"{duty:g}% of factory price"})
    else:
        parts.append({"part": "import duty", "perUnit": r2(unit * CHINA_EXTRA_DUTY_PCT / 100), "tier": "assumed",
                      "basis": f"{CHINA_EXTRA_DUTY_PCT:g}% of factory price: China add-ons, base (MFN) rate unknown. "
                               f"Run {COGS_SKILL} with the HTS code for a real rate"})
    place = money_arg("--placement")
    parts.append({"part": "Amazon inbound placement", "perUnit": r2(PLACEMENT_PER_UNIT if place is None else place),
                  "tier": "assumed" if place is None else "given"})
    total = sum(p["perUnit"] for p in parts)
    tiers = {p["tier"] for p in parts}
    tier = "assumed" if "assumed" in tiers else "derived" if "derived" in tiers else "given"
    return total, tier, "make + freight + duty + inbound placement, quick landed cost (see parts)", parts


def ads_from_options(revenue):
    """Monthly ad spend at this revenue: (dict low/central/high or None, tier, basis)."""
    band, monthly, ads_pct = band_arg("--ads-band"), money_arg("--ads-monthly"), money_arg("--ads-pct")
    if band:
        return band, arg("--ads-tier", "derived"), f"modelled band from {ADSPEND_SKILL}: ${band['low']:,.0f} / " \
                                                    f"${band['central']:,.0f} / ${band['high']:,.0f} a month (central used)"
    if monthly is not None:
        return {"low": monthly, "central": monthly, "high": monthly}, arg("--ads-tier", "given"), "monthly ad spend you gave"
    if ads_pct is not None:
        v = revenue * ads_pct / 100
        return {"low": v, "central": v, "high": v}, arg("--ads-tier", "given"), f"{ads_pct:g}% of revenue"
    return None, "missing", f"no ad spend given: run {ADSPEND_SKILL} and pass its band as --ads-band low,central,high"


def waterfall(revenue, units, referral, fba, fba_basis, cogs_unit, cogs_tier, cogs_basis, cogs_parts,
              rev_basis, referral_basis, referral_tier="derived", fba_tier="derived", cogs_total=None, rev_tier="derived"):
    """One month's margin waterfall. cogs_total overrides cogs_unit x units (brand mode)."""
    lines = [{"line": "Revenue", "monthly": r2(revenue), "tier": rev_tier, "basis": rev_basis}]

    def add(name, amount, tier, basis, **kw):
        lines.append({"line": name, "monthly": None if amount is None else r2(-amount),
                      "pctOfRevenue": None if amount is None else (pct(-amount, revenue) or 0.0),
                      "perUnit": r2(-amount / units) if amount is not None and units else None,
                      "tier": tier, "basis": basis, **kw})

    cogs = cogs_total if cogs_total is not None else (cogs_unit * units if cogs_unit is not None else None)
    add("Cost of goods (landed)", cogs, cogs_tier, cogs_basis, **({"parts": cogs_parts} if cogs_parts else {}))
    add("Amazon referral fee", referral, referral_tier, referral_basis)
    add("FBA fulfilment", fba, fba_tier, fba_basis)
    ads, ads_tier, ads_basis = ads_from_options(revenue)
    add("Advertising", ads["central"] if ads else None, ads_tier, ads_basis)
    ret_pct = money_arg("--returns-pct")
    add("Returns", revenue * ret_pct / 100 if ret_pct is not None else 0.0,
        "given" if ret_pct is not None else "assumed",
        f"{ret_pct:g}% of revenue, your figure" if ret_pct is not None
        else "not modelled (the research's convention): $0, so profit is a ceiling")
    sto_m, sto_u = money_arg("--storage-monthly"), money_arg("--storage-per-unit")
    sto = sto_m if sto_m is not None else (sto_u * units if sto_u is not None else None)
    add("Storage", sto if sto is not None else 0.0, "given" if sto is not None else "assumed",
        "your figure" if sto is not None else "not modelled (the research's convention): $0, so profit is a ceiling")

    known = [l for l in lines[1:] if l["monthly"] is not None]
    missing = [l["line"] for l in lines[1:] if l["monthly"] is None]
    costs = -sum(l["monthly"] for l in known)
    before_ads = revenue - sum(-l["monthly"] for l in known if l["line"] != "Advertising")
    res = {"lines": lines, "missing": missing,
           "marginBeforeAdsPct": pct(before_ads, revenue) if "Cost of goods (landed)" not in missing else None}
    if missing:
        res["leftBeforeMissing"] = r2(revenue - costs)
        res["profit"] = None
        res["marginPct"] = None
    else:
        res["profit"] = r2(revenue - costs)
        res["marginPct"] = pct(revenue - costs, revenue)
        if ads and ads["low"] != ads["high"]:
            res["profitAcrossAdsBand"] = {"atAdsHigh": r2(revenue - costs + ads["central"] - ads["high"]),
                                          "atAdsLow": r2(revenue - costs + ads["central"] - ads["low"])}
    return res


def verdict(m):
    if m is None:
        return None
    return "comfortable (25%+)" if m >= 25 else "thin (10-25%)" if m >= 10 else "under water (below 10%)"


def series_profit(hist, margin_pct):
    """The research's convention: every month costed at the snapshot month's margin."""
    if margin_pct is None:
        return None, None
    rows = [{"month": r["month"], "revenueLowCents": r["revenueLowCents"], "revenueHighCents": r["revenueHighCents"],
             "profitLow": r2(r["revenueLowCents"] / 100 * margin_pct / 100),
             **({"live": True} if r.get("live") else {})} for r in hist]
    full = [r for r in rows if not r.get("live")]
    ttm = full[-12:]
    rev = sum(r["revenueLowCents"] for r in ttm) / 100
    peak = max((r["revenueLowCents"] for r in ttm), default=0) / 100
    return rows, {"months": len(ttm), "complete": len(ttm) == 12,
                  "revenueLow": r2(rev), "profitLow": r2(rev * margin_pct / 100),
                  "peakMonthSharePct": pct(peak, rev) if len(ttm) == 12 else None,
                  "note": "Every past month costed at this month's margin (the case studies' one-model convention). "
                          "Revenue is a floor; profit is a ceiling (no returns/storage/overhead unless given)."}


PNL_NOTE = ("An estimate, not the seller's books. Revenue = Amazon's 'bought in past month' badge x today's price "
            "(a floor; the low end of the badge bucket is used). Each cost line says whether it is given (yours), "
            "derived (from a named source) or assumed (a default to replace).")


def pnl_product():
    raw = positional()
    md = mode()
    price_o, units_o, fba_o, ref_o = money_arg("--price"), money_arg("--units"), money_arg("--fba-fee"), money_arg("--referral-pct")
    p, extra, hist = None, {}, None
    if raw:
        if md == "none":
            out(NO_KEYS, 2)
        if md == "whm" and not has("KEEPA_API_KEY"):
            _, body = whm_get("/v1/tools/product-sales?" + urllib.parse.urlencode({"asin": raw}))
            p = body
            extra = {"mode": "whm", "historyNote": {
                "error": "whm_route_not_live", "route": "GET /v1/tools/product-sales?asin=&history=1",
                "note": "WaitHowMuch serves the current month only; the monthly series (and so a trailing-twelve "
                        "profit) is not live yet. Set KEEPA_API_KEY for it."}}
        else:
            asin = parse_asin(raw)
            k = Keepa()
            r = k.call("product", {"asin": asin, "stats": 30, "history": 1, "days": (date.today() - BADGE_FLOOR).days})
            kp = (r.get("products") or [None])[0]
            if not kp or (not kp.get("title") and not kp.get("categoryTree")):
                out({"mode": "keepa", "error": "asin_not_found", "asin": asin, **k.meta()}, 1)
            p = shape(kp)
            hist = series([kp])
            extra = {"mode": "keepa", "source": "Keepa", **k.meta()}
    elif price_o is None or units_o is None:
        out({"error": "usage", "message": "pnl <ASIN|amazon.com URL> [...]  or  pnl --price P --units N --fba-fee F [...]"}, 4)
    else:
        extra = {"mode": "inputs_only"}

    price = price_o if price_o is not None else ((p.get("price") or {}).get("cents") or 0) / 100
    if not price:
        out({"error": "no_price", "message": "the listing has no current price; pass --price"}, 4)
    u = (p or {}).get("units") or {}
    badged = u.get("source") == "amazon_badge"
    if units_o is not None:
        units_lo = units_hi = int(units_o) if float(units_o).is_integer() else units_o
        units_basis = "units a month you gave"
    elif badged:
        units_lo, units_hi = u["low"], u["high"]
        units_basis = f"Amazon's {u['label']} bought-in-past-month badge ({units_lo:,}-{units_hi:,} units)"
    else:
        units_lo = units_hi = 0
        lb = u.get("lastBadge")
        units_basis = "no badge now (under ~50 a month)" + (f"; last badge {lb['label']} on {lb['seenAt']}" if lb else "") + \
                      ": pass --units for a monthly figure"
    ref_pct = ref_o if ref_o is not None else ((p or {}).get("referralFeePercent") or None)
    ref_tier = "given" if ref_o is not None else "derived" if ref_pct else "assumed"
    ref_pct = ref_pct or DEFAULT_REFERRAL_PCT
    fba_fee = fba_o if fba_o is not None else (((p or {}).get("amazonFbaFeeCents") or 0) / 100 or None)
    fba_tier = "given" if fba_o is not None else "derived" if fba_fee else "missing"
    pkg = (p or {}).get("package")
    tier_note = ""
    if pkg:
        L, W, H = sorted([pkg["lengthMm"] / 25.4, pkg["widthMm"] / 25.4, pkg["heightMm"] / 25.4], reverse=True)
        oz = pkg["weightG"] / 28.3495
        tier = ("Small Standard" if L <= 15 and W <= 12 and H <= 0.75 and oz <= 16 else
                "Large Standard" if L <= 18 and W <= 14 and H <= 8 and oz <= 320 else "Bulky (check Amazon's table)")
        tier_note = f"Size tier: {tier}. Box {L:.1f} x {W:.1f} x {H:.1f} in, {oz:.1f} oz. "
    fba_basis = (tier_note + (f"${fba_fee:.2f} a unit, " + ("your figure" if fba_o is not None else "Amazon's FBA fee for this listing (Keepa pick-and-pack)"))
                 if fba_fee else f"no FBA fee known: pass --fba-fee (Amazon's revenue calculator) or a similar ASIN")
    cogs_unit, cogs_tier, cogs_basis, parts = cogs_from_options(price, pkg)

    def month(units):
        rev = units * price
        return waterfall(rev, units, rev * ref_pct / 100, fba_fee * units if fba_fee else None, fba_basis,
                         cogs_unit, cogs_tier, cogs_basis, parts,
                         f"{units:,} units x ${price:.2f} ({units_basis})", f"{ref_pct:g}% of the price" +
                         (" (Keepa, this listing's category)" if ref_tier == "derived" else " (most categories)" if ref_tier == "assumed" else ""),
                         referral_tier=ref_tier, fba_tier=fba_tier,
                         rev_tier="given" if units_o is not None and (price_o is not None or not raw) else "derived")

    # Per unit at the price, fixed costs (ads $, storage $) spread over the floor units.
    floor = month(units_lo)
    res = {**extra, "what": "product", "asin": (p or {}).get("asin"), "title": ((p or {}).get("title") or "")[:120] or None,
           "brand": (p or {}).get("brand"), "month": datetime.now(timezone.utc).strftime("%Y-%m"),
           "price": r2(price), "unitsLow": units_lo, "unitsHigh": units_hi,
           "floor": floor, "high": month(units_hi) if units_hi != units_lo else None,
           "verdict": verdict(floor["marginPct"]), "method": PNL_NOTE}
    if units_lo == 0:
        res["noUnits"] = "No monthly units (no badge): monthly lines are $0. Ask the user for expected units and pass --units."
    if hist:
        rows, ttm = series_profit(hist, floor["marginPct"])
        res["history"], res["ttm"] = rows, ttm
    res["next"] = [x for x in (
        f"run {ADSPEND_SKILL} on this ASIN/brand and re-run with --ads-band low,central,high" if "Advertising" in floor["missing"] else None,
        f"run {COGS_SKILL} for a landed cost and re-run with --landed X --landed-tier derived" if "Cost of goods (landed)" in floor["missing"] else None,
        "pass --fba-fee" if "FBA fulfilment" in floor["missing"] else None) if x]
    res["retrievedAt"] = retrieved()
    out(res)


def researched_pnl(b):
    _, m = whm_get(f"/v1/businesses/{urllib.parse.quote(b['slug'])}/metrics")
    by = {}
    for x in m.get("metrics") or []:
        by.setdefault(x["periodStart"][:7], {})[x["type"]] = float(x["value"])
    months = sorted(k for k, v in by.items() if "revenue" in v)
    last = months[-1] if months else None
    cur = by.get(last, {})
    rev, prof, ads = cur.get("revenue"), cur.get("profit"), cur.get("ad_spend")
    lines = None
    if rev:
        lines = [{"line": "Revenue", "monthly": r2(rev), "tier": "derived", "basis": "WaitHowMuch researched case study"}]
        if prof is not None:
            other = rev - prof - (ads or 0)
            lines.append({"line": "Cost of goods + Amazon fees (+ other modelled lines)", "monthly": r2(-other),
                          "pctOfRevenue": pct(-other, rev), "tier": "derived",
                          "basis": "the case study's margin breakdown, line by line, is on its page"})
        if ads is not None:
            lines.append({"line": "Advertising", "monthly": r2(-ads), "pctOfRevenue": pct(-ads, rev), "tier": "derived",
                          "basis": "modelled by WaitHowMuch's amazon-adspend-spy research"})
    ttm = months[-12:]
    return {"mode": "whm", "what": "brand", "researched": True, "name": b.get("name"), "month": last,
            "floor": {"lines": lines, "profit": r2(prof), "marginPct": pct(prof, rev) if rev and prof is not None else None},
            "ttm": {"months": len(ttm), "complete": len(ttm) == 12,
                    "revenueLow": r2(sum(by[k].get("revenue", 0) for k in ttm)),
                    "profitLow": r2(sum(by[k].get("profit", 0) for k in ttm))},
            "confidence": b.get("confidence"),
            "caseStudy": f"https://waithowmuch.com/business/{b['slug']}/?utm_source=whm-skills&utm_medium=skill"
                         f"&utm_campaign=whm-skills&utm_content={SKILL}",
            "method": "WaitHowMuch's researched case study: cost of goods from supplier quotes, fees per listing, "
                      "ads modelled. Profit is a ceiling (returns, storage, overhead not modelled)."}


def pnl_brand():
    name = arg("--brand")
    n = int_arg("--max", 50, 1, 300)
    md = need_mode()
    if md == "whm":
        b = find_business(name)
        if b:
            out(researched_pnl(b))
        status, body = whm_get("/v1/tools/brand-revenue?" + urllib.parse.urlencode({"brand": name, "max": min(n, 50)}),
                               allow=(404,))
        if status == 200:
            out({"mode": "whm", **body, "note": "brand-revenue answered; this helper does not yet cost its rows. "
                                               "Set KEEPA_API_KEY for the full P&L."})
        if not has("KEEPA_API_KEY"):
            if not route_missing(status, body):
                out({"mode": "whm", "status": status, **body}, 1)
            out(not_live("GET /v1/tools/brand-revenue?brand=&max=",
                         f"'{name}' is not a researched WaitHowMuch case study, and the brand-revenue route "
                         "(API-PROXY.md, Phase 2) is not live yet, so a brand P&L needs KEEPA_API_KEY."), 2)
    if arg("--unit-cost") is not None:
        out({"error": "usage", "message": "a brand has many products: pass --cogs-pct (of revenue) or --landed "
                                          "(blended per unit), not --unit-cost"}, 4)
    k = Keepa()
    k.ensure(11 + n)
    q = k.call("query", {}, {"brand": [name], "monthlySold_gte": 1, "sort": [["monthlySold", "desc"]],
                             "perPage": max(50, n), "page": 0})
    found = q.get("totalResults")
    prods = products(k, (q.get("asinList") or [])[:n])
    rows = []
    for kp in prods:
        s = shape(kp)
        if s["units"]["source"] != "amazon_badge" or not s["price"]:
            continue
        rows.append({"asin": s["asin"], "price": s["price"]["cents"] / 100, "lo": s["units"]["low"], "hi": s["units"]["high"],
                     "ref": s["referralFeePercent"], "fba": (s["amazonFbaFeeCents"] or 0) / 100 or None})
    if not rows:
        out({"mode": "keepa", "error": "no_badged_listings", "brand": name, **k.meta()}, 1)

    def month(key):
        rev = sum(r[key] * r["price"] for r in rows)
        units = sum(r[key] for r in rows)
        referral = sum(r[key] * r["price"] * (r["ref"] or DEFAULT_REFERRAL_PCT) / 100 for r in rows)
        known = [r for r in rows if r["fba"]]
        fba_known = sum(r[key] * r["fba"] for r in known)
        share = sum(r[key] * r["price"] for r in known) / rev if rev else 0
        fba = fba_known / share if share else None  # unknown-fee listings at the known listings' fee rate
        landed, cogs_pct = money_arg("--landed"), money_arg("--cogs-pct")
        if landed is not None:
            cogs, tier, basis = landed * units, arg("--landed-tier", "given"), f"${landed:.2f} landed per unit (blended), x {units:,} units"
        elif cogs_pct is not None:
            cogs, tier, basis = rev * cogs_pct / 100, "given", f"{cogs_pct:g}% of revenue, your figure"
        else:
            cogs, tier, basis = None, "missing", f"no cost of goods: pass --cogs-pct or --landed (run {COGS_SKILL} on the best seller)"
        return waterfall(rev, units, referral, fba,
                         f"each listing's FBA fee (Keepa pick-and-pack) x its units; {len(known)}/{len(rows)} listings had a fee, "
                         "the rest at the same rate", None, tier, basis, None,
                         f"{len(rows)} badged listings, badge {'low' if key == 'lo' else 'high'} end x today's price",
                         "each listing's referral % (Keepa), 15% where missing", cogs_total=cogs)

    floor = month("lo")
    hist = series(prods)
    rows_h, ttm = series_profit(hist, floor["marginPct"])
    out({"mode": "keepa", "what": "brand", "brand": name, "month": datetime.now(timezone.utc).strftime("%Y-%m"),
         "badgedListings": found, "pricedListings": len(rows), "capped": bool(found and found > n),
         "floor": floor, "high": month("hi"), "verdict": verdict(floor["marginPct"]),
         "history": rows_h, "ttm": ttm, "method": PNL_NOTE + " Brand totals cover the listings priced here; capped=true means more exist.",
         "next": [x for x in (f"run {ADSPEND_SKILL} on the brand and re-run with --ads-band" if "Advertising" in floor["missing"] else None,
                              f"run {COGS_SKILL} on the best seller, or pass --cogs-pct" if "Cost of goods (landed)" in floor["missing"] else None) if x],
         "retrievedAt": retrieved(), "source": "Keepa", **k.meta()})


def cmd_pnl():
    if arg("--brand"):
        pnl_brand()
    pnl_product()


def cmd_api():
    if need_mode() != "whm":
        out({"error": "wrong_mode", "mode": mode(), "message": "api runs in WHM mode (WHM_API_KEY)"}, 2)
    out({"mode": "whm", **whm_get(positional())[1]})


FLAGS_WITH_VALUE.update({
    "--brand", "--max", "--price", "--units", "--fba-fee", "--referral-pct", "--landed", "--landed-tier", "--unit-cost",
    "--unit-basis", "--cogs-pct", "--freight-per-unit", "--duty-pct", "--placement", "--dest-coast", "--ads-band",
    "--ads-monthly", "--ads-pct", "--ads-tier", "--returns-pct", "--storage-monthly", "--storage-per-unit"})


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    usage_ping(cmd)
    if cmd == "mode":
        md = mode()
        out({"mode": md, "keys": {"WHM_API_KEY": has("WHM_API_KEY"), "KEEPA_API_KEY": has("KEEPA_API_KEY")},
             **({} if md != "none" else NO_KEYS), "skill": SKILL, "version": VERSION})
    {"pnl": cmd_pnl, "api": cmd_api}.get(cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
