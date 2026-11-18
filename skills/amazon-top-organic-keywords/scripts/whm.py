#!/usr/bin/env python3
"""WaitHowMuch skills data helper: one WHM API key, or your own provider keys.

Base: the shared whm.py (product / brand / niche on Keepa). This copy adds the
keyword commands used by amazon-top-organic-keywords and amazon-adspend-estimator.
Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key
(Keepa takes its key in the query string, so no URL is ever printed).

Mode, decided per run from the environment:
  1. WHM_API_KEY set   -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
                          (keyword commands: add --direct to skip it and use your own keys)
  2. your own keys     -> Keepa (KEEPA_API_KEY), Jungle Scout (JUNGLESCOUT_API_KEY, "<key name>:<key>"),
                          DataForSEO (DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD), optional Amazon Ads
                          (AMAZON_ADS_CLIENT_ID, _CLIENT_SECRET, _REFRESH_TOKEN, _PROFILE_ID)
  3. neither           -> {"error": "no_keys", ...}, exit 2

Commands:
  mode                         which mode this run would use (no provider call)
  product <ASIN|amazon.com URL>  monthly units/revenue range, price, fees    (Keepa: 1 token)
  api </v1/path?query>         GET a WaitHowMuch API route (WHM mode only)
  brand <name> [--seller ID] [--max N]   catalogue revenue of any brand   (needs KEEPA_API_KEY: ~11 + N tokens)
  niche "<keywords>" [--max N]           top-selling brands for a keyword (needs KEEPA_API_KEY: ~11 + N tokens)
  keywords <ASIN|URL> [--limit 25] [--max-rank 60] [--pages 3] [--source js|dfs] [--direct]
        top organic keywords: volume, organic rank, sponsored rank, bid
        (Jungle Scout: 1 request per 100 keywords listed; DataForSEO: ~$0.012 + $0.00012/keyword)
  adspend <ASIN|URL|brand> [--brand "as Jungle Scout spells it"] [--asins A,B] [--keywords 25]
          [--max-requests 40] [--margin-pct N] [--revenue USD] [--direct]
        modelled monthly ad-spend band (Jungle Scout: ~3 + one request per keyword read;
        DataForSEO only: the ad footprint, no dollar figure)

Exit codes: 0 ok, 1 upstream/API error, 2 no keys / wrong mode / route not live, 3 not enough tokens or requests, 4 bad input.
"""
import json
import math
import os
import re
import sys
import time
import base64
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

COMMANDS = {"adspend", "api", "brand", "keywords", "mode", "niche", "product"}
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


BOOL_FLAGS = {"--direct"}


def positional():
    skip, res = False, []
    for a in sys.argv[2:]:
        if skip:
            skip = False
            continue
        if a.startswith("--"):
            skip = a not in BOOL_FLAGS
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


# ─── Keyword providers (amazon-top-organic-keywords, amazon-adspend-estimator) ──
#
# The method is WaitHowMuch research's amazon-adspend-spy, cut to what runs from
# one script with no browser: Jungle Scout keywords_by_asin + share_of_voice,
# Amazon's own suggested bids when the user has Ads API keys, Keepa for the
# revenue denominator. Every spend figure is MODELLED, never measured.

JS_API = "https://developer.junglescout.com/api"
DFS_API = "https://api.dataforseo.com/v3"
ADS_HOSTS = {"NA": "https://advertising-api.amazon.com", "EU": "https://advertising-api-eu.amazon.com",
             "FE": "https://advertising-api-fe.amazon.com"}
ADS_VARS = ("AMAZON_ADS_CLIENT_ID", "AMAZON_ADS_CLIENT_SECRET", "AMAZON_ADS_REFRESH_TOKEN", "AMAZON_ADS_PROFILE_ID")
# Proposed WaitHowMuch routes (DataForSEO-derived keyword demand); the exact paths are this
# skill's proposal, not built.
ROUTE_KEYWORDS = "GET /v1/tools/top-keywords?asin="
ROUTE_ADSPEND = "GET /v1/tools/ad-spend?asin=|brand="
# FSCTR band borrowed when too few sponsored-dominant rows (adspend-spy §5a: organic median halved).
FSCTR_BORROWED = {"low": 0.018, "central": 0.03, "high": 0.045}
SHARE_BAND = 0.05  # adspend-spy §1: only brands holding >=5% share calibrate FSCTR


def env(k):
    return os.environ.get(k, "").strip()


def providers():
    return {"junglescout": bool(env("JUNGLESCOUT_API_KEY")),
            "dataforseo": bool(env("DATAFORSEO_LOGIN") and env("DATAFORSEO_PASSWORD")),
            "keepa": bool(env("KEEPA_API_KEY")),
            "amazonAds": all(env(k) for k in ADS_VARS)}


