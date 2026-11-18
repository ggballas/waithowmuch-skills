#!/usr/bin/env python3
"""WaitHowMuch skills data helper, amazon-case-study-builder: plans a full case study of an Amazon brand from
the keys present, fetches the product photos, and checks whether WaitHowMuch has already researched the brand.
The figures themselves come from the sibling skills' helpers (see SKILL.md); render.py turns the result into HTML.

Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key (Keepa takes its key in the query
string, so no request URL is ever printed).

Mode, decided per run from the environment:
  1. WHM_API_KEY set -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
  2. your own keys   -> Keepa (KEEPA_API_KEY), Jungle Scout (JUNGLESCOUT_API_KEY), DataForSEO
                        (DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD), Similarweb (SIMILARWEB_API_KEY),
                        Kalodata (KALODATA_API_KEY); each section uses the ones it needs
  3. neither         -> {"error": "no_keys", ...}, exit 2
A WHM route that is not live yet returns {"error": "whm_route_not_live", "route": ...}; if a matching own
key is also set, the command falls back to it instead.

Commands:
  mode                               which keys are set, and which case-study sections they make possible
                                     (no provider call)
  lookup "<brand | ASIN | domain>"   is this brand already a WaitHowMuch case study? (WHM mode; free)
  photos <ASIN>[,<ASIN>...]          main product photo (Amazon image URL) + title for each ASIN, up to 20
                                     (Keepa: 1 token per ASIN; WHM: the product route, falls back to Keepa)
  api </v1/path?query>               GET a WaitHowMuch API route (WHM mode only)
  invoke                             count one use of this skill (a free WaitHowMuch call, no key, no input sent)

Exit codes: 0 ok, 1 upstream/API error, 2 no keys / wrong mode / route not live, 3 not enough tokens, 4 bad input.
"""
import gzip
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VERSION = "0.4.1"
WHM_API = os.environ.get("WHM_API_BASE", "").strip().rstrip("/") or "https://api.waithowmuch.com"
KEEPA = "https://api.keepa.com"
US = 1
IMG = "https://m.media-amazon.com/images/I/"
UTM = "utm_source=whm-skills&utm_medium=skill&utm_campaign=whm-skills&utm_content=amazon-case-study-builder"

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

COMMANDS = {"api", "invoke", "lookup", "mode", "photos"}
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


def own():
    return {"keepa": has("KEEPA_API_KEY"),
            "junglescout": has("JUNGLESCOUT_API_KEY"),
            "dataforseo": has("DATAFORSEO_LOGIN") and has("DATAFORSEO_PASSWORD"),
            "similarweb": has("SIMILARWEB_API_KEY"),
            "kalodata": has("KALODATA_API_KEY"),
            "amazonAds": all(has(v) for v in ("AMAZON_ADS_CLIENT_ID", "AMAZON_ADS_CLIENT_SECRET",
                                              "AMAZON_ADS_REFRESH_TOKEN", "AMAZON_ADS_PROFILE_ID"))}


def mode():
    if has("WHM_API_KEY"):
        return "whm"
    if any(own().values()):
        return "own"
    return "none"


NO_KEYS = {
    "error": "no_keys",
    "message": "Set ONE of: WHM_API_KEY (Option B: one WaitHowMuch API key) or your own provider keys (Option A): "
               "KEEPA_API_KEY (paid Keepa API plan, required for revenue, the chart, the breakdown and photos), plus "
               "JUNGLESCOUT_API_KEY or DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD for advertising and keywords; "
               "SIMILARWEB_API_KEY and KALODATA_API_KEY are optional. In Claude Code: /plugin > waithowmuch > "
               "Configure options. Elsewhere: environment variables. "
               "https://github.com/ggballas/waithowmuch-skills#data-providers",
}


# ─── HTTP ────────────────────────────────────────────────────────────

def _fetch(url, headers=None):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": f"whm-skills/{VERSION}",
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


def whm_get(path, allow=()):
    if not path.startswith("/v1/"):
        out({"error": "bad_path", "message": "path must start with /v1/"}, 4)
    sep = "&" if "?" in path else "?"
    status, body = _fetch(f"{WHM_API}{path}{sep}{urllib.parse.urlencode(TAG)}",
                          headers={"X-WHM-Key": os.environ["WHM_API_KEY"].strip()})
    if status == 200 or status in allow:
        return status, body
    out({"mode": "whm", "status": status, **(body if isinstance(body, dict) else {})}, 1)


