#!/usr/bin/env python3
"""WaitHowMuch skills data helper: one WHM API key, or your own Keepa key.

Identical copy in every skill's scripts/ folder; edit all four together.
Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key
(Keepa takes its key in the query string, so no URL is ever printed).

Mode, decided per run from the environment:
  1. WHM_API_KEY set   -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
  2. KEEPA_API_KEY set -> Keepa API directly (your tokens)
  3. neither           -> {"error": "no_keys", ...}, exit 2

Commands:
  mode                         which mode this run would use (no provider call)
  product <ASIN|amazon.com URL>  monthly units/revenue range, price, fees    (Keepa: 1 token)
  api </v1/path?query>         GET a WaitHowMuch API route (WHM mode only)
  brand <name> [--seller ID] [--max N]   catalogue revenue of any brand   (needs KEEPA_API_KEY: ~11 + N tokens)
  niche "<keywords>" [--max N]           top-selling brands for a keyword (needs KEEPA_API_KEY: ~11 + N tokens)

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

COMMANDS = {"api", "brand", "mode", "niche", "product"}
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


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    usage_ping(cmd)
    if cmd == "mode":
        md = mode()
        out({"mode": md, "keys": {"WHM_API_KEY": bool(os.environ.get("WHM_API_KEY", "").strip()),
                                  "KEEPA_API_KEY": bool(os.environ.get("KEEPA_API_KEY", "").strip())},
             **({} if md != "none" else NO_KEYS), "skill": SKILL, "version": VERSION})
    {"product": cmd_product, "api": cmd_api, "brand": cmd_brand, "niche": cmd_niche}.get(
        cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