NO_KEYS_KW = {
    "error": "no_keys",
    "message": "Set ONE of: WHM_API_KEY (a WaitHowMuch API key) or your own provider keys: "
               "JUNGLESCOUT_API_KEY (Jungle Scout API add-on, \"<key name>:<key>\"; needed for the ad-spend dollar band) "
               "or DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD (pay-as-you-go, keywords and ad footprint only). "
               "Optional: KEEPA_API_KEY (revenue, brand ASINs), AMAZON_ADS_CLIENT_ID/_CLIENT_SECRET/_REFRESH_TOKEN/_PROFILE_ID "
               "(Amazon's own suggested bids). https://github.com/ggballas/waithowmuch-skills#data-providers",
}


KW_SKILLS = ("amazon-top-organic-keywords", "amazon-adspend-estimator")


def keyword_mode():
    """For the mode command: what the keyword commands would use (no provider call)."""
    if SKILL not in KW_SKILLS:
        return None
    p = providers()
    if env("WHM_API_KEY"):
        return "whm"
    return "junglescout" if p["junglescout"] else "dataforseo" if p["dataforseo"] else "none"


def kw_mode(direct_ok):
    """WHM first unless --direct; then the first own provider in direct_ok."""
    p = providers()
    if env("WHM_API_KEY") and "--direct" not in sys.argv:
        return "whm"
    for name in direct_ok:
        if p[name]:
            return name
    if env("WHM_API_KEY"):
        out({**NO_KEYS_KW, "error": "no_own_keys", "message": "--direct needs your own provider keys. " + NO_KEYS_KW["message"]}, 2)
    out(NO_KEYS_KW, 2)


def not_live(route, what):
    p = providers()
    own = [k for k in ("junglescout", "dataforseo") if p[k]]
    out({"mode": "whm", "error": "whm_route_not_live", "proposedRoute": route,
         "message": f"WaitHowMuch has no live API route for {what} yet (proposed: {route}). "
                    "It only has researched case studies, and this one isn't among them.",
         "ownKeysPresent": own,
         "hint": ("Re-run with --direct to use your own " + " / ".join(own) + " key.") if own else
                 "Option A works today: set JUNGLESCOUT_API_KEY or DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD."}, 2)


def whm_case_study(q, accept):
    """A researched WaitHowMuch business matching q, with its modelled ad reading, or None."""
    hits = whm_get("/v1/lookup?" + urllib.parse.urlencode({"q": q})).get("results") or []
    hit = next((h for h in hits if h.get("matchedOn") in accept), None)
    if not hit:
        return None
    slug = hit["business"]["slug"]
    reading = whm_get(f"/v1/businesses/{urllib.parse.quote(slug)}/ads").get("reading")
    if not reading:
        return None
    return {"business": hit["business"]["name"], "slug": slug, "matchedOn": hit["matchedOn"], "match": hit.get("match"),
            "url": f"https://waithowmuch.com/business/{slug}/?utm_source=whm-skills&utm_medium=skill"
                   f"&utm_campaign=whm-skills&utm_content={SKILL}", "reading": reading}


class JungleScout:
    """Metered: every request counts against the user's monthly API add-on, $0.05 past it."""

    def __init__(self, budget=10_000):
        self.headers = {"Authorization": env("JUNGLESCOUT_API_KEY"), "X-API-Type": "junglescout",
                        "Accept": "application/vnd.junglescout.v1+json", "Content-Type": "application/vnd.api+json"}
        self.requests, self.budget = 0, budget

    def left(self):
        return self.budget - self.requests

    def call(self, url, body=None):
        data = json.dumps(body).encode() if body is not None else None
        for t in range(5):
            status, res = _fetch(url, self.headers, data)
            if status == 429:
                time.sleep(3 * (t + 1))
                continue
            self.requests += 1
            if status == 401:
                out({"mode": "junglescout", "error": "js_key_rejected", "status": status,
                     "message": "Jungle Scout refused the key. JUNGLESCOUT_API_KEY must be \"<key name>:<key>\"."}, 1)
            if status == 403:
                out({"mode": "junglescout", "error": "js_forbidden", "status": status, "requests": self.requests,
                     "message": "Jungle Scout returned 403: no API add-on, a marketplace the key isn't linked to, "
                                "or the monthly overage cap was hit."}, 1)
            if status == 422:
                return None
            if status != 200:
                out({"mode": "junglescout", "error": "js_error", "status": status, "requests": self.requests}, 1)
            return res
        out({"mode": "junglescout", "error": "js_rate_limited", "requests": self.requests}, 3)

    def keywords_by_asin(self, asins, pages):
        url = f"{JS_API}/keywords/keywords_by_asin_query?marketplace=us&sort=-monthly_search_volume_exact&page%5Bsize%5D=100"
        rows, total = [], None
        for _ in range(pages):
            if not url or self.left() <= 0:
                break
            j = self.call(url, {"data": {"type": "keywords_by_asin_query",
                                         "attributes": {"asins": asins[:10], "include_variants": True}}}) or {}
            rows += [d["attributes"] for d in j.get("data") or []]
            total = (j.get("meta") or {}).get("total_items", total)
            url = (j.get("links") or {}).get("next")
        return rows, total, bool(url)

    def share_of_voice(self, keyword):
        j = self.call(f"{JS_API}/share_of_voice?" + urllib.parse.urlencode({"keyword": keyword, "marketplace": "us"}))
        return ((j or {}).get("data") or {}).get("attributes")