def route_missing(status, body):
    return status == 404 and isinstance(body, dict) and body == {"error": "not_found"}


def retrieved():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Keepa:
    def __init__(self):
        self.key = os.environ["KEEPA_API_KEY"].strip()
        self.used, self.left = 0, None

    def call(self, path, params):
        qs = urllib.parse.urlencode({"key": self.key, "domain": US, **params})
        status, res = _fetch(f"{KEEPA}/{path}?{qs}")
        self.used += res.get("tokensConsumed") or 0
        if isinstance(res.get("tokensLeft"), int):
            self.left = res["tokensLeft"]
        if status == 429:
            out({"mode": "own", "error": "keepa_tokens_low", "tokensLeft": res.get("tokensLeft"),
                 "refillInSec": round((res.get("refillIn") or 60000) / 1000), **self.meta()}, 3)
        if status in (401, 402, 403):
            out({"mode": "own", "error": "keepa_key_rejected", "status": status,
                 "message": "Keepa refused the key (invalid, or no active API plan)."}, 1)
        if status != 200:
            out({"mode": "own", "error": "keepa_error", "status": status, **self.meta()}, 1)
        return res

    def meta(self):
        return {"tokensConsumed": self.used, "tokensLeft": self.left}


# ─── Args ────────────────────────────────────────────────────────────

ASIN_RE = re.compile(r"^(?:B0[A-Z0-9]{8}|\d{9}[\dX])$")
ASIN_IN_PATH = re.compile(r"/(?:dp|gp/product|gp/aw/d|product|d)/([A-Z0-9]{10})(?:[/?]|$)", re.I)


def positional():
    return sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else ""


def parse_asin(raw):
    s = raw.strip()
    if ASIN_RE.match(s.upper()):
        return s.upper()
    m = ASIN_IN_PATH.search(s)
    if m and "amazon.com" in s.lower() and ASIN_RE.match(m.group(1).upper()):
        return m.group(1).upper()
    out({"error": "invalid_asin", "value": raw[:80],
         "message": "Give 10-character ASINs or full amazon.com product links, comma-separated."}, 4)


# ─── mode: which sections the keys make possible ─────────────────────

