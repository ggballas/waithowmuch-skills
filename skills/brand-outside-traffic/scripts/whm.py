#!/usr/bin/env python3
"""WaitHowMuch skills data helper, brand-outside-traffic: how much attention a brand gets OUTSIDE Amazon,
where it comes from, and whether it shows up on Amazon.

Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key (Similarweb and Keepa take
their keys in the query string, so no request URL is ever printed).

Mode, decided per run from the environment:
  1. WHM_API_KEY set -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
  2. your own keys   -> Similarweb (SIMILARWEB_API_KEY), DataForSEO (DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD),
                        Keepa (KEEPA_API_KEY); each command uses the ones it needs
  3. neither         -> {"error": "no_keys", ...}, exit 2   (site and youtube need no key)
A WHM route that is not live yet returns {"error": "whm_route_not_live", "route": ...}; if a matching
own key is also set, the command falls back to it instead.

Commands:
  mode                               which mode this run would use (no provider call)
  researched "<brand>"               WaitHowMuch's researched readings for a case-study brand (WHM, live)
  site <domain|URL>                  own store: platform, social links, links to Amazon (free)
  traffic <domain> [--months 6]      site visits + channel mix (Similarweb, ~2 API calls) and/or
                                     Google organic/paid traffic estimate (DataForSEO, ~$0.012)
  brand-search "<brand>" [--also "variant,variant"]
                                     Google US monthly searches for the brand name, 12-month history
                                     (DataForSEO, ~$0.012)
  youtube <@handle|channel URL>      subscribers and video count (free)
  spikes <ASIN> [--days 730]         dates the Amazon rank jumped, to line up with off-Amazon moments
                                     (Keepa: 1 token)
  api </v1/path?query>               GET a WaitHowMuch API route (WHM mode only)

Exit codes: 0 ok, 1 upstream/API error, 2 no keys / wrong mode / route not live, 3 not enough tokens, 4 bad input.
"""
import base64
import gzip
import html as htmlmod
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

VERSION = "0.4.1"
WHM_API = os.environ.get("WHM_API_BASE", "").strip().rstrip("/") or "https://api.waithowmuch.com"
KEEPA = "https://api.keepa.com"
SIMILARWEB = "https://api.similarweb.com"
DFS = "https://api.dataforseo.com/v3"
KEEPA_EPOCH_MIN = 21_564_000  # Keepa time = minutes since 2011-01-01 UTC
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

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

COMMANDS = {"api", "brand-search", "mode", "researched", "site", "spikes", "traffic", "youtube"}
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
    return {"similarweb": has("SIMILARWEB_API_KEY"),
            "dataforseo": has("DATAFORSEO_LOGIN") and has("DATAFORSEO_PASSWORD"),
            "keepa": has("KEEPA_API_KEY")}


def mode():
    if has("WHM_API_KEY"):
        return "whm"
    if any(own().values()):
        return "own"
    return "none"


NO_KEYS = {
    "error": "no_keys",
    "message": "Set ONE of: WHM_API_KEY (Option B: one WaitHowMuch API key) or your own provider keys "
               "(Option A): SIMILARWEB_API_KEY (Similarweb API plan) for site visits and channel mix, "
               "DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD (pay as you go, ~$0.012 a lookup) for search traffic and "
               "brand searches, KEEPA_API_KEY (paid Keepa API plan) for Amazon rank spikes. In Claude Code: "
               "/plugin > waithowmuch > Configure options. Elsewhere: environment variables. "
               "https://github.com/ggballas/waithowmuch-skills#data-providers",
    "free": "site and youtube work without a key.",
}


# ─── HTTP ────────────────────────────────────────────────────────────