class DataForSEO:
    """Pay as you go: Labs Amazon endpoints cost ~$0.012 a task + $0.00012 an item returned."""

    def __init__(self):
        tok = base64.b64encode(f"{env('DATAFORSEO_LOGIN')}:{env('DATAFORSEO_PASSWORD')}".encode()).decode()
        self.headers = {"Authorization": "Basic " + tok, "Content-Type": "application/json"}
        self.cost = 0.0

    def call(self, path, task):
        status, res = _fetch(f"{DFS_API}/{path}", self.headers, json.dumps([task]).encode())
        if status in (401, 403):
            out({"mode": "dataforseo", "error": "dfs_key_rejected", "status": status,
                 "message": "DataForSEO refused DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD (use the API password, not the site one)."}, 1)
        self.cost += res.get("cost") or 0
        t = (res.get("tasks") or [{}])[0]
        if status != 200 or t.get("status_code") != 20000:
            out({"mode": "dataforseo", "error": "dfs_error", "status": status,
                 "code": t.get("status_code") or res.get("status_code"),
                 "message": t.get("status_message") or res.get("status_message"), "costUsd": round(self.cost, 4)}, 1)
        return (t.get("result") or [{}])[0] or {}

    def ranked(self, asin, limit, filters):
        return self.call("dataforseo_labs/amazon/ranked_keywords/live", {
            "asin": asin, "location_code": 2840, "language_code": "en", "limit": min(max(limit, 1), 1000),
            "filters": filters, "order_by": ["keyword_data.keyword_info.search_volume,desc"]})


def amazon_bids(asins, keywords):
    """Amazon's own suggested EXACT bids for arbitrary keywords against these ASINs (the user's Ads API app).
    bidInfo[].bid is CENTS. Returns ({keyword: usd}, error or None)."""
    if not providers()["amazonAds"] or not keywords:
        return {}, None
    host = ADS_HOSTS.get(env("AMAZON_ADS_REGION").upper() or "NA", ADS_HOSTS["NA"])
    st, tok = _fetch("https://api.amazon.com/auth/o2/token", {"Content-Type": "application/x-www-form-urlencoded"},
                     urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": env("AMAZON_ADS_REFRESH_TOKEN"),
                                             "client_id": env("AMAZON_ADS_CLIENT_ID"),
                                             "client_secret": env("AMAZON_ADS_CLIENT_SECRET")}).encode())
    if not tok.get("access_token"):
        return {}, f"Amazon Ads token refused ({tok.get('error') or st})"
    mt = "application/vnd.spkeywordsrecommendation.v5+json"
    h = {"Authorization": "Bearer " + tok["access_token"], "Amazon-Advertising-API-ClientId": env("AMAZON_ADS_CLIENT_ID"),
         "Amazon-Advertising-API-Scope": env("AMAZON_ADS_PROFILE_ID"), "Accept": mt, "Content-Type": mt}
    bids, want = {}, {k.lower() for k in keywords}
    for i in range(0, len(keywords), 100):
        body = {"recommendationType": "KEYWORDS_FOR_ASINS", "asins": asins[:2], "locale": "en_US",
                "targets": [{"keyword": k, "matchType": "EXACT"} for k in keywords[i:i + 100]]}
        res, st = None, 0
        for t in range(6):  # the Ads API throttles dynamically; a 429 first is normal
            st, res = _fetch(f"{host}/sp/targets/keywords/recommendations", h, json.dumps(body).encode())
            if st != 429:
                break
            time.sleep(4 * (t + 1))
        if st != 200:
            return bids, f"Amazon Ads bid recommendations returned {st}"
        for x in res.get("keywordTargetList") or []:
            k = (x.get("keyword") or "").lower()
            ex = next((b for b in x.get("bidInfo") or [] if b.get("matchType") == "EXACT" and b.get("bid") is not None), None)
            if ex and k in want:
                bids[k] = ex["bid"] / 100
    return bids, None


def median(xs):
    s = sorted(xs)
    m = len(s) // 2
    return None if not s else s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def int_arg(flag, default, lo, hi):
    try:
        return max(lo, min(int(arg(flag, str(default))), hi))
    except ValueError:
        out({"error": "bad_input", "message": f"{flag} takes a number"}, 4)


def js_rank(a):
    """Best organic rank of the ASIN or a variation of it, and which one held it."""
    o, v = a.get("organic_rank"), a.get("variation_lowest_organic_rank")
    if o and (not v or o <= v):
        return o, "asin"
    return (v, "variation") if v else (None, None)