def plan():
    """Section by section, in the page's order: what this run can fill, from which provider, and what is missing."""
    p, whm = own(), has("WHM_API_KEY")
    k, js, dfs, sw, kalo = p["keepa"], p["junglescout"], p["dataforseo"], p["similarweb"], p["kalodata"]
    researched_only = "WaitHowMuch-researched brands only (WHM_API_KEY); any other brand needs KEEPA_API_KEY"

    def row(section, skill, status, via, missing=None, note=None):
        r = {"section": section, "skill": skill, "status": status, "via": via}
        if missing:
            r["notAvailableWithout"] = missing
        if note:
            r["note"] = note
        return r

    rev = "yes" if k else "researched_only" if whm else "no"
    rows = [
        row("headline + top cards", "amazon-revenue-sales, amazon-profit-calculator", rev,
            "Keepa badge series" if k else researched_only if whm else None, None if rev != "no" else "KEEPA_API_KEY",
            "Profit headline needs the margin section; without cost of goods the title falls back to revenue."),
        row("product photos", "this skill: photos", "yes" if (k or whm) else "partial",
            "Keepa (1 token per ASIN)" if k else "WaitHowMuch product route" if whm else
            "public product page (amazon-listing-teardown page / amazon-review-insights page), may be bot-checked"),
        row("timeline", "amazon-listing-teardown, brand-outside-traffic spikes", "yes" if k else "partial",
            "Keepa launch dates, badge jumps, rank spikes" if k else "dates from the public record only"),
        row("revenue chart + sales breakdown", "amazon-revenue-sales brand/store", rev,
            "Keepa" if k else researched_only if whm else None, None if rev != "no" else "KEEPA_API_KEY"),
        row("how it sells (selling methods)", "brand-outside-traffic site, amazon-listing-teardown, tiktok-shop-research",
            "yes" if k else "partial", "own site scan (free) + Keepa offers/buy box" + (" + Kalodata" if kalo else ""),
            None if k else "KEEPA_API_KEY (buy box, FBA/FBM)"),
        row("margin waterfall", "amazon-cogs-estimator, amazon-profit-calculator", "yes" if (k or whm) else "no",
            "price + fees from Keepa; cost of goods from the user's factory price or supplier quotes (Freightos, USITC: free)",
            None if (k or whm) else "KEEPA_API_KEY",
            "Cost of goods is never invented: ask the user for a factory price or supplier quotes. Without one, "
            "the waterfall stops before cost of goods and there is no profit."),
        row("advertising", "amazon-adspend-estimator", "yes" if js else "footprint_only" if dfs else
            "researched_only" if whm else "no",
            "Jungle Scout model (~3 + 1 request per keyword)" if js else
            "DataForSEO: where their ads show, no dollar figure" if dfs else researched_only if whm else None,
            None if (js or dfs or whm) else "JUNGLESCOUT_API_KEY (or DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD for the footprint)"),
        row("top keywords", "amazon-top-organic-keywords", "yes" if (js or dfs) else "researched_only" if whm else "no",
            "Jungle Scout (1 request per 100 keywords)" if js else "DataForSEO (~$0.02; volumes ~20x below Amazon's)"
            if dfs else researched_only if whm else None,
            None if (js or dfs or whm) else "JUNGLESCOUT_API_KEY or DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD"),
        row("outside traffic", "brand-outside-traffic", "yes" if (sw or dfs) else "partial",
            ", ".join(x for x in ["site scan + YouTube (free)", "Similarweb visits" if sw else "",
                                  "DataForSEO Google traffic + brand searches (~$0.012 each)" if dfs else "",
                                  "Keepa rank spikes (1 token)" if k else "", "WaitHowMuch readings" if whm else ""] if x),
            None if (sw and dfs) else " / ".join(x for x in ["SIMILARWEB_API_KEY (site visits)" if not sw else "",
                                                             "DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD (Google traffic, "
                                                             "brand searches)" if not dfs else ""] if x)),
        row("TikTok Shop", "tiktok-shop-research", "yes" if kalo else "no", "Kalodata (~0.1 credit a call)" if kalo else None,
            None if kalo else "KALODATA_API_KEY"),
        row("listing + reviews", "amazon-listing-teardown, amazon-review-insights", "yes" if k else "partial",
            "Keepa teardown (5 tokens) + public page (free)" if k else "public page only (free, may be bot-checked)",
            None if k else "KEEPA_API_KEY (history, buy box)"),
        row("brand owner", "amazon-listing-teardown offers, amazon-revenue-sales store", "yes" if k else "partial",
            "Keepa buy-box seller and storefront" if k else "the listing's 'Sold by' line"),
        row("valuation", "amazon-brand-valuation value", "yes" if k else "researched_only" if whm else "no",
            "offline model on 12 months of profit" if k else researched_only if whm else None,
            None if (k or whm) else "KEEPA_API_KEY",
            "Needs 12 months of series AND the margin (cost of goods + ads). Under 12 months: no valuation."),
        row("similar case studies", "amazon-case-studies", "yes" if whm else "niche_scan" if k else "no",
            "WaitHowMuch case studies" if whm else "Keepa niche scan (~11 + N tokens), revenue only" if k else None,
            None if (whm or k) else "WHM_API_KEY"),
        row("textual analysis, links, sources", "this skill", "yes", "written from the figures above"),
    ]
    return rows


def cmd_mode():
    md = mode()
    keys = {"WHM_API_KEY": has("WHM_API_KEY"), **own()}
    res = {"mode": md, "keys": keys, "sections": plan(), "skill": SKILL, "version": VERSION}
    if md == "none":
        res.update(NO_KEYS)
    out(res)


# ─── lookup: an existing WaitHowMuch case study ──────────────────────

def cmd_lookup():
    q = positional()
    if not q:
        out({"error": "bad_input", "message": "give a brand name, ASIN or domain"}, 4)
    if mode() != "whm":
        out({"error": "wrong_mode", "mode": mode(), "researched": None,
             "message": "lookup reads WaitHowMuch's case studies: set WHM_API_KEY. Without it, build from own keys."}, 2)
    _, body = whm_get("/v1/lookup?" + urllib.parse.urlencode({"q": q}))
    hits = body.get("results") or []
    if not hits:
        out({"mode": "whm", "query": q, "researched": False})
    h = hits[0]
    slug = h["business"]["slug"]
    out({"mode": "whm", "query": q, "researched": True, "business": h["business"].get("name"), "slug": slug,
         "matchedOn": h.get("matchedOn"), "match": h.get("match"),
         "caseStudy": f"https://waithowmuch.com/business/{slug}/?{UTM}",
         "next": f"python3 scripts/whm.py api \"/v1/businesses/{slug}\" for its series, profit, margin and valuation"})


