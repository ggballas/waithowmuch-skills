#!/usr/bin/env python3
"""WaitHowMuch skills data helper, amazon-listing-teardown: everything about one competitor ASIN's
listing - content (title, bullets, images, videos, A+, variations), price / BSR / rating / review
history, offers and buy box, launch date and the sales badge. One WHM API key, or your own Keepa key.

Shared core (mode, HTTP, Keepa client) is the same in every skill's scripts/whm.py.
Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key
(Keepa takes its key in the query string, so no URL is ever printed).

Mode, decided per run from the environment:
  1. WHM_API_KEY set   -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
  2. KEEPA_API_KEY set -> Keepa API directly (your tokens)
  3. neither           -> {"error": "no_keys", ...}, exit 2   (`page` needs no key)
A WHM route that is not live yet returns {"error": "whm_route_not_live"}; if KEEPA_API_KEY is also
set, the command falls back to Keepa instead.

Commands:
  mode                                   which mode this run would use (no provider call)
  listing <ASIN|amazon.com URL> [--months N] [--no-buybox]
                                         the teardown from Keepa (4 tokens + 1 for the buy-box seller's
                                         name; --no-buybox: 2 tokens, no buy-box share or seller)
  page <ASIN|amazon.com URL>             what only the live page shows (badges, A+ type, brand story,
                                         "Customers say"). ONE plain request, no key, no retry; on a
                                         bot check it returns page_blocked and the agent reads the page itself
  api </v1/path?query>                   GET a WaitHowMuch API route (WHM mode only)

Exit codes: 0 ok, 1 upstream/API error, 2 no keys / wrong mode / route not live, 3 not enough Keepa
tokens, 4 bad input, 5 page blocked.
"""
import base64
import gzip
import html as htmllib
import json
import math
import os
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VERSION = "0.4.1"
WHM_API = os.environ.get("WHM_API_BASE", "").strip().rstrip("/") or "https://api.waithowmuch.com"
KEEPA = "https://api.keepa.com"
US = 1
KEEPA_EPOCH_MIN = 21_564_000  # Keepa time = minutes since 2011-01-01 UTC
IMG = "https://m.media-amazon.com/images/I/"
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

COMMANDS = {"api", "listing", "mode", "page"}
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