def js_row(a):
    rank, held = js_rank(a)
    return {"keyword": a.get("name"), "searchVolume": a.get("monthly_search_volume_exact"),
            "searchVolumeBroad": a.get("monthly_search_volume_broad"), "organicRank": rank, "organicRankHeldBy": held,
            "sponsoredRank": a.get("sponsored_rank") or a.get("variation_lowest_sponsored_rank"),
            "ppcBidExact": a.get("ppc_bid_exact"), "ppcBidBroad": a.get("ppc_bid_broad"),
            "sponsoredBrandsBid": a.get("sp_brand_ad_bid"), "trendMonthlyPct": a.get("monthly_trend"),
            "trendQuarterlyPct": a.get("quarterly_trend"), "relevancyScore": a.get("relevancy_score"),
            "easeOfRankingScore": a.get("ease_of_ranking_score"), "sponsoredProductCount": a.get("sponsored_product_count"),
            "category": a.get("dominant_category"), "updatedAt": (a.get("updated_at") or "")[:10] or None}


def dfs_rows(items):
    """One row per keyword: organic rank_group from amazon_serp, sponsored from amazon_paid."""
    by = {}
    for it in items or []:
        kd, el = it.get("keyword_data") or {}, (it.get("ranked_serp_element") or {})
        s = el.get("serp_item") or {}
        k = kd.get("keyword")
        r = by.setdefault(k, {"keyword": k, "searchVolume": (kd.get("keyword_info") or {}).get("search_volume"),
                              "organicRank": None, "organicRankAbsolute": None, "sponsoredRank": None,
                              "seenAt": (el.get("last_updated_time") or "")[:10] or None})
        if s.get("type") == "amazon_paid":
            pos_ = s.get("rank_absolute") or s.get("rank_group")
            if pos_ and (r["sponsoredRank"] is None or pos_ < r["sponsoredRank"]):
                r["sponsoredRank"] = pos_
        elif s.get("rank_group"):
            if r["organicRank"] is None or s["rank_group"] < r["organicRank"]:
                r["organicRank"], r["organicRankAbsolute"] = s["rank_group"], s.get("rank_absolute")
    return list(by.values())


DFS_SCALE_NOTE = ("DataForSEO's Amazon search volumes run far below Amazon's scale (WaitHowMuch research: 19-43x under "
                  "Jungle Scout; 'mahjong set' 28,835 vs 587,812 on 2026-11-17). Use them to RANK keywords, not as counts.")


# ─── keywords ───────────────────────────────────────────────────────

def cmd_keywords():
    raw = positional()
    if not raw:
        out({"error": "invalid_asin", "reason": "empty"}, 4)
    limit, max_rank, pages = int_arg("--limit", 25, 1, 200), int_arg("--max-rank", 60, 1, 300), int_arg("--pages", 3, 1, 10)
    src = (arg("--source") or "").lower()
    order = {"js": ("junglescout",), "dfs": ("dataforseo",)}.get(src, ("junglescout", "dataforseo"))
    md = kw_mode(order)
    asin = parse_asin(raw) if md != "whm" else None
    if md == "whm":
        cs = whm_case_study(raw, ("asin",))
        if not cs:
            not_live(ROUTE_KEYWORDS, "an ASIN's organic keywords")
        r = cs["reading"]
        out({"mode": "whm", "asin": raw, "source": "waithowmuch_case_study", "business": cs["business"], "url": cs["url"],
             "month": r.get("month"), "scope": "brand: the best organic rank ANY of the brand's researched listings holds, not this ASIN alone",
             "keywords": [{"keyword": k["keyword"], "searchVolume": k["monthlySearches"], "organicRank": k["organicRank"],
                           "sponsoredRank": k["adPosition"], "bid": k["cpc"], "theirShareOfAdsPct": k["shareOfAdsPct"],
                           "modelledAdSpendMonthly": k["spendMonthly"]} for k in r.get("organicKeywords") or []][:limit],
             "method": "WaitHowMuch research (Jungle Scout keywords_by_asin, Amazon Ads suggested bids), snapshot month above"})
    if md == "junglescout":
        js = JungleScout()
        rows, total, more = js.keywords_by_asin([asin], pages)
        ranked = [js_row(a) for a in rows]
        ranked = [r for r in ranked if r["organicRank"] and r["organicRank"] <= max_rank]
        ranked.sort(key=lambda r: -(r["searchVolume"] or 0))
        out({"mode": "junglescout", "asin": asin, "url": f"https://www.amazon.com/dp/{asin}",
             "keywordsListed": total, "keywordsRead": len(rows), "rankedWithinMaxRank": len(ranked), "maxRank": max_rank,
             "truncated": more, "keywords": ranked[:limit],
             "method": "Jungle Scout keywords_by_asin (variants included), read biggest search volume first; kept where the "
                       f"ASIN or a variation ranks organically in the top {max_rank}; sorted by exact monthly search volume. "
                       "Search volume and bids are Jungle Scout's estimates; ranks are their latest crawl.",
             "source": "Jungle Scout", "jungleScoutRequests": js.requests,
             **({"note": f"Only the {len(rows)} biggest of {total} keywords were read (--pages {pages}); "
                         "smaller ranked keywords may be missing."} if more else {})})
    d = DataForSEO()
    res = d.ranked(asin, min(limit * 2, 1000), [["ranked_serp_element.serp_item.rank_group", "<=", max_rank]])
    rows = dfs_rows(res.get("items"))
    ranked = sorted([r for r in rows if r["organicRank"]], key=lambda r: -(r["searchVolume"] or 0))
    out({"mode": "dataforseo", "asin": asin, "url": f"https://www.amazon.com/dp/{asin}",
         "keywordsListed": res.get("total_count"), "maxRank": max_rank, "keywords": ranked[:limit],
         "sponsoredSeenOn": [r["keyword"] for r in rows if r["sponsoredRank"]],
         "method": f"DataForSEO Labs Amazon ranked_keywords, rank_group <= {max_rank}, biggest search volume first. "
                   "organicRank = position among organic results; ranks come from DataForSEO's own SERP crawls (date in seenAt).",
         "volumeWarning": DFS_SCALE_NOTE, "source": "DataForSEO", "costUsd": round(d.cost, 4)})


