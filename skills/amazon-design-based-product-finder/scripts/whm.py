#!/usr/bin/env python3
"""WaitHowMuch skills data helper, amazon-design-based-product-finder: new, traction-proven Amazon
products whose value is the design ("made once, sold many times"), and the sellers behind them.

Shared core (mode, HTTP, Keepa client, badge method) is the same in every skill's scripts/whm.py.
Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key
(Keepa takes its key in the query string, so no URL is ever printed).

Mode, decided per run from the environment:
  1. WHM_API_KEY set   -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
  2. KEEPA_API_KEY set -> Keepa API directly (your tokens)
  3. neither           -> {"error": "no_keys", ...}, exit 2
No WHM route serves this skill yet: with only WHM_API_KEY set, scan/sellers return
{"error": "whm_route_not_live"}. With KEEPA_API_KEY set they run on it.

Commands:
  mode                      which mode this run would use (no provider call)
  categories                the built-in categories, niches, keywords and tags (no provider call)
  scan [--category "<label>"]... [--niche kitchen]... [--keywords "a,b" | --keywords default]
       [--per-query 20] [--months 24] [--min-units 100] [--max-units 5000] [--min-price 13] [--min-variations N]
                            Product Finder per query (11 tokens) + 1 token per product fetched.
                            No query flags = the 3 default design-dense Toys categories (~93 tokens).
  sellers <ASIN,ASIN,...|rows.json> [--max 30]
                            buy-box seller, business, address, country, catalogue signal: ~4 tokens per ASIN.
                            Drops sellers with a China or Hong Kong address.
  shortlist <tagged.json>   offline: keep design tags, merge by seller, rank (no provider call, no tokens)

Exit codes: 0 ok, 1 upstream/API error, 2 no keys / route not live, 3 not enough Keepa tokens, 4 bad input.
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

COMMANDS = {"categories", "mode", "scan", "sellers", "shortlist"}
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
    "message": "Set ONE of: WHM_API_KEY (Option B: one WaitHowMuch API key; this skill's WHM route is not live yet) "
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




# ─── Badge + price (same method as the other skills) ─────────────────

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


# ─── Where design-based products live ─────────────────────────────────

# Broad searches. Toys & Games is split: a design-led card or board game lives under Games &
# Accessories. Left out on purpose: Grocery, Health & Household, Beauty (food and supplements are
# out of scope for now), Books, Clothing.
CATEGORIES = {
    "Toys: Games & Accessories": {"categories_include": [166220011]},
    "Toys: Puzzles": {"categories_include": [166359011]},
    "Toys: Novelty & Gag": {"categories_include": [166027011]},
    "Toys: Learning & Education": {"categories_include": [166269011]},
    "Toys: App & Remote Controlled": {"categories_include": [6925830011]},
    "Toys: Arts & Crafts": {"categories_include": [166057011]},
    "Toys: Building": {"categories_include": [166092011]},
    "Home & Kitchen": {"rootCategory": [1055398]},
    "Office Products": {"rootCategory": [1064954]},
    "Sports & Outdoors": {"rootCategory": [3375251]},
    "Pet Supplies": {"rootCategory": [2619533011]},
    "Baby Products": {"rootCategory": [165796011]},
    "Arts, Crafts & Sewing": {"rootCategory": [2617941011]},
    "Patio, Lawn & Garden": {"rootCategory": [2972638011]},
    "Musical Instruments": {"rootCategory": [11091801]},
    "Electronics": {"rootCategory": [172282]},
    "Tools & Home Improvement": {"rootCategory": [228013]},
}
DEFAULT_CATEGORIES = ["Toys: Games & Accessories", "Toys: Puzzles", "Toys: Novelty & Gag"]

# Niche leaves where the product IS the design (art, characters, themes), found from the case
# studies: e.g. Ototo (character kitchen gadgets).
NICHES = {
    "kitchen": {"Kitchen: Utensils & Gadgets": {"categories_include": [289754]}},
}

# Title keywords for the sweep: one Product Finder query each, any category.
KEYWORDS = [
    "dice tray", "dnd dice", "tarot", "board game", "party game",
    "spoon rest", "kitchen gadget", "silicone kitchen", "egg cooker", "garlic press", "cookie cutter",
    "desk mat", "desk accessory", "enamel pin", "sticker book", "planner", "bookmark", "book sleeve",
    "cat shaped", "pet bowl", "dog toy", "night light", "wall hook", "coaster", "mouse pad",
]

# Pre-tag hints from the title only. They help the agent read faster; they are NOT the judgment.
DESIGN_HINTS = re.compile(
    r"card game|board game|party game|game for|puzzle|jigsaw|illustrat|artwork|art print|design|shaped|"
    r"character|themed|novelty|funny|gag|cute|kawaii|tarot|oracle|sticker|enamel pin|"
    r"coloring|activity book|plush|figure|collectible|limited edition|original art|app|bluetooth|smart", re.I)
COMMODITY_HINTS = re.compile(
    r"mahjong (mat|rack)|card shuffler|shuffler|chess set|playing cards.*(bulk|pack of \d{2,})|prize wheel|"
    r"squish|replacement|refill|pack of \d{2,}|bulk|generic|organizer|storage bin|cable|charger|adapter|"
    r"protein|supplement|vitamin|gumm|snack|coffee|tea\b", re.I)

# Registered-agent mills: a US address that says nothing about who runs it.
AGENT_RE = re.compile(
    r"30 N(orth)? Gould|1309 Coffeen|1603 Capitol|2106 House Ave|1908 Thomes|1121 D? ?Lincolnway|"
    r"5830 E(ast)? 2nd|312 w 2nd|212 E 22nd|8 The Green|131 Continental|251 Little Falls|"
    r"1000 N(orth)? West St|1401 Pennsylvania Ave|24A Trolley|16192 Coastal|32413 Lewes|"
    r"418 Broadway|5900 Balcones|1209 Mountain Road|6801 Jefferson", re.I)
CN_COMPANY_RE = re.compile(
    r"keji|youxian|gongsi|maoyi|dianzi|shangmao|shenzhen|guangzhou|yiwu|hangzhou|suzhou|dongguan|"
    r"xiamen|ningbo|fujian|zhejiang|jiangsu|cross-?border", re.I)
NOT_A_SELLER = {"ATVPDKIKX0DER", "-1", "-2", ""}

# The tags the agent assigns, strongest tier first (the "made once, sold many times" thesis).
KEEP_TAGS = ["design-led", "art-or-licensed", "content-led", "software-or-app", "utility-with-design-twist"]
DROP_TAGS = ["commodity", "food-or-supplement", "reseller", "established"]


def selection(cat_filter, page, a):
    cutoff = kminutes(datetime.now(timezone.utc)) - a["months"] * 30 * 1440
    return {
        "listedSince_gte": cutoff,                       # the PRODUCT is new, not just the seller account
        "monthlySold_gte": a["min_units"], "monthlySold_lte": a["max_units"],   # traction, not an incumbent
        "current_NEW_gte": a["min_price"],               # $13 and up by default, no ceiling
        "current_COUNT_NEW_lte": 1,                      # one new offer: the brand owns the listing
        "buyBoxIsAmazon": False,
        **({"variationCount_gte": a["min_variations"]} if a["min_variations"] else {}),
        "sort": [["monthlySold", "desc"]], "perPage": 50, "page": page, **cat_filter}


def slim(p, label):
    st = p.get("stats") or {}
    cur = st.get("current") or []
    price = pick_price(st)
    rng = badge_range(p.get("monthlySold"))
    title = p.get("title") or ""
    return {
        "asin": p["asin"], "url": f"https://www.amazon.com/dp/{p['asin']}", "title": title[:160],
        "brand": p.get("brand") or "", "manufacturer": p.get("manufacturer") or "",
        "category": " > ".join(c.get("name") for c in (p.get("categoryTree") or [])),
        "searchedIn": label,
        "priceCents": price["cents"] if price else None,
        "units": {"label": badge_label(rng[0]), "low": rng[0], "high": rng[1]} if rng else None,
        "revenueLowCents": rng[0] * price["cents"] if rng and price else None,
        "revenueHighCents": rng[1] * price["cents"] if rng and price else None,
        "listedSince": kdate(p["listedSince"]).date().isoformat() if (p.get("listedSince") or 0) > 0 else None,
        "variations": len(p.get("variations") or []),
        "rating": (cur[16] / 10) if len(cur) > 16 and (cur[16] or 0) > 0 else None,
        "reviews": cur[17] if len(cur) > 17 and (cur[17] or 0) > 0 else None,
        "features": [f[:200] for f in (p.get("features") or [])[:4]],
        "hints": {"design": sorted({m.group(0).lower() for m in DESIGN_HINTS.finditer(title)}),
                  "commodity": sorted({m.group(0).lower() for m in COMMODITY_HINTS.finditer(title)})},
    }


# ─── Args ────────────────────────────────────────────────────────────

def args_multi(flag):
    res, i = [], 0
    while i < len(sys.argv):
        if sys.argv[i] == flag and i + 1 < len(sys.argv):
            res.append(sys.argv[i + 1])
            i += 1
        i += 1
    return res


def arg(flag, default=None):
    v = args_multi(flag)
    return v[-1] if v else default


def int_arg(flag, default, lo, hi):
    try:
        v = arg(flag)
        return default if v is None else max(lo, min(int(v), hi))
    except ValueError:
        out({"error": "bad_" + flag.strip("-")}, 4)


def need_keepa(route):
    md = mode()
    if md == "none":
        out(NO_KEYS, 2)
    if not has("KEEPA_API_KEY"):
        out({"mode": md, "error": "whm_route_not_live", "route": route,
             "note": "No WaitHowMuch route runs this search yet. It is not in API-PROXY.md either (the nearest "
                     "proposal is GET /v1/tools/niche-scan, which groups a keyword's best sellers by brand, without "
                     "the new-listing, single-seller and seller-country filters this needs).",
             "fallback": "Set KEEPA_API_KEY (Option A) and this runs on your own Keepa key."}, 2)
    return "keepa"


# ─── Commands ────────────────────────────────────────────────────────

def cmd_categories():
    out({"categories": list(CATEGORIES), "default": DEFAULT_CATEGORIES, "niches": {k: list(v) for k, v in NICHES.items()},
         "keywords": KEYWORDS, "keepTags": KEEP_TAGS, "dropTags": DROP_TAGS})


def cmd_scan():
    md = need_keepa("GET /v1/tools/design-finder?category=|niche=|keywords=")
    a = {"months": int_arg("--months", 24, 1, 120), "min_units": int_arg("--min-units", 100, 1, 100000),
         "max_units": int_arg("--max-units", 5000, 1, 1000000), "min_price": int_arg("--min-price", 13, 0, 10000) * 100,
         "min_variations": int_arg("--min-variations", 0, 0, 100)}
    per = int_arg("--per-query", 20, 1, 200)
    queries = {}
    for c in args_multi("--category"):
        if c not in CATEGORIES:
            out({"error": "unknown_category", "category": c, "known": list(CATEGORIES)}, 4)
        queries[c] = CATEGORIES[c]
    for n in args_multi("--niche"):
        if n not in NICHES:
            out({"error": "unknown_niche", "niche": n, "known": list(NICHES)}, 4)
        queries.update(NICHES[n])
    kw = arg("--keywords")
    if kw is not None:
        words = KEYWORDS if kw in ("*", "default") else [w.strip() for w in kw.split(",") if w.strip()]
        queries.update({"kw: " + w: {"title": w} for w in words})
    if not queries:
        queries = {c: CATEGORIES[c] for c in DEFAULT_CATEGORIES}
    pages = (per + 49) // 50
    k = Keepa()
    k.ensure(len(queries) * pages * 11 + len(queries) * per)
    matched, totals = {}, {}
    for label, f in queries.items():
        got = []
        for page in range(pages):
            q = k.call("query", {}, selection(f, page, a))
            if page == 0:
                totals[label] = q.get("totalResults")
            ids = q.get("asinList") or []
            got += ids
            if len(ids) < 50:
                break
        for asin in got[:per]:
            matched.setdefault(asin, label)
    rows, asins = [], list(matched)
    for i in range(0, len(asins), 100):
        r = k.call("product", {"asin": ",".join(asins[i:i + 100]), "stats": 1, "history": 0})
        rows += [slim(p, matched[p["asin"]]) for p in r.get("products") or []]
    rows.sort(key=lambda r: -(r["revenueLowCents"] or 0))
    out({"mode": md, "filters": {"listedWithinMonths": a["months"], "monthlySold": [a["min_units"], a["max_units"]],
                                 "minPriceUsd": a["min_price"] / 100, "newOffersMax": 1, "amazonNotInBuyBox": True,
                                 "minVariations": a["min_variations"]},
         "matchesPerQuery": totals, "fetched": len(rows), "products": rows,
         "next": "Tag each product (tags: " + ", ".join(KEEP_TAGS + DROP_TAGS) + ") with a one-line why, then run "
                 "`sellers` on the ones you kept.",
         "retrievedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "Keepa", **k.meta()})


def read_rows(raw):
    if os.path.exists(raw):
        data = json.load(open(raw))
        return data.get("products", data) if isinstance(data, dict) else data
    return [{"asin": a.strip().upper()} for a in re.split(r"[,\s]+", raw) if a.strip()]


def cmd_sellers():
    md = need_keepa("GET /v1/tools/design-finder/sellers?asins=")
    raw = " ".join(a for a in sys.argv[2:] if not a.startswith("--"))
    rows = [r for r in read_rows(raw) if re.fullmatch(r"[A-Z0-9]{10}", (r.get("asin") or "").upper())]
    if not rows:
        out({"error": "empty", "message": "give ASINs (comma-separated) or a JSON file of rows with `asin`"}, 4)
    rows = rows[:int_arg("--max", 30, 1, 200)]
    k = Keepa()
    k.ensure(3 * len(rows) + len(rows))
    for i in range(0, len(rows), 50):
        batch = rows[i:i + 50]
        # buybox=1 (+2 tokens) is required: without it Keepa reports Amazon as the seller of every row.
        r = k.call("product", {"asin": ",".join(x["asin"] for x in batch), "stats": 1, "history": 0, "buybox": 1})
        by = {p["asin"]: p for p in r.get("products") or []}
        for x in batch:
            st = (by.get(x["asin"]) or {}).get("stats") or {}
            sid = st.get("buyBoxSellerId") or ""
            x["sellerId"] = "" if sid in NOT_A_SELLER else sid
            x["buyBoxIsFBA"] = st.get("buyBoxIsFBA")
    ids = sorted({x["sellerId"] for x in rows if x["sellerId"]})
    info = {}
    for i in range(0, len(ids), 100):
        info.update(k.call("seller", {"seller": ",".join(ids[i:i + 100])}).get("sellers") or {})
    kept, dropped = [], []
    for x in rows:
        s = info.get(x["sellerId"]) or {}
        addr = s.get("address") or []
        address = ", ".join(addr[:-1]) if len(addr) > 1 else ", ".join(addr)
        stats = s.get("sellerBrandStatistics") or []
        flags = []
        if AGENT_RE.search(address):
            flags.append("registered-agent address: says nothing about who runs it")
        if CN_COMPANY_RE.search(s.get("businessName") or ""):
            flags.append("business name reads as a Chinese company")
        if x["sellerId"] and not addr:
            flags.append("no address on file, country unknown")
        if not x["sellerId"]:
            flags.append("no third-party buy-box seller (Amazon, suppressed or out of stock)")
        x.update({"sellerName": s.get("sellerName") or "", "business": s.get("businessName") or "", "address": address,
                  "country": addr[-1] if addr else "", "sellerRating": s.get("currentRating"),
                  "sellerRatings": s.get("currentRatingCount") or 0,
                  "sellerFirstSeen": kdate(s["trackedSince"]).date().isoformat() if s.get("trackedSince") else None,
                  "storeUrl": f"https://www.amazon.com/sp?seller={x['sellerId']}" if x["sellerId"] else None,
                  # a design line is one brand with many products; a reseller carries many brands
                  "sellerTopBrandProducts": max([b.get("productCount") or 0 for b in stats] or [0]),
                  "sellerBrands": len(stats), "flags": flags})
        (dropped if x["country"] in ("CN", "HK") else kept).append(x)
    out({"mode": md, "products": kept,
         "droppedChinaHongKong": [{"asin": x["asin"], "brand": x.get("brand"), "sellerName": x["sellerName"]} for x in dropped],
         "retrievedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "Keepa", **k.meta()})


def cmd_shortlist():
    """Offline: merge tagged rows by seller (or brand), drop the out-of-scope tags, rank. No network."""
    path = " ".join(a for a in sys.argv[2:] if not a.startswith("--"))
    if not path or not os.path.exists(path):
        out({"error": "empty", "message": "give a JSON file of rows, each with `tag` and `why` (and seller fields from `sellers`)"}, 4)
    rows = read_rows(path)
    untagged = [r.get("asin") for r in rows if r.get("tag") not in KEEP_TAGS + DROP_TAGS]
    if untagged:
        out({"error": "untagged", "asins": untagged, "tags": KEEP_TAGS + DROP_TAGS}, 4)
    groups = {}
    for r in rows:
        if r["tag"] not in KEEP_TAGS or r.get("country") in ("CN", "HK"):
            continue
        key = r.get("sellerId") or ("brand:" + (r.get("brand") or r["asin"]).lower())
        g = groups.setdefault(key, {"brand": r.get("brand"), "sellerId": r.get("sellerId") or None,
                                    "sellerName": r.get("sellerName"), "business": r.get("business"),
                                    "country": r.get("country"), "storeUrl": r.get("storeUrl"),
                                    "sellerFirstSeen": r.get("sellerFirstSeen"), "sellerRatings": r.get("sellerRatings"),
                                    "sellerTopBrandProducts": r.get("sellerTopBrandProducts"),
                                    "tag": r["tag"], "products": [], "revenueLowCents": 0, "revenueHighCents": 0,
                                    "flags": set()})
        g["products"].append({"asin": r["asin"], "title": r.get("title"), "url": r.get("url"), "units": r.get("units"),
                              "priceCents": r.get("priceCents"), "listedSince": r.get("listedSince"),
                              "variations": r.get("variations"), "tag": r["tag"], "why": r.get("why")})
        g["revenueLowCents"] += r.get("revenueLowCents") or 0
        g["revenueHighCents"] += r.get("revenueHighCents") or 0
        g["flags"].update(r.get("flags") or [])
        if KEEP_TAGS.index(r["tag"]) < KEEP_TAGS.index(g["tag"]):
            g["tag"] = r["tag"]
    res = []
    for g in groups.values():
        signals = []
        if (g.get("sellerTopBrandProducts") or 0) >= 8:
            signals.append(f"design line: {g['sellerTopBrandProducts']} products under its top brand")
        if any((p.get("variations") or 0) >= 3 for p in g["products"]):
            signals.append("3+ variants (designs, characters, themes) under one listing")
        if len(g["products"]) > 1:
            signals.append(f"{len(g['products'])} qualifying products from one seller")
        g["signals"], g["flags"] = signals, sorted(g["flags"])
        res.append(g)
    tier = {t: i for i, t in enumerate(KEEP_TAGS)}
    # Ranking: thesis tier (design-led strongest), then demand (revenue floor), then the design-line signal.
    res.sort(key=lambda g: (tier[g["tag"]] > 1, -g["revenueLowCents"], -(g.get("sellerTopBrandProducts") or 0)))
    for i, g in enumerate(res, 1):
        g["rank"] = i
    out({"shortlist": res, "considered": len(rows), "kept": sum(len(g["products"]) for g in res),
         "rankedBy": "tier (design-led / art-or-licensed first), then estimated monthly revenue floor, then products under "
                     "the seller's top brand. Revenue = Amazon's badge bucket x price, a floor."})


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    usage_ping(cmd)
    if cmd == "mode":
        md = mode()
        out({"mode": md, "keys": {"WHM_API_KEY": has("WHM_API_KEY"), "KEEPA_API_KEY": has("KEEPA_API_KEY")},
             **({} if md != "none" else NO_KEYS),
             **({"note": "This skill runs on KEEPA_API_KEY only for now; no WHM route serves it yet."} if md == "whm" and not has("KEEPA_API_KEY") else {}),
             "skill": SKILL, "version": VERSION})
    {"categories": cmd_categories, "scan": cmd_scan, "sellers": cmd_sellers, "shortlist": cmd_shortlist}.get(
        cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
