#!/usr/bin/env python3
"""WaitHowMuch skills data helper, amazon-review-insights: what buyers praise and complain about on an
Amazon listing, and how its rating and review count moved. One WHM API key, or your own Keepa key;
the page read needs no key.

Shared core (mode, HTTP, Keepa client) is the same in every skill's scripts/whm.py.
Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key
(Keepa takes its key in the query string, so no URL is ever printed).

What is obtainable (checked 2026-11-17):
  Keepa /product?rating=1   rating and ratings-count history (csv[16], csv[17]) and the WRITTEN review
                            count history (reviews.reviewCount). No review text: Keepa has none.
  public product page       star histogram, Amazon's AI "Customers say" summary of the review text, and
                            its aspects ("28 customers mention design, 25 positive, 3 negative") with
                            quoted snippets. Individual top reviews load by script, so a plain read has
                            none; a browser shows ~8-10. The full review list needs a sign-in: never.

Mode, decided per run from the environment:
  1. WHM_API_KEY set   -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
  2. KEEPA_API_KEY set -> Keepa API directly (your tokens)
  3. neither           -> {"error": "no_keys", ...}, exit 2   (`page` needs no key)
A WHM route that is not live yet returns {"error": "whm_route_not_live"}; if KEEPA_API_KEY is also
set, the command falls back to Keepa instead.

Commands:
  mode                                   which mode this run would use (no provider call)
  page <ASIN|URL> [<ASIN|URL> ...]       the review read off the public page, up to 5 listings: ONE plain
                                         request each, no key, no retry; stops at the first bot check
                                         (page_blocked) and the agent reads the page itself
  ratings <ASIN|URL> [--months N]        rating, ratings and written-review counts per month (Keepa: 2 tokens)
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
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VERSION = "0.4.1"
WHM_API = os.environ.get("WHM_API_BASE", "").strip().rstrip("/") or "https://api.waithowmuch.com"
KEEPA = "https://api.keepa.com"
US = 1
KEEPA_EPOCH_MIN = 21_564_000  # Keepa time = minutes since 2011-01-01 UTC

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

COMMANDS = {"api", "mode", "page", "ratings"}
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


# ─── Ratings over time ───────────────────────────────────────────────

def rating_history(p, n):
    now = datetime.now(timezone.utc)
    c = p.get("csv") or []
    rating = pairs(c[16] if len(c) > 16 else None)
    ratings = pairs(c[17] if len(c) > 17 else None)
    written = pairs((p.get("reviews") or {}).get("reviewCount"))
    rows, prev = [], None
    for label, start, end in months_back(n, now):
        r, rc, wr = at(rating, end), at(ratings, end), at(written, end)
        rc = rc if rc is not None and rc >= 0 else None
        before = at(ratings, start - 1)
        before = before if before is not None and before >= 0 else None
        rows.append({"month": label, "rating": r / 10 if r and r > 0 else None, "ratings": rc,
                     "netNewRatings": rc - before if rc is not None and before is not None else None,
                     "writtenReviews": wr if wr is not None and wr >= 0 else None})
    rows[-1]["live"] = True
    vals = [x["rating"] for x in rows if x["rating"]]
    return {
        "history": rows,
        "summary": {"months": len(rows), "ratingFirst": vals[0] if vals else None, "ratingNow": vals[-1] if vals else None,
                    "ratingLow": min(vals, default=None), "ratingHigh": max(vals, default=None),
                    "netRatingsAdded": sum(x["netNewRatings"] or 0 for x in rows),
                    "writtenShareNow": round(rows[-1]["writtenReviews"] / rows[-1]["ratings"], 3)
                    if rows[-1]["writtenReviews"] and rows[-1]["ratings"] else None},
    }


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

def cmd_ratings():
    raw, n = positional(), int_arg("--months", 12, 1, 36)
    if not raw:
        out({"error": "invalid_asin", "reason": "empty"}, 4)
    asin = parse_asin(raw)
    md = mode()
    if md == "none":
        out(NO_KEYS, 2)
    if md == "whm":
        status, body = whm_get("/v1/tools/review-insights?" + urllib.parse.urlencode({"asin": asin, "months": n}), allow=(404,))
        if status == 200:
            out({"mode": "whm", **body})
        if not has("KEEPA_API_KEY"):
            if route_missing(status, body):
                out(not_live("GET /v1/tools/review-insights?asin=&months=",
                             "WaitHowMuch has no rating-history route yet. The page read (`page`) needs no key and "
                             "carries the review content; the month-by-month rating needs KEEPA_API_KEY."), 2)
            out({"mode": "whm", "status": status, **body}, 1)
    k = Keepa()
    k.ensure(2)
    p = (k.call("product", {"asin": asin, "stats": 30, "history": 1, "rating": 1, "days": n * 31 + 31}).get("products") or [None])[0]
    if not p or (not p.get("title") and not p.get("categoryTree")):
        out({"mode": "keepa", "error": "asin_not_found", "asin": asin, **k.meta()}, 1)
    out({"mode": "keepa", "asin": asin, "url": f"https://www.amazon.com/dp/{asin}", "title": p.get("title"),
         "brand": p.get("brand"), "listedSince": kday(p.get("listedSince")), **rating_history(p, n),
         "note": "ratings = star ratings (with or without text); writtenReviews = reviews with text, the pool Amazon's "
                 "'Customers say' and its aspect counts are drawn from. Keepa has no review text.",
         "retrievedAt": retrieved(), "source": "Keepa", **k.meta()})


def cmd_page():
    raws = [a for a in sys.argv[2:] if not a.startswith("--")]
    if not raws:
        out({"error": "invalid_asin", "reason": "empty"}, 4)
    if len(raws) > 5:
        out({"error": "too_many", "message": "Up to 5 listings per run: this reads public pages one at a time, not in bulk."}, 4)
    asins, res = [parse_asin(r) for r in raws], []
    for i, asin in enumerate(asins):
        if i:
            time.sleep(3)  # one page at a time, politely
        status, h = page_fetch(asin)
        if status != 200 or any(b in h[:200000] for b in BLOCKED) or 'id="productTitle"' not in h:
            blocked = page_blocked(asin, status)
            if not res:
                out(blocked, 5)
            res.append({**blocked, "notRead": asins[i + 1:]})
            break
        res.append(page_parse(asin, h))
    out({"listings": res, "retrievedAt": retrieved()} if len(asins) > 1 else {**res[0], "retrievedAt": retrieved()})


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
    {"page": cmd_page, "ratings": cmd_ratings, "api": cmd_api}.get(
        cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