# ─── adspend ────────────────────────────────────────────────────────

def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def brand_matcher(brand):
    b = norm(brand)
    return lambda name: bool(b) and (norm(name) == b or norm(name).startswith(b + " ") or b.startswith(norm(name) + " "))


def brand_terms(brand):
    b = norm(brand)
    first = b.split(" ")[0] if b else ""
    return [t for t in {b, first} if len(t) >= 4]


def keepa_context(k, raw, asins):
    """(asins, brand, title, monthly revenue range in USD) from Keepa, for an ASIN or a brand name."""
    if asins:
        prods = products(k, asins[:10], history=False)
    elif ASIN_RE.match(raw.strip().upper()) or "amazon." in raw:
        prods = products(k, [parse_asin(raw)], history=False)
    else:
        k.ensure(21)
        found, _ = finder(k, {"brand": [raw], "monthlySold_gte": 1, "sort": [["monthlySold", "desc"]], "perPage": 50, "page": 0})
        prods = products(k, found[:10], history=False)
    rows = [row(p) for p in prods]
    t = total(rows)
    return ([r["asin"] for r in rows], (rows[0]["brand"] if rows else None), (rows[0]["title"] if rows else None),
            {"low": t["revenueLowCents"] / 100, "high": t["revenueHighCents"] / 100} if t["revenueLowCents"] else None)


def cmd_adspend():
    raw = positional()
    if not raw and not arg("--asins"):
        out({"error": "bad_input", "message": "give an ASIN, an amazon.com URL or a brand name"}, 4)
    md = kw_mode(("junglescout", "dataforseo"))
    if md == "whm":
        cs = whm_case_study(raw or arg("--asins").split(",")[0], ("asin", "name", "domain", "handle"))
        if not cs:
            not_live(ROUTE_ADSPEND, "modelled ad spend of an unresearched product or brand")
        r = cs["reading"]
        out({"mode": "whm", "query": raw, "source": "waithowmuch_case_study", "business": cs["business"], "url": cs["url"],
             "matchedOn": cs["matchedOn"], "tier": "modelled", "month": r.get("month"), "strategy": r.get("strategy"),
             "spendMonthlyUsd": r.get("spendMonthly"), "adRatePctOfRevenue": r.get("ratePct"),
             "paidKeywords": (r.get("paidKeywords") or [])[:25],
             "shakiestInput": "the click-through rate applied to their share of the ads (FSCTR)",
             "method": "WaitHowMuch research, amazon-adspend-spy: keywords x search volume x their sponsored share x "
                       "click-through x Amazon's suggested bid; a keyword floor, labelled modelled"})

    asins = [a.strip().upper() for a in (arg("--asins") or "").split(",") if a.strip()]
    for a in asins:
        if not ASIN_RE.match(a):
            out({"error": "invalid_asin", "reason": "no_asin", "asin": a}, 4)
    title, revenue, kmeta, kb = None, None, None, None
    is_asin = bool(raw) and bool(ASIN_RE.match(raw.strip().upper()) or "amazon." in raw.lower())
    if providers()["keepa"]:
        k = Keepa()
        ka, kb, title, revenue = keepa_context(k, raw, asins)
        asins, kmeta = asins or ka, k.meta()
    elif is_asin and not asins:
        asins = [parse_asin(raw)]
    brand = arg("--brand") or (raw if raw and not is_asin else None) or kb
    if not asins:
        out({"error": "needs_asins", "message": "A brand name needs KEEPA_API_KEY to find its listings, or pass "
                                                "--asins B0...,B0... (up to 10, best sellers first)."}, 4)
    if revenue is None and arg("--revenue"):
        try:
            v = float(arg("--revenue"))
            revenue = {"low": v, "high": v}
        except ValueError:
            out({"error": "bad_input", "message": "--revenue takes monthly USD"}, 4)

    if md == "dataforseo":
        return adspend_footprint(asins, brand, title, revenue, kmeta)
    if not brand:
        out({"error": "brand_unknown", "message": "Pass --brand as Jungle Scout spells it (or set KEEPA_API_KEY): "
                                                  "share of voice is per brand, so the model must know whose ads to count."}, 4)
    adspend_model(asins, brand, title, revenue, kmeta)