def _fetch(url, headers=None, data=None, raw_text=False):
    req = urllib.request.Request(url, data=data, headers={"Accept-Encoding": "gzip", "User-Agent": f"whm-skills/{VERSION}",
                                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            if raw_text:
                return r.status, raw.decode("utf-8", "replace"), r.geturl()
            return r.status, json.loads(raw or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            if e.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            body = raw.decode("utf-8", "replace") if raw_text else json.loads(raw or b"{}")
        except Exception:  # noqa: BLE001
            body = "" if raw_text else {}
        return (e.code, body, url) if raw_text else (e.code, body)
    except Exception as e:  # noqa: BLE001  (network: never echo the URL, it may hold a key)
        return (0, "", url) if raw_text else (0, {"error": "unreachable", "detail": type(e).__name__})


def page(url):
    return _fetch(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html", "Accept-Language": "en-US"}, raw_text=True)


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


def try_whm(route, query, fallback_ok, fallback_msg):
    """WHM first. Returns the body if the route is live, None to fall back; exits when there is no fallback."""
    if mode() != "whm":
        return None
    status, body = whm_get(f"{route}?{urllib.parse.urlencode(query)}", allow=(404,))
    if not route_missing(status, body):
        if status != 200:
            out({"mode": "whm", "status": status, **body}, 1)
        return body
    if not fallback_ok:
        out({"mode": "whm", "error": "whm_route_not_live", "route": route,
             "note": "WaitHowMuch does not serve this for an unresearched brand yet "
                     "(try `researched` for a case-study brand).", "fallback": fallback_msg}, 2)
    return None


def retrieved():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─── Args ────────────────────────────────────────────────────────────

FLAGS_WITH_VALUE = {"--months", "--also", "--days"}


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


def domain_of(raw):
    s = (raw or "").strip()
    host = urllib.parse.urlparse(s if re.match(r"^https?://", s, re.I) else "https://" + s).hostname or ""
    host = host.lower().removeprefix("www.")
    if not re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$", host):
        out({"error": "bad_domain", "message": "give the brand's website, e.g. mount-cleverest.com"}, 4)
    if re.search(r"(^|\.)amazon\.|(^|\.)amzn\.", host):
        out({"error": "bad_domain", "message": "that is Amazon; give the brand's OWN website"}, 4)
    return host


# ─── researched (WHM) ────────────────────────────────────────────────

def cmd_researched():
    name = positional()
    if mode() != "whm":
        out({"error": "wrong_mode", "mode": mode(), "message": "researched reads WaitHowMuch's case studies: set WHM_API_KEY"}, 2)
    _, body = whm_get("/v1/businesses?limit=100")
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())  # noqa: E731
    q = norm(name)
    hit = next((b for b in body.get("businesses") or [] if q and q in (norm(b.get("name")), norm(b.get("slug")))), None)
    if not hit:
        out({"mode": "whm", "researched": False, "brand": name,
             "note": "Not a WaitHowMuch case study. Use site / traffic / brand-search / youtube instead."})
    _, d = whm_get(f"/v1/businesses/{urllib.parse.quote(hit['slug'])}")
    b = d.get("business") or d
    out({"mode": "whm", "researched": True, "brand": b.get("name"), "country": b.get("country"),
         "links": [{"platform": x.get("platform"), "url": x.get("url"), "handle": x.get("handle"), **(x.get("meta") or {})}
                   for x in b.get("links") or []],
         "events": [{"date": e.get("date"), "title": e.get("title"), "track": e.get("track")} for e in b.get("events") or []],
         "caseStudy": f"https://waithowmuch.com/business/{hit['slug']}/?utm_source=whm-skills&utm_medium=skill"
                      f"&utm_campaign=whm-skills&utm_content={SKILL}",
         "method": "Readings taken by WaitHowMuch's researchers; each carries its source and, where given, the date read.",
         "retrievedAt": retrieved()})


# ─── site (free) ─────────────────────────────────────────────────────

SOCIAL = {
    "tiktok": r"tiktok\.com/@[\w.]+", "instagram": r"instagram\.com/[\w.]+", "youtube": r"youtube\.com/(?:@[\w.-]+|c/[\w.-]+|channel/[\w-]+|user/[\w.-]+)",
    "facebook": r"facebook\.com/[\w.-]+", "x": r"(?:twitter|x)\.com/[\w]+", "pinterest": r"pinterest\.com/[\w.-]+",
    "linkedin": r"linkedin\.com/company/[\w.-]+", "threads": r"threads\.net/@[\w.]+",
}
SKIP_HANDLES = re.compile(r"/(sharer|share|intent|plugins|tr|dialog|p|reel|watch|embed|hashtag)(?:[/?.]|$)", re.I)


def cmd_site():
    dom = domain_of(positional())
    status, html, final = page(f"https://{dom}/")
    if status != 200 or not html:
        out({"mode": "public", "domain": dom, "error": "site_unreachable", "status": status,
             "message": "The homepage did not load (blocked, down or a bot check). Open it in a browser if you have one."}, 1)
    low = html.lower()
    socials = {}
    for k, pat in SOCIAL.items():
        found = []
        for m in re.finditer(r"https?://(?:www\.|m\.)?" + pat, html, re.I):
            u = m.group(0).rstrip("/.")
            if not SKIP_HANDLES.search(u) and u not in found:
                found.append(u)
        if found:
            socials[k] = found[:3]
    amazon = []
    for m in re.finditer(r"https?://(?:www\.)?(?:amazon\.[a-z.]+|amzn\.to|a\.co)/[^\s\"'<>]*", html, re.I):
        u = m.group(0)
        if u not in amazon:
            amazon.append(u)
    platform = ("Shopify" if "cdn.shopify.com" in low or "shopify.theme" in low else
                "WooCommerce" if "woocommerce" in low else "BigCommerce" if "bigcommerce" in low else
                "Wix" if "wixstatic.com" in low else "Squarespace" if "squarespace" in low else None)
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    out({"mode": "public", "domain": dom, "finalUrl": final,
         "title": htmlmod.unescape(re.sub(r"\s+", " ", title.group(1)).strip())[:160] if title else None,
         "platform": platform,
         "sellsDirect": bool(re.search(r"add[ -]to[ -]cart|/cart\b|checkout", low)),
         "socials": socials,
         "amazonLinks": {"count": len(amazon), "sample": amazon[:5],
                         "buyOnAmazonText": bool(re.search(r"(buy|shop|available|find us) (it )?on amazon", low)),
                         "amazonAttribution": any(re.search(r"maas=|aa_maas", u, re.I) for u in amazon)},
         "note": "Homepage only, as served to a logged-out visitor; links injected by scripts are missed. "
                 "Amazon links on the brand's own site are the off-Amazon -> Amazon signal; amazonAttribution "
                 "(a maas= tag) means they measure that traffic with Amazon Attribution, which usually also "
                 "earns Amazon's Brand Referral Bonus.",
         "retrievedAt": retrieved()})


# ─── traffic (Similarweb / DataForSEO) ───────────────────────────────

def similarweb(dom, months):
    key = os.environ["SIMILARWEB_API_KEY"].strip()
    today = date.today().replace(day=1)
    end = today - timedelta(days=1)  # last full month
    start = date(end.year, end.month, 1)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    q = {"api_key": key, "start_date": start.strftime("%Y-%m"), "end_date": end.strftime("%Y-%m"),
         "country": "world", "granularity": "monthly", "main_domain_only": "false", "format": "json"}
    res = {}
    for name, path in (("visits", "total-traffic-and-engagement/visits"), ("channels", "traffic-sources/overview-share")):
        status, body = _fetch(f"{SIMILARWEB}/v1/website/{dom}/{path}?{urllib.parse.urlencode(q)}")
        if status in (401, 403) or (isinstance(body, dict) and "invalid api key" in json.dumps(body).lower()):
            return {"error": "similarweb_key_rejected", "status": status,
                    "message": "Similarweb refused the key (invalid, or the plan lacks API access / this endpoint)."}
        if status != 200:
            res[name] = {"error": "similarweb_error", "status": status,
                         "message": (body.get("meta") or {}).get("error_message") if isinstance(body, dict) else None}
            continue
        if name == "visits":
            rows = [{"month": v.get("date", "")[:7], "visits": round(v.get("visits") or 0)} for v in body.get("visits") or []]
            res["visits"] = rows
            if rows:
                res["avgMonthlyVisits"] = round(sum(r["visits"] for r in rows) / len(rows))
        else:
            res["channels"] = body.get("visits") or body
    return {"source": "Similarweb API (panel and clickstream estimate)", **res}


def dataforseo(path, payload):
    login, pw = os.environ["DATAFORSEO_LOGIN"].strip(), os.environ["DATAFORSEO_PASSWORD"].strip()
    auth = base64.b64encode(f"{login}:{pw}".encode()).decode()
    status, body = _fetch(f"{DFS}/{path}", data=json.dumps(payload).encode(),
                          headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"})
    if status == 401 or (isinstance(body, dict) and body.get("status_code") == 40100):
        out({"mode": "own", "error": "dataforseo_key_rejected", "status": status}, 1)
    if status == 402 or (isinstance(body, dict) and body.get("status_code") == 40200):
        out({"mode": "own", "error": "dataforseo_balance_low", "message": "Top up at dataforseo.com"}, 3)
    task = ((body or {}).get("tasks") or [{}])[0]
    if status != 200 or task.get("status_code") != 20000:
        out({"mode": "own", "error": "dataforseo_error", "status": status,
             "message": task.get("status_message") or body.get("status_message")}, 1)
    return task.get("result") or [], task.get("cost")


def cmd_traffic():
    dom = domain_of(positional())
    months = int_arg("--months", 6, 1, 24)
    keys = own()
    hit = try_whm("/v1/tools/brand-traffic", {"domain": dom, "months": months}, keys["similarweb"] or keys["dataforseo"],
                  "Set SIMILARWEB_API_KEY or DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD too (Option A) and this runs on your own keys.")
    if hit is not None:
        out({"mode": "whm", **hit})
    if not (keys["similarweb"] or keys["dataforseo"]):
        out({**NO_KEYS, "needs": "SIMILARWEB_API_KEY and/or DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD",
             "freeFallback": f"Similarweb's public page https://www.similarweb.com/website/{dom}/ shows "
                             "'Total Visits Last 3 Months': divide by 3 for a monthly figure."}, 2)
    res = {"mode": "own", "domain": dom}
    if keys["similarweb"]:
        res["similarweb"] = similarweb(dom, months)
    if keys["dataforseo"]:
        result, cost = dataforseo("dataforseo_labs/google/domain_rank_overview/live",
                                  [{"target": dom, "location_code": 2840, "language_code": "en"}])
        items = (result[0].get("items") if result else None) or []
        m = (items[0].get("metrics") if items else {}) or {}
        pick = lambda x: {"estVisitsPerMonth": round((x or {}).get("etv") or 0), "keywords": (x or {}).get("count"),  # noqa: E731
                          "top3": sum((x or {}).get(k) or 0 for k in ("pos_1", "pos_2_3")),
                          "trafficValueUsd": round((x or {}).get("estimated_paid_traffic_cost") or 0)}
        res["googleSearch"] = {"source": "DataForSEO Labs (Google US, modelled from rankings x search volume)",
                               "organic": pick(m.get("organic")), "paid": pick(m.get("paid")),
                               "found": bool(items), "costUsd": cost}
    res["method"] = ("Similarweb visits are a panel estimate for the whole site, all countries. DataForSEO is "
                     "Google US search only: organic visits it models from rankings, and paid = Google Ads keywords "
                     "it saw. Neither is the brand's analytics.")
    res["retrievedAt"] = retrieved()
    out(res)


def cmd_brand_search():
    name = positional()
    if not name:
        out({"error": "empty", "message": "give the brand name"}, 4)
    kws = [name] + [k.strip() for k in (arg("--also") or "").split(",") if k.strip()]
    kws = list(dict.fromkeys(k.lower() for k in kws))[:10]
    hit = try_whm("/v1/tools/brand-search", {"q": ",".join(kws)}, own()["dataforseo"],
                  "Set DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD too (Option A) and this runs on your own key.")
    if hit is not None:
        out({"mode": "whm", **hit})
    if not own()["dataforseo"]:
        out({**NO_KEYS, "needs": "DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD"}, 2)
    result, cost = dataforseo("dataforseo_labs/google/keyword_overview/live",
                              [{"keywords": kws, "location_code": 2840, "language_code": "en"}])
    rows = []
    for it in ((result[0].get("items") if result else None) or []):
        ki = it.get("keyword_info") or {}
        hist = sorted(({"month": f"{m['year']}-{m['month']:02d}", "searches": m.get("search_volume")}
                       for m in ki.get("monthly_searches") or []), key=lambda r: r["month"])
        rows.append({"keyword": it.get("keyword"), "searchesPerMonth": ki.get("search_volume"),
                     "cpcUsd": ki.get("cpc"), "history": hist})
    found = {r["keyword"] for r in rows}
    out({"mode": "own", "keywords": rows, "notFound": [k for k in kws if k not in found], "costUsd": cost,
         "source": "DataForSEO Labs (Google Ads search volume, Google US)",
         "note": "People typing the brand into Google is demand the brand created off Amazon. "
                 "A keyword missing here has too little volume to be listed (under ~10 a month).",
         "retrievedAt": retrieved()})


# ─── youtube (free) ──────────────────────────────────────────────────

def cmd_youtube():
    raw = positional()
    m = re.search(r"youtube\.com/((?:@[\w.-]+)|(?:channel/[\w-]+)|(?:c/[\w.-]+)|(?:user/[\w.-]+))", raw or "")
    path = m.group(1) if m else (raw if raw.startswith("@") else ("@" + raw if re.match(r"^[\w.-]+$", raw or "") else None))
    if not path:
        out({"error": "bad_channel", "message": "give a YouTube @handle or channel URL"}, 4)
    status, html, _ = page(f"https://www.youtube.com/{path}")
    if status == 404:
        out({"mode": "public", "error": "channel_not_found", "channel": path}, 1)
    if status != 200:
        out({"mode": "public", "error": "youtube_unreachable", "status": status}, 1)
    subs = re.search(r'"content":"([^"]{1,20}) subscribers?"', html)
    vids = re.search(r'"content":"([^"]{1,20}) videos?"', html)
    name = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    cid = re.search(r'"externalId":"(UC[\w-]+)"', html)
    out({"mode": "public", "channel": path, "name": htmlmod.unescape(name.group(1)) if name else None,
         "channelId": cid.group(1) if cid else None,
         "subscribers": subs.group(1) if subs else None, "subscribersApprox": parse_count(subs.group(1)) if subs else None,
         "videos": vids.group(1) if vids else None,
         "url": f"https://www.youtube.com/{path}", "source": "YouTube channel page (YouTube rounds the count)",
         "retrievedAt": retrieved()})


def parse_count(s):
    m = re.match(r"^([\d.,]+)\s*([KMB]?)", (s or "").strip(), re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return round(n * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2).upper()])


# ─── spikes (Keepa) ──────────────────────────────────────────────────

ASIN_RE = re.compile(r"^(?:B0[A-Z0-9]{8}|\d{9}[\dX])$")


def parse_asin(raw):
    s = (raw or "").strip()
    if ASIN_RE.match(s.upper()):
        return s.upper()
    m = re.search(r"amazon\.com/.*?/(?:dp|gp/product)/([A-Z0-9]{10})", s, re.I)
    if m:
        return m.group(1).upper()
    out({"error": "invalid_asin", "message": "give a 10-character ASIN or a full amazon.com product link"}, 4)


def kday(minute):
    return (datetime(2011, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minute)).date()


def daily(pairs, start):
    """Keepa [t, v, t, v, ...] -> {date: last value that day}, carried forward, from `start`."""
    pts = {}
    for i in range(0, len(pairs) - 1, 2):
        if pairs[i + 1] is not None and pairs[i + 1] > 0:
            pts[kday(pairs[i])] = pairs[i + 1]
    if not pts:
        return {}
    cur, d, res = None, min(pts), {}
    while d <= date.today():
        cur = pts.get(d, cur)
        if d >= start and cur:
            res[d] = cur
        d += timedelta(days=1)
    return res


def cmd_spikes():
    asin = parse_asin(positional())
    days = int_arg("--days", 730, 60, 1500)
    hit = try_whm("/v1/tools/rank-spikes", {"asin": asin, "days": days}, own()["keepa"],
                  "Set KEEPA_API_KEY too (Option A) and this runs on your own Keepa key (1 token).")
    if hit is not None:
        out({"mode": "whm", **hit})
    if not own()["keepa"]:
        out({**NO_KEYS, "needs": "KEEPA_API_KEY"}, 2)
    qs = urllib.parse.urlencode({"key": os.environ["KEEPA_API_KEY"].strip(), "domain": 1, "asin": asin,
                                 "history": 1, "days": days})
    status, r = _fetch(f"{KEEPA}/product?{qs}")
    if status == 429:
        out({"mode": "own", "error": "keepa_tokens_low", "tokensLeft": r.get("tokensLeft"),
             "refillInSec": round((r.get("refillIn") or 60000) / 1000)}, 3)
    if status in (401, 402, 403):
        out({"mode": "own", "error": "keepa_key_rejected", "status": status}, 1)
    if status != 200:
        out({"mode": "own", "error": "keepa_error", "status": status}, 1)
    p = (r.get("products") or [None])[0]
    if not p or not p.get("csv"):
        out({"mode": "own", "error": "asin_not_found", "asin": asin, "tokensConsumed": r.get("tokensConsumed")}, 1)
    start = date.today() - timedelta(days=days)
    rank = daily((p.get("csv") or [None] * 4)[3] or [], start)
    ds = sorted(rank)
    events = []
    for i, d in enumerate(ds):
        if i < 7 or i + 14 >= len(ds):
            continue
        before = statistics.median(rank[x] for x in ds[i - 7:i])
        after = statistics.median(rank[x] for x in ds[i:i + 14])
        if before >= 3 * after and before > 200:
            events.append({"date": d.isoformat(), "rankBefore": round(before), "rankAfter": round(after),
                           "factor": round(before / after, 1)})
    merged = []  # keep the strongest day of each run of consecutive hits
    for e in events:
        if merged and (date.fromisoformat(e["date"]) - date.fromisoformat(merged[-1]["date"])).days <= 10:
            if e["factor"] > merged[-1]["factor"]:
                merged[-1] = e
        else:
            merged.append(e)
    badge, seen = [], []  # a jump = the badge at least doubles the highest it showed in the 30 days before
    h = p.get("monthlySoldHistory") or []
    for i in range(0, len(h) - 1, 2):
        d, v = kday(h[i]), h[i + 1]
        if not v or v <= 0:
            continue
        seen = [(x, y) for x, y in seen if (d - x).days <= 30]
        top = max((y for _, y in seen), default=None)
        if top and v >= 2 * top and d >= start:
            badge.append({"date": d.isoformat(), "badgeFrom": top, "badgeTo": v})
        seen.append((d, v))
    out({"mode": "own", "asin": asin, "title": (p.get("title") or "")[:120], "brand": p.get("brand"),
         "rankNow": rank[ds[-1]] if ds else None, "rankSpikes": sorted(merged, key=lambda e: -e["factor"])[:10],
         "badgeJumps": badge[-10:],
         "method": "A spike = the 14-day median sales rank at least 3x better than the 7 days before (rank above "
                   "200 before). Badge jumps = Amazon's 'bought in past month' at least doubling. Match the dates "
                   "against posts, press, TV or brand-search months; a rank jump with no Amazon cause (deal, ads, "
                   "price cut) points to outside traffic. Correlation, not proof.",
         "source": "Keepa", "tokensConsumed": r.get("tokensConsumed"), "tokensLeft": r.get("tokensLeft"),
         "retrievedAt": retrieved()})


def cmd_api():
    if mode() != "whm":
        out({"error": "wrong_mode", "mode": mode(), "message": "api runs in WHM mode (WHM_API_KEY)"}, 2)
    out({"mode": "whm", **whm_get(positional())[1]})


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    usage_ping(cmd)
    if cmd == "mode":
        md = mode()
        out({"mode": md, "keys": {"WHM_API_KEY": has("WHM_API_KEY"), **{k: v for k, v in own().items()}},
             **({} if md != "none" else NO_KEYS), "free": ["site", "youtube"], "skill": SKILL, "version": VERSION})
    {"researched": cmd_researched, "site": cmd_site, "traffic": cmd_traffic, "brand-search": cmd_brand_search,
     "youtube": cmd_youtube, "spikes": cmd_spikes, "api": cmd_api}.get(
        cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