# ─── photos ──────────────────────────────────────────────────────────

def keepa_photos(asins):
    k = Keepa()
    res = k.call("product", {"asin": ",".join(asins), "history": 0})
    by = {p.get("asin"): p for p in res.get("products") or []}
    rows = []
    for a in asins:
        p = by.get(a) or {}
        imgs = [i for i in p.get("images") or [] if i.get("l")]
        if not imgs and p.get("imagesCSV"):
            imgs = [{"l": f} for f in p["imagesCSV"].split(",") if f]
        rows.append({"asin": a, "title": p.get("title"), "brand": p.get("brand"),
                     "image": IMG + imgs[0]["l"] if imgs else None,
                     "images": [IMG + i["l"] for i in imgs[:8]],
                     "url": f"https://www.amazon.com/dp/{a}"})
    return rows, k.meta()


def cmd_photos():
    raw = positional()
    asins = [parse_asin(a) for a in raw.split(",") if a.strip()] if raw else []
    if not asins:
        out({"error": "bad_input", "message": "give one or more ASINs, comma-separated"}, 4)
    if len(asins) > 20:
        out({"error": "too_many", "message": "up to 20 ASINs a call"}, 4)
    md = mode()
    if md == "none":
        out(NO_KEYS, 2)
    rows, meta, src = None, None, None
    if md == "whm":
        rows = []
        for a in asins:
            status, body = whm_get("/v1/tools/product-sales?" + urllib.parse.urlencode({"asin": a}), allow=(404,))
            img = None
            if status == 200 and isinstance(body, dict):
                img = body.get("image") or body.get("imageUrl") or (body.get("product") or {}).get("image")
            rows.append({"asin": a, "title": body.get("title") if isinstance(body, dict) else None, "image": img,
                         "url": f"https://www.amazon.com/dp/{a}"})
        src = "WaitHowMuch product route"
        if any(not r["image"] for r in rows):
            if has("KEEPA_API_KEY"):
                rows, meta = keepa_photos(asins)
                src = "Keepa (the WaitHowMuch route returned no image)"
            else:
                out({"mode": "whm", "error": "whm_route_not_live", "route": "GET /v1/tools/product-sales (image field)",
                     "partial": rows, "fallback": "Read the main image off the public product page "
                                                  "(amazon-listing-teardown page) or set KEEPA_API_KEY."}, 2)
    elif has("KEEPA_API_KEY"):
        rows, meta = keepa_photos(asins)
        src = "Keepa"
    else:
        out({"mode": md, "error": "needs_keepa", "message": "photos need KEEPA_API_KEY or WHM_API_KEY; otherwise read "
                                                           "the main image off the public product page."}, 2)
    out({"mode": md, "photos": rows, "source": src,
         "note": "Amazon CDN URLs (m.media-amazon.com). They are linked, not copied, so the HTML stays one file; "
                 "Amazon can re-crop or drop an image, so the page carries the ASIN beside each one.",
         "retrievedAt": retrieved(), **(meta or {})})


def cmd_api():
    if mode() != "whm":
        out({"error": "wrong_mode", "mode": mode(), "message": "api runs in WHM mode (WHM_API_KEY)"}, 2)
    out({"mode": "whm", **whm_get(positional())[1]})


def cmd_invoke():
    """Count one use of this skill: main() already sent the usage ping as event=invoke. No key,
    nothing from the conversation is sent."""
    if os.environ.get("WHM_USAGE", "").strip() == "0":
        out({"reached": False, "skipped": "WHM_USAGE=0"})
    status = usage_wait() or 0
    out({"reached": status == 200, "status": status, "route": "/health",
         "sent": {"client": "whm-skills", "skill": SKILL, "v": VERSION, "event": "invoke",
                  "cmd": "invoke", "mode": usage_mode()}})


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    usage_ping(cmd)
    {"mode": cmd_mode, "lookup": cmd_lookup, "photos": cmd_photos, "api": cmd_api, "invoke": cmd_invoke}.get(
        cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