def adspend_footprint(asins, brand, title, revenue, kmeta):
    d = DataForSEO()
    seen = {}
    for a in asins[:3]:
        res = d.ranked(a, 100, [["ranked_serp_element.serp_item.type", "=", "amazon_paid"]])
        for r in dfs_rows(res.get("items")):
            if r["sponsoredRank"] and (r["keyword"] not in seen or r["sponsoredRank"] < seen[r["keyword"]]["sponsoredRank"]):
                seen[r["keyword"]] = {"keyword": r["keyword"], "searchVolumeRelative": r["searchVolume"],
                                      "sponsoredRank": r["sponsoredRank"], "asin": a, "seenAt": r["seenAt"]}
    rows = sorted(seen.values(), key=lambda r: -(r["searchVolumeRelative"] or 0))
    terms = brand_terms(brand)
    out({"mode": "dataforseo", "asins": asins, "brand": brand, "title": title, "tier": "measured footprint, no spend",
         "spendMonthlyUsd": None,
         "why": "No dollar band without Jungle Scout: the model needs each brand's share of the sponsored results and "
                "search volume on Amazon's scale, and DataForSEO has neither. Set JUNGLESCOUT_API_KEY for the band.",
         "adKeywordsSeen": len(rows), "brandTermAdKeywords": sum(1 for r in rows if any(t in r["keyword"] for t in terms)),
         "keywords": rows[:50], "volumeWarning": DFS_SCALE_NOTE, "revenueMonthlyUsd": revenue,
         "source": "DataForSEO Labs Amazon ranked_keywords (amazon_paid)", "costUsd": round(d.cost, 4),
         **({"keepa": kmeta} if kmeta else {})})


def fsctr_band(sov, is_brand):
    """adspend-spy §1/§5a: clicks per unit of visibility share, read off top_asins of OTHER single-product brands
    holding >=5% share; >=2 sponsored-dominant rows measure it, else the borrowed 1.8/3/4.5% band."""
    rows = []
    for kw, a in sov.items():
        vol = a.get("estimated_30_day_search_volume")
        brands = {b["brand"]: b for b in a.get("brands") or []}
        for t in a.get("top_asins") or []:
            b = brands.get(t.get("brand"))
            if not b or not vol or is_brand(t.get("brand")) or (b.get("combined_weighted_sov") or 0) < SHARE_BAND \
                    or b.get("combined_products") != 1:
                continue
            rows.append({"keyword": kw, "brand": t["brand"], "fsctr": round((t["clicks"] * 30 / 7) / (vol * b["combined_weighted_sov"]), 4),
                         "sponsoredDominant": (b.get("sponsored_weighted_sov") or 0) > (b.get("organic_weighted_sov") or 0)})
    spon = [r["fsctr"] for r in rows if r["sponsoredDominant"]]
    if len(spon) >= 2:
        c = median(spon)
        return {"low": min(spon), "central": c, "high": max(c, median([r["fsctr"] for r in rows])), "measured": True,
                "basis": f"measured: {len(spon)} sponsored-dominant rows in Jungle Scout's panel (low = min, central = median)",
                "rows": rows}
    return {**FSCTR_BORROWED, "measured": False,
            "basis": f"BORROWED 1.8/3/4.5% band (WaitHowMuch research, organic click rate halved): only {len(spon)} "
                     f"sponsored-dominant row(s) here; {len(rows) - len(spon)} organic rows are not a substitute", "rows": rows}