def not_live(route, note, **extra):
    return {"mode": "whm", "error": "whm_route_not_live", "route": route, "note": note, **extra,
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


# ─── ASINs and Keepa time ────────────────────────────────────────────

ASIN_RE = re.compile(r"^(?:B0[A-Z0-9]{8}|\d{9}[\dX])$")
ASIN_IN_PATH = re.compile(r"/(?:dp|gp/product|gp/aw/d|product|d)/([A-Z0-9]{10})(?:[/?]|$)", re.I)


def parse_asin(raw, fatal=True):
    s = raw.strip()
    if ASIN_RE.match(s.upper()):
        return s.upper()
    u = urllib.parse.urlparse(s if re.match(r"^https?://", s, re.I) else "https://" + s)
    host = (u.hostname or "").lower()
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


def kdate(minute):
    return datetime.fromtimestamp((minute + KEEPA_EPOCH_MIN) * 60, timezone.utc)


def kday(minute):
    return kdate(minute).date().isoformat() if isinstance(minute, int) and minute > 0 else None


def kminutes(dt):
    return int(dt.timestamp() // 60) - KEEPA_EPOCH_MIN


def badge_label(v):
    return f"{v / 1_000_000:g}M+" if v >= 1_000_000 else f"{v / 1000:g}K+" if v >= 1000 else f"{v}+"


def pairs(h, step=2):
    """Keepa [t, v, t, v ...] (or [t, v, x ...] with step 3) -> [(minute, v)]; -1 = no data/out of stock."""
    h = h or []
    return [(h[i], h[i + 1]) for i in range(0, len(h) - step + 1, step)]


def at(series, minute):
    v = None
    for t, x in series:
        if t > minute:
            break
        v = x
    return v


def months_back(n, now):
    """The last n months INCLUDING the current one, oldest first: [(YYYY-MM, start minute, end minute)]."""
    res, y, m = [], now.year, now.month
    for _ in range(n):
        start = datetime(y, m, 1, tzinfo=timezone.utc)
        nxt = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
        res.append((f"{y}-{m:02d}", kminutes(start), min(kminutes(nxt), kminutes(now)) - 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return list(reversed(res))


def cents(v):
    return v if isinstance(v, int) and v > 0 else None


# ─── The teardown ────────────────────────────────────────────────────

def price_series(p):
    """Buy box (price + shipping) when Keepa has it, else lowest new. Cents, None = no offer."""
    c = p.get("csv") or []
    bb = c[18] if len(c) > 18 and c[18] else None
    if bb:
        return "buy_box", [(t, (v + max(s, 0)) if v > 0 else None) for t, v, s in
                           [(bb[i], bb[i + 1], bb[i + 2]) for i in range(0, len(bb) - 2, 3)]]
    new = c[1] if len(c) > 1 else None
    return "new", [(t, v if v > 0 else None) for t, v in pairs(new)]


def monthly(p, n):
    now = datetime.now(timezone.utc)
    c = p.get("csv") or []
    src, price = price_series(p)
    ref = str(p.get("salesRankReference") if (p.get("salesRankReference") or -1) > 0 else p.get("rootCategory"))
    bsr = pairs((p.get("salesRanks") or {}).get(ref))
    rating = pairs(c[16] if len(c) > 16 else None)
    ratings = pairs(c[17] if len(c) > 17 else None)
    reviews = pairs((p.get("reviews") or {}).get("reviewCount"))
    badge = pairs(p.get("monthlySoldHistory"))
    rows = []
    for label, start, end in months_back(n, now):
        ranks = [v for t, v in bsr if start <= t <= end and v > 0]
        if not ranks:
            v = at(bsr, start)
            ranks = [v] if v and v > 0 else []
        prices = [v for t, v in price if start <= t <= end and v]
        pe, r, rc, wr, b = at(price, end), at(rating, end), at(ratings, end), at(reviews, end), at(badge, end)
        rows.append({
            "month": label,
            "priceEndCents": pe, "priceMinCents": min(prices + ([pe] if pe else []), default=None),
            "bsrMedian": round(statistics.median(ranks)) if ranks else None,
            "bsrBest": min(ranks) if ranks else None,
            "rating": r / 10 if r and r > 0 else None,
            "ratings": rc if rc is not None and rc >= 0 else None,
            "writtenReviews": wr if wr is not None and wr >= 0 else None,
            "badge": badge_label(b) if b and b > 0 else None,
        })
    rows[-1]["live"] = True
    return src, ref, rows


def coupons(p, since):
    """couponHistory = [t, one-time, subscribe&save, ...]: >0 cents off, <0 percent off, 0 none."""
    h, res = p.get("couponHistory") or [], []
    for i in range(0, len(h) - 2, 3):
        if h[i] < since:
            continue
        v = h[i + 1]
        res.append({"from": kday(h[i]), "coupon": None if not v else (f"{-v}% off" if v < 0 else f"${v / 100:.2f} off")})
    return res


def ships_by(p):
    st = p.get("stats") or {}
    return "Amazon" if st.get("buyBoxIsAmazon") else ("FBA" if st.get("buyBoxIsFBA") else ("FBM" if st.get("buyBoxSellerId") else None))


def teardown(p, n, k, with_buybox):
    st = p.get("stats") or {}
    cats = {str(c.get("catId")): c.get("name") for c in p.get("categoryTree") or []}
    src, ref, rows = monthly(p, n)
    since = kminutes(datetime.now(timezone.utc)) - n * 31 * 1440
    ranks_now = {cats.get(cid, f"Category {cid}"): pairs(h)[-1][1] for cid, h in (p.get("salesRanks") or {}).items()
                 if pairs(h) and pairs(h)[-1][1] > 0}
    imgs = p.get("images") or []
    vids = p.get("videos") or []
    aplus = p.get("aPlus") or []
    variations = p.get("variations") or []
    dims = sorted({a.get("dimension") for v in variations for a in v.get("attributes") or [] if a.get("dimension")})
    full = [r for r in rows if not r.get("live")]
    allp = [r["priceMinCents"] for r in rows if r["priceMinCents"]]
    allb = [r["bsrBest"] for r in rows if r["bsrBest"]]
    res = {
        "asin": p["asin"], "marketplace": "us", "url": f"https://www.amazon.com/dp/{p['asin']}",
        "content": {
            "title": p.get("title"), "titleChars": len(p.get("title") or ""),
            "brand": p.get("brand"), "brandStore": p.get("brandStoreName"),
            "itemHighlights": p.get("itemHighlights"),
            "bullets": p.get("features") or [], "bulletCount": len(p.get("features") or []),
            "description": (p.get("description") or "")[:1500] or None,
            "images": {"count": len(imgs), "slots": [i.get("variant") for i in imgs],
                       "main": IMG + imgs[0]["l"] if imgs and imgs[0].get("l") else None,
                       "allHiRes": all((i.get("lW") or 0) >= 1000 for i in imgs) if imgs else None},
            "videos": {"count": len(vids), "byCreator": {c: sum(1 for v in vids if v.get("creator") == c)
                                                        for c in sorted({v.get("creator") or "?" for v in vids})},
                       "titles": [v.get("title") for v in vids if v.get("title")][:8]},
            "aPlus": {"present": bool(aplus), "modules": sum(len(a.get("module") or []) for a in aplus),
                      "text": [t for a in aplus for m in a.get("module") or [] for t in (m.get("text") or [])][:12]},
            "variations": {"count": len(variations), "dimensions": dims, "parentAsin": p.get("parentAsin"),
                           "values": [" / ".join(a.get("value") or "" for a in v.get("attributes") or []) for v in variations][:40]},
            "categoryPath": [c.get("name") for c in p.get("categoryTree") or []],
            "subscribeAndSave": p.get("isSNS"),
            "frequentlyBoughtTogether": p.get("frequentlyBoughtTogether") or [],
        },
        "launch": {"listedSince": kday(p.get("listedSince")), "keepaTrackingSince": kday(p.get("trackingSince"))},
        "now": {
            "priceCents": cents(st.get("buyBoxPrice")) or cents((st.get("current") or [None] * 2)[1]),
            "priceSource": "buy_box" if cents(st.get("buyBoxPrice")) else "new",
            "listPriceCents": cents((st.get("current") or [None] * 5)[4]),
            "bsr": ranks_now, "bsrCategory": cats.get(ref, f"Category {ref}"),
            "rating": (lambda v: v / 10 if v and v > 0 else None)((st.get("current") or [None] * 17)[16]),
            "ratings": (lambda v: v if v and v >= 0 else None)((st.get("current") or [None] * 18)[17]),
            "writtenReviews": (pairs((p.get("reviews") or {}).get("reviewCount")) or [(0, None)])[-1][1],
            "salesBadge": badge_label(p["monthlySold"]) + " bought in past month" if (p.get("monthlySold") or 0) > 0 else None,
            "outOfStockPct90d": (lambda v: v if isinstance(v, int) and v >= 0 else None)(
                (st.get("outOfStockPercentage90") or [None, None])[1] if isinstance(st.get("outOfStockPercentage90"), list)
                else st.get("outOfStockPercentage90")),
            "salesRankDrops30d": st.get("salesRankDrops30"), "salesRankDrops90d": st.get("salesRankDrops90"),
        },
        "history": rows,
        "historySummary": {
            "months": len(rows), "priceSource": src,
            "priceLowCents": min(allp, default=None), "priceHighCents": max((r["priceEndCents"] or 0 for r in rows), default=None) or None,
            "bsrBest": min(allb, default=None), "bsrWorstMedian": max((r["bsrMedian"] or 0 for r in full), default=None) or None,
            "ratingsAdded": (rows[-1]["ratings"] - rows[0]["ratings"]) if rows[-1]["ratings"] is not None and rows[0]["ratings"] is not None else None,
            "coupons": coupons(p, since),
        },
        "offers": {"offerCountNew": (lambda v: v if isinstance(v, int) and v >= 0 else None)((st.get("current") or [None] * 12)[11]),
                   "buyBoxSellerId": st.get("buyBoxSellerId") if with_buybox else None,
                   "buyBoxShipsBy": ships_by(p) if with_buybox else None,
                   "buyBoxShare": ({sid: round(v.get("percentageWon") or 0) for sid, v in (st.get("buyBoxStats") or {}).items()}
                                   if with_buybox else None)},
        "pageOnly": ["Amazon's Choice / #1 Best Seller badges", "Premium A+ vs basic, and the Brand Story",
                     "live deal / coupon / Prime badges", "'Customers say' review summary", "star histogram",
                     "'Frequently returned item' warning", "Q&A"],
    }
    if with_buybox:
        sid = st.get("buyBoxSellerId")
        if sid and sid not in NOT_A_SELLER:
            s = (k.call("seller", {"seller": sid}).get("sellers") or {}).get(sid) or {}
            res["offers"]["buyBoxSeller"] = {"id": sid, "name": s.get("sellerName"), "url": f"https://www.amazon.com/sp?seller={sid}",
                                             "rating": s.get("currentRating"), "ratingCount": s.get("currentRatingCount")}
        elif sid == "ATVPDKIKX0DER":
            res["offers"]["buyBoxSeller"] = {"id": sid, "name": "Amazon.com"}
    return res


# ─── The live page (one plain request; never a bypass) ───────────────

BLOCKED = ("validateCaptcha", "api-services-support@amazon.com", "make sure you're not a robot", "Robot Check")


def page_fetch(asin):
    req = urllib.request.Request(f"https://www.amazon.com/dp/{asin}", headers={
        "User-Agent": f"whm-skills/{VERSION} (+https://github.com/ggballas/waithowmuch-skills)",
        "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return r.status, raw.decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001
        return 0, type(e).__name__


def _text(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.S)
    s = re.sub(r"<[^>]*$", " ", re.sub(r"<[^>]+>", " ", s))  # a cut segment can end mid-tag
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def _seg(h, id_, n=4000):
    i = h.find(f'id="{id_}"')
    if i < 0:
        return ""
    j = h.find(">", i)
    return h[j + 1:j + 1 + n]


def _grab(h, pattern):
    m = re.search(pattern, h, re.S)
    return _text(m.group(1)) or None if m else None


def _blobs(h):
    for b in re.findall(r"k-injected k\+b64 ([A-Za-z0-9+/=]+)", h):
        try:
            yield json.loads(base64.b64decode(b + "==="))
        except Exception:  # noqa: BLE001
            continue


def _frag(fr):
    return "".join(f.get("text") or ((f.get("semanticContent") or {}).get("content") or {}).get("text") or "" for f in fr or []).strip()


def page_parse(asin, h):
    t_ac, t_bs = _text(_seg(h, "acBadge_feature_div", 3000)), _text(_seg(h, "zeitgeistBadge_feature_div", 1500))
    bs = re.search(r"#1 Best Seller\s*(?:in\s*)?([^#]{0,60}?)(?:\s{2}|$|\d)", t_bs)
    mods = re.findall(r'class="celwidget aplus-module ([^"]*)"', h)
    story = [m for m in mods if "brand-story" in m]
    ap = [m for m in mods if "brand-story" not in m]
    rating = re.search(r'id="acrPopover"[^>]*title="([\d.]+) out of 5 stars"', h)
    ratings = re.search(r"([\d,]+) global ratings?", h)
    summary, aspects_detail = None, {}
    for d in _blobs(h):
        kd = d.get("k-data") or {}
        if summary is None and str(d.get("k-component", "")).startswith("SummaryFragments"):
            summary = " ".join(f.get("inertText") or "" for f in kd.get("fragments") or []).strip() or None
        for a in kd.get("aspectsFlattened") or []:
            if a.get("summary") and a.get("label") not in aspects_detail:
                aspects_detail[a["label"]] = {"summary": a.get("summary"),
                                              "quotes": [_frag((s.get("text") or {}).get("fragments")) for s in a.get("snippets") or []][:4]}
    aspects = []
    for m, label, pos_, neg in re.findall(r"(\d+) customers mention ([^,<\"]+), (\d+) positive, (\d+) negative", htmllib.unescape(h)):
        if label in [a["aspect"] for a in aspects]:
            continue
        aspects.append({"aspect": label, "mentions": int(m), "positive": int(pos_), "negative": int(neg),
                        **aspects_detail.get(label.lower(), aspects_detail.get(label, {}))})
    hist = {f"{s}star": int(p) for p, s in re.findall(r'aria-label="(\d+) percent of reviews have (\d) stars?"', h)}
    bought = _grab(h, r'id="social-proofing-faceout-title-tk_bought"[^>]*>(.*?)</div>')
    vids = re.search(r"(\d+) VIDEOS", h)
    return {
        "asin": asin, "url": f"https://www.amazon.com/dp/{asin}", "source": "public product page, one request",
        "title": _grab(h, r'id="productTitle"[^>]*>(.*?)</span>'),
        "byline": _grab(h, r'<a id="bylineInfo"[^>]*>(.*?)</a>'),
        "badges": {"amazonsChoice": "Amazon's Choice" in t_ac, "bestSeller": (bs.group(1).strip() or True) if bs else False,
                   "boughtPastMonth": bought or None,
                   "deal": bool(re.search(r"Limited time deal|Lightning Deal|Prime (?:Big )?Deal", _text(_seg(h, "dealBadge_feature_div", 2500)))),
                   "smallBusiness": 'id="smallBusinessBadge' in h or "Small Business" in _text(_seg(h, "provenanceCertifications_feature_div", 3000)),
                   "frequentlyReturned": "Frequently returned item" in h},
        "aPlus": {"present": bool(ap), "modules": len(ap), "premium": any("premium" in m for m in ap),
                  "brandStory": bool(story)},
        "videoCountOnPage": int(vids.group(1)) if vids else 0,
        "rating": float(rating.group(1)) if rating else None,
        "ratings": int(ratings.group(1).replace(",", "")) if ratings else None,
        "starHistogramPct": hist or None,
        "customersSay": summary,
        "aspects": aspects,
        "notOnPage": "Individual top reviews load by script and are not in a plain read; a browser shows the first "
                     "~8-10. The full review list needs an Amazon sign-in, which this skill never does.",
    }


def page_blocked(asin, status):
    if status == 404:
        return {"error": "asin_not_found", "asin": asin, "status": 404,
                "message": "amazon.com has no product page for this ASIN (wrong ASIN, or not sold in the US)."}
    return {"error": "page_blocked", "asin": asin, "status": status, "url": f"https://www.amazon.com/dp/{asin}",
            "agentTodo": "Amazon answered a plain request with a bot check. Do not retry or work around it. If you have a "
                         "browser or web-page tool, open the URL and read it yourself; else ask the user to paste the page "
                         "text (or a screenshot). Keepa's fields don't need the page."}


# ─── Args ────────────────────────────────────────────────────────────

FLAGS_WITH_VALUE = {"--months"}


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


def retrieved():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─── Commands ────────────────────────────────────────────────────────

def cmd_listing():
    raw, n, with_bb = positional(), int_arg("--months", 12, 1, 36), "--no-buybox" not in sys.argv
    if not raw:
        out({"error": "invalid_asin", "reason": "empty"}, 4)
    asin = parse_asin(raw)
    md = mode()
    if md == "none":
        out(NO_KEYS, 2)
    if md == "whm":
        status, body = whm_get("/v1/tools/listing-teardown?" + urllib.parse.urlencode({"asin": asin, "months": n}), allow=(404,))
        if status == 200:
            out({"mode": "whm", **body})
        if not has("KEEPA_API_KEY"):
            if not route_missing(status, body):
                out({"mode": "whm", "status": status, **body}, 1)
            _, part = whm_get("/v1/tools/product-sales?" + urllib.parse.urlencode({"asin": asin}), allow=(404,))
            out(not_live("GET /v1/tools/listing-teardown?asin=&months=",
                         "WaitHowMuch has no listing-teardown route yet. `partial` is what the live product-sales route "
                         "gives (title, brand, price, sales badge, launch date, fees); bullets, images, A+, variations and "
                         "the price/BSR/review history need KEEPA_API_KEY.", partial=part), 2)
    k = Keepa()
    k.ensure(5 if with_bb else 2)
    params = {"asin": asin, "stats": 90, "history": 1, "rating": 1, "days": n * 31 + 31, "videos": 1, "aplus": 1}
    if with_bb:
        params["buybox"] = 1
    p = (k.call("product", params).get("products") or [None])[0]
    if not p or (not p.get("title") and not p.get("categoryTree")):
        out({"mode": "keepa", "error": "asin_not_found", "asin": asin, **k.meta()}, 1)
    res = teardown(p, n, k, with_bb)
    out({"mode": "keepa", **res, "retrievedAt": retrieved(), "source": "Keepa", **k.meta()})


def cmd_page():
    asin = parse_asin(positional() or "")
    status, h = page_fetch(asin)
    if status != 200 or any(b in h[:200000] for b in BLOCKED) or 'id="productTitle"' not in h:
        out(page_blocked(asin, status), 5)
    out({**page_parse(asin, h), "retrievedAt": retrieved()})


def cmd_api():
    if mode() != "whm":
        out({"error": "wrong_mode", "mode": mode(), "message": "api runs in WHM mode (WHM_API_KEY)"}, 2)
    out({"mode": "whm", **whm_get(positional())[1]})


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    usage_ping(cmd)
    if cmd == "mode":
        md = mode()
        out({"mode": md, "keys": {"WHM_API_KEY": has("WHM_API_KEY"), "KEEPA_API_KEY": has("KEEPA_API_KEY")},
             **({} if md != "none" else NO_KEYS), "skill": SKILL, "version": VERSION})
    {"listing": cmd_listing, "page": cmd_page, "api": cmd_api}.get(
        cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