def adspend_model(asins, brand, title, revenue, kmeta):
    n_kw, n_top = int_arg("--keywords", 25, 1, 150), int_arg("--top", 10, 0, 50)
    js = JungleScout(budget=int_arg("--max-requests", 40, 3, 400))
    raw_rows, total_listed, more = js.keywords_by_asin(asins, int_arg("--pages", 3, 1, 10))
    is_brand, terms = brand_matcher(brand), brand_terms(brand)
    is_term = lambda k: any(t in k.lower() for t in terms)  # noqa: E731

    kw = {}
    for a in raw_rows:  # merge the brand's ASINs: best rank any of them held ("competitor_*" = the query's other ASINs)
        e = kw.setdefault(a["name"], {"keyword": a["name"], "vol": a.get("monthly_search_volume_exact") or 0,
                                      "jsBid": a.get("ppc_bid_exact"), "o": [], "s": []})
        spon = {c["asin"]: c.get("sponsored_rank") for c in a.get("competitor_sponsored_rank") or []}
        for o, s in [(a.get("organic_rank"), a.get("sponsored_rank"))] + \
                    [(c.get("organic_rank"), spon.get(c["asin"])) for c in a.get("competitor_organic_rank") or []]:
            if o:
                e["o"].append(o)
            if s:
                e["s"].append(s)
    for e in kw.values():
        e["bestOrganic"], e["bestSponsored"] = min(e["o"], default=None), min(e["s"], default=None)
    allk = sorted(kw.values(), key=lambda e: -e["vol"])
    fits = lambda e: len(e["keyword"]) <= 50  # noqa: E731  (share_of_voice refuses longer)
    relevant = [e for e in allk if (e["bestOrganic"] and e["bestOrganic"] <= 60) or e["bestSponsored"]]
    top = [e for e in relevant if fits(e)][:n_top]
    with_ads = [e for e in allk if e["bestSponsored"] and fits(e)]
    prior = lambda e: e["vol"] * (e["jsBid"] or 1)  # noqa: E731
    chosen = {e["keyword"]: e for e in top}
    for e in [e for e in with_ads if is_term(e["keyword"])] + sorted(with_ads, key=lambda e: -prior(e)):
        if len(chosen) >= max(n_kw, len(top)):
            break
        chosen.setdefault(e["keyword"], e)
    chosen = list(chosen.values())

    sov, unread_budget = {}, []
    for e in chosen:
        if js.left() <= 0:
            unread_budget.append(e["keyword"])
            continue
        a = js.share_of_voice(e["keyword"])
        if a:
            sov[e["keyword"]] = a
    band = fsctr_band(sov, is_brand)
    bids, bid_err = amazon_bids(asins, list(sov))

    rows = []
    for e in chosen:
        a = sov.get(e["keyword"])
        if not a:
            continue
        vol = a.get("estimated_30_day_search_volume") or e["vol"]
        mine = [b for b in a.get("brands") or [] if is_brand(b["brand"])]
        sw = sum(b.get("sponsored_weighted_sov") or 0 for b in mine)
        amz = bids.get(e["keyword"].lower())
        bid = amz or a.get("exact_suggested_bid_median") or e["jsBid"]
        src = "amazon-ads" if amz else "jungle-scout-sov-median" if a.get("exact_suggested_bid_median") else \
            "jungle-scout-keyword" if e["jsBid"] else None
        observed = sum(t["clicks"] for t in a.get("top_asins") or [] if is_brand(t.get("brand"))) * 30 / 7
        r = {"keyword": e["keyword"], "searchVolume30d": vol, "brandTerm": is_term(e["keyword"]),
             "theirSponsoredShare": round(sw, 4), "theirOrganicShare": round(sum(b.get("organic_weighted_sov") or 0 for b in mine), 4),
             "bestOrganicRank": e["bestOrganic"], "bestSponsoredRank": e["bestSponsored"], "bid": bid, "bidSource": src,
             "topAdvertisers": [{"brand": b["brand"], "sponsoredShare": b["sponsored_weighted_sov"]} for b in
                                sorted(a.get("brands") or [], key=lambda b: -(b.get("sponsored_weighted_sov") or 0))[:3]
                                if b.get("sponsored_weighted_sov")],
             "theirClicksObservedMonthly": round(observed, 1) or None}
        for case in ("low", "central", "high"):
            clicks = band[case] * vol * sw
            if observed:
                clicks = min(clicks, observed)  # paid clicks can't exceed all the clicks the panel saw them take
            r[f"spend_{case}"] = None if bid is None else round(clicks * bid, 2)
        rows.append(r)

    tot = {c: round(sum(r[f"spend_{c}"] or 0 for r in rows)) for c in ("low", "central", "high")}
    read_ads = [e for e in with_ads if e["keyword"] in sov]
    unread_ads = [e for e in with_ads if e["keyword"] not in sov]
    pr_read, pr_unread = sum(prior(e) for e in read_ads), sum(prior(e) for e in unread_ads)
    scale = 1 + (pr_unread / pr_read) if pr_read else None
    extrap = {c: round(v * scale) for c, v in tot.items()} if scale and unread_ads else None

    brand_spend = sum(r["spend_central"] or 0 for r in rows if r["brandTerm"])
    share = brand_spend / tot["central"] if tot["central"] else 0
    generic = [r for r in rows if r["keyword"] in {e["keyword"] for e in top} and not r["brandTerm"]]
    bought = [r for r in generic if r["theirSponsoredShare"] >= 0.05]
    ad_rows = [r for r in rows if r["theirSponsoredShare"] > 0]
    label = ("No Amazon ads seen" if not ad_rows and not with_ads else
             "Category acquisition" if generic and len(bought) >= len(generic) / 3 else
             "Brand defence" if share >= 0.5 and not bought else
             "Brand defence plus a few generic searches" if share >= 0.5 else "Long-tail phrases")
    no_bid = [r["keyword"] for r in rows if r["bid"] is None and r["theirSponsoredShare"] > 0]
    gaps = ["Keyword floor: auto campaigns, product targeting, Sponsored Brands and Display are invisible to this model.",
            "A suggested bid is not a billed CPC; cleared auctions usually run 60-85% of the bid, so spend leans high per click."]
    if unread_ads:
        gaps.append(f"{len(unread_ads)} smaller keywords they show ads on were not read (budget --keywords {n_kw}); "
                    "'withUnreadKeywords' scales the band by their searches x bid, a rough extrapolation.")
    if more:
        gaps.append(f"Jungle Scout lists {total_listed} keywords for these ASINs; only the {len(raw_rows)} biggest were read.")
    if unread_budget:
        gaps.append(f"--max-requests ran out: {len(unread_budget)} chosen keywords not read.")
    if no_bid:
        gaps.append(f"No bid anywhere for {len(no_bid)} keyword(s) they advertise on, left out: {', '.join(no_bid[:10])}")
    if bid_err:
        gaps.append(bid_err + "; bids fell back to Jungle Scout's (they ran ~2x Amazon's on one tested brand).")
    elif not providers()["amazonAds"]:
        gaps.append("No Amazon Ads keys: bids are Jungle Scout's estimates (ran ~2x Amazon's own suggestion on one tested brand).")
    if not any(is_brand(b["brand"]) for a in sov.values() for b in a.get("brands") or []):
        gaps.append(f"'{brand}' never appeared in Jungle Scout's share of voice: check the spelling with --brand "
                    "(it must match how Jungle Scout names the brand), or they truly show no ads here.")

    rate = None
    if revenue and revenue.get("low"):
        mid = (revenue["low"] + revenue["high"]) / 2
        rate = {c: round(v / mid * 100, 2) for c, v in tot.items()}
    margin = arg("--margin-pct")
    ceiling = None
    if margin:
        try:
            m = float(margin)
            ceiling = {"marginBeforeAdsPct": m, "marginAfterAdsPct": {"0": m, "12": round(m - 12, 1), "20": round(m - 20, 1)},
                       "binds": m - 20 < 5,
                       "note": "the margin caps what they can pay for ads; a product that can't bear 20% is a finding, not an error"}
        except ValueError:
            out({"error": "bad_input", "message": "--margin-pct takes a number"}, 4)

    rows.sort(key=lambda r: -(r["spend_central"] or 0))
    out({"mode": "junglescout", "asins": asins, "brand": brand, "title": title, "tier": "modelled",
         "spendMonthlyUsd": tot, **({"withUnreadKeywords": extrap} if extrap else {}),
         "adRatePctOfRevenue": rate, "revenueMonthlyUsd": revenue, "marginCeiling": ceiling,
         "strategy": {"label": label, "brandSpendShare": round(share, 3), "adKeywordsSeen": len(with_ads),
                      "topGenericChecked": len(generic), "topGenericBought": [r["keyword"] for r in bought]},
         "shakiestInput": {"input": "click-through on their sponsored share (FSCTR)", "value": {c: band[c] for c in ("low", "central", "high")},
                           "measured": band["measured"], "basis": band["basis"],
                           "why": "Nobody publishes paid CTR. It is read off Jungle Scout's panel of mostly ORGANIC winners and "
                                  "applied to a SPONSORED share, which likely overstates paid clicks by 1-3x."},
         "formula": "per keyword: FSCTR x 30-day searches x their sponsored share = paid clicks (capped at the clicks the panel "
                    "saw them take); x bid = spend. Summed over keywords read.",
         "gaps": gaps, "keywords": rows,
         "fsctrRows": band["rows"][:20],
         "source": "Jungle Scout keywords_by_asin + share_of_voice" + (", Amazon Ads suggested bids" if bids else "") +
                   (", Keepa" if kmeta else ""),
         "jungleScoutRequests": js.requests, **({"keepa": kmeta} if kmeta else {})})


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    usage_ping(cmd)
    if cmd == "mode":
        md = mode()
        out({"mode": md, "keys": {"WHM_API_KEY": bool(os.environ.get("WHM_API_KEY", "").strip()),
                                  "KEEPA_API_KEY": bool(os.environ.get("KEEPA_API_KEY", "").strip())},
             "keywordProviders": providers(),
             **({} if md != "none" or SKILL in KW_SKILLS else NO_KEYS),
             **({"keywordMode": kmd} if (kmd := keyword_mode()) else {}),
             **(NO_KEYS_KW if SKILL in KW_SKILLS and kmd == "none" else {}), "skill": SKILL, "version": VERSION})
    {"product": cmd_product, "api": cmd_api, "brand": cmd_brand, "niche": cmd_niche,
     "keywords": cmd_keywords, "adspend": cmd_adspend}.get(
        cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
