#!/usr/bin/env python3
"""WaitHowMuch skills data helper, tiktok-shop-research: what a brand sells and advertises on TikTok.
TikTok Shop revenue, units and creators per shop and product (Kalodata Open API), a post's date and
caption (TikTok's public oEmbed), and a link into TikTok's public ad library.

Python 3 stdlib only. Prints JSON to stdout. Never prints or logs a key.

Mode, decided per run from the environment:
  1. WHM_API_KEY set      -> WaitHowMuch API (api.waithowmuch.com), key sent as X-WHM-Key
  2. KALODATA_API_KEY set -> Kalodata Open API directly (your credits; header secret-key)
  3. neither              -> {"error": "no_keys", ...}, exit 2
A WHM route that is not live yet returns {"error": "whm_route_not_live", "route": ...}; if
KALODATA_API_KEY is also set, the command falls back to Kalodata instead.

Commands (Kalodata: detail 0.1 credit, rank 0.1 credit per 100 rows; 1 credit ~ $0.10):
  mode                                         which mode this run would use (no provider call)
  balance                                      Kalodata credits left (free)
  shops "<keyword>"    [--region US] [--date last30Day]   top 10 shops for a keyword       (0.1)
  products "<keyword>" [--region US] [--date last30Day]   top 10 products for a keyword    (0.1)
  shop <shop_id>       [--region US] [--date last30Day | --months N]
                                               one shop's revenue split, creators, videos (0.1; --months: 0.1 x N)
  product <product_id> [--region US] [--date last30Day]   one product, its shop and split  (0.1)
  videos --shop <shop_id>   [--region US] [--date ...]    a shop's top videos, ad flag, ROAS (0.1)
  creators --shop <shop_id> [--region US] [--date ...]    a shop's top creators          (0.1)
  creator <creator_id> [--region US] [--date ...]         one creator: followers, revenue (0.1)
  video <video_id|URL> [--region US] [--date ...]         one video's views, revenue, ads (0.1) + post
  post <TikTok video URL>                      post date (from the id) and caption (oEmbed), free
  adlib "<advertiser legal name>" [--days 365] TikTok ad library link (EU/EEA/UK ads only), free
  api </v1/path?query>                         GET a WaitHowMuch API route (WHM mode only)

--date: lastDay, last7Day, last30Day, last60Day, last90Day, last180Day, last365Day,
        a month 2026-09, or a range 2026-09-01~2026-09-30.

Exit codes: 0 ok, 1 upstream/API error, 2 no keys / wrong mode / route not live, 3 out of credits, 4 bad input.
"""
import gzip
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

VERSION = "0.4.1"
WHM_API = os.environ.get("WHM_API_BASE", "").strip().rstrip("/") or "https://api.waithowmuch.com"
KALO = "https://www.kalodata.com/openapi/v1"
REGIONS = {"US", "GB", "ID", "TH", "VN", "MY", "PH", "SG", "SA", "MX", "BR", "ES", "DE", "FR", "IT", "JP"}
DATE_RE = re.compile(r"^(lastDay|last(7|30|60|90|180|365)Day|\d{4}-\d{2}|\d{4}-\d{2}-\d{2}~\d{4}-\d{2}-\d{2})$")

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

COMMANDS = {"adlib", "api", "balance", "creator", "creators", "mode", "post", "product", "products", "shop", "shops", "video", "videos"}
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

METHOD = ("Kalodata's estimate from public TikTok Shop data, in USD: not the seller's own figures. "
          "revenue splits into shopping mall (shop page / search), self account (the brand's own posts) "
          "and affiliate (creators paid on commission).")


def out(obj, code=0):
    print(json.dumps(obj, indent=1, ensure_ascii=False))
    sys.exit(code)


def has(var):
    return bool(os.environ.get(var, "").strip())


def mode():
    if has("WHM_API_KEY"):
        return "whm"
    if has("KALODATA_API_KEY"):
        return "kalodata"
    return "none"


NO_KEYS = {
    "error": "no_keys",
    "message": "Set ONE of: WHM_API_KEY (Option B: one WaitHowMuch API key) or KALODATA_API_KEY "
               "(Option A: your own Kalodata Open API key, https://api.waithowmuch.com/go/kalodata-api?from=tiktok-shop-research; "
               "about $0.01 a lookup in Kalodata credits). In Claude Code: /plugin > waithowmuch > "
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
    except Exception as e:  # noqa: BLE001  (network: never echo the request, it may hold a key)
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


def not_live(route):
    return {"mode": "whm", "error": "whm_route_not_live", "route": route,
            "note": "WaitHowMuch does not serve TikTok Shop data yet.",
            "fallback": "Set KALODATA_API_KEY too (Option A) and this command runs on your own Kalodata credits."}


def kalo(op, body):
    """POST a Kalodata Open API endpoint. Returns `data`."""
    payload = {"language": "en-US", "currency": "USD", **{k: v for k, v in body.items() if v is not None}}
    status, res = _fetch(f"{KALO}/tiktok/{op}", data=json.dumps(payload).encode(),
                         headers={"secret-key": os.environ["KALODATA_API_KEY"].strip(), "Content-Type": "application/json"})
    msg = (res.get("message") or "") if isinstance(res, dict) else ""
    if status in (401, 403) or re.search(r"secret|api key|unauthori", msg, re.I):
        out({"mode": "kalodata", "error": "kalodata_key_rejected", "status": status, "message": msg[:200]}, 1)
    if re.search(r"credit|point|balance|insufficient", msg, re.I):
        out({"mode": "kalodata", "error": "kalodata_credits_low", "message": msg[:200],
             "topUp": "https://api.waithowmuch.com/go/kalodata-api?from=tiktok-shop-research"}, 3)
    if status != 200 or not res.get("success"):
        out({"mode": "kalodata", "error": "kalodata_error", "status": status, "endpoint": op, "message": msg[:300]}, 1)
    return res.get("data")


def run(op, body, credits):
    """WHM first (if keyed), then the user's own Kalodata key."""
    route = f"/v1/tools/tiktok-shop/{op}"
    if mode() == "whm":
        q = urllib.parse.urlencode({k: v for k, v in body.items() if v is not None})
        status, res = whm_get(f"{route}?{q}", allow=(404,))
        if not route_missing(status, res):
            if status != 200:
                out({"mode": "whm", "status": status, **res}, 1)
            return "whm", res
        if not has("KALODATA_API_KEY"):
            out(not_live(route), 2)
    elif mode() == "none":
        out(NO_KEYS, 2)
    return "kalodata", {"data": kalo(op, body), "creditsSpent": credits}


# ─── Args ────────────────────────────────────────────────────────────

FLAGS_WITH_VALUE = {"--region", "--date", "--months", "--shop", "--days"}


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


def common():
    region = (arg("--region") or "US").upper()
    if region == "UK":
        region = "GB"
    if region not in REGIONS:
        out({"error": "bad_region", "valid": sorted(REGIONS)}, 4)
    d = arg("--date") or "last30Day"
    if not DATE_RE.match(d):
        out({"error": "bad_date", "valid": "lastDay, last7Day, last30Day, last60Day, last90Day, last180Day, last365Day, "
                                          "a month 2026-09, or a range 2026-09-01~2026-09-30"}, 4)
    return {"region": region, "date_range": d}


def need_id(raw, what):
    m = re.search(r"(\d{15,22})", raw or "")
    if not m:
        out({"error": "bad_id", "message": f"give a numeric Kalodata/TikTok {what} id (15-22 digits)"}, 4)
    return m.group(1)


def retrieved():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def wrap(md, op, body, res, extra=None):
    return {"mode": md, "endpoint": op, "query": body, **res, **(extra or {}),
            "method": METHOD, "retrievedAt": retrieved(), "source": "Kalodata Open API"}


# ─── Commands ────────────────────────────────────────────────────────

def cmd_balance():
    if not has("KALODATA_API_KEY"):
        out({"error": "no_kalodata_key", "message": "balance reads your own Kalodata credits: set KALODATA_API_KEY"}, 2)
    status, res = _fetch(f"{KALO}/credit/balance", headers={"secret-key": os.environ["KALODATA_API_KEY"].strip()})
    if status != 200 or not res.get("success"):
        out({"mode": "kalodata", "error": "kalodata_error", "status": status, "message": (res.get("message") or "")[:200]}, 1)
    d = res.get("data") or {}
    out({"mode": "kalodata", "creditsLeft": d.get("totalRemain"), "approxUsd": round((d.get("totalRemain") or 0) * 0.1, 2),
         "note": "1 credit is about $0.10 (Kalodata). Detail and rank calls cost 0.1 credit each."})


def cmd_rank(op):
    kw = positional()
    if not kw:
        out({"error": "empty", "message": "give a keyword: the brand or product name"}, 4)
    body = {**common(), "keyword": kw}
    md, res = run(op, body, 0.1)
    out(wrap(md, op, body, res, {"note": "Top 10 for the keyword only, and the match is fuzzy: filter the names "
                                         "yourself. A shop missing here is not zero; try other spellings, "
                                         "the other region, and products (a listing's shop id is in product)."}))


def months_back(n):
    today = date.today()
    y, m = today.year, today.month
    res = []
    for _ in range(n):
        res.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return list(reversed(res))


def cmd_shop():
    sid = need_id(positional(), "shop")
    months = arg("--months")
    if months:
        try:
            n = max(1, min(int(months), 24))
        except ValueError:
            out({"error": "bad_months"}, 4)
        base = common()
        rows, md = [], None
        for mo in months_back(n):
            body = {"region": base["region"], "date_range": mo, "shop_id": sid}
            md, res = run("shop/detail", body, 0.1)
            d = res.get("data") or {}
            rows.append({"month": mo, **{k: d.get(k) for k in (
                "revenue", "sales_volumn", "shoppingmall_revenue", "self_account_revenue", "affiliate_revenue",
                "creator_number", "video_number", "live_number")}})
            name = d.get("shop_name")
        tot = sum(r["revenue"] or 0 for r in rows)
        out({"mode": md, "endpoint": "shop/detail", "shop_id": sid, "shop_name": name, "region": base["region"],
             "months": rows, "totalRevenue": round(tot, 2), "creditsSpent": round(0.1 * n, 2),
             "note": "The current month is partial. A month of 0 is an explicit zero from Kalodata.",
             "method": METHOD, "retrievedAt": retrieved(), "source": "Kalodata Open API"})
    body = {**common(), "shop_id": sid}
    md, res = run("shop/detail", body, 0.1)
    out(wrap(md, "shop/detail", body, res))


def cmd_detail(op, key, what):
    raw = positional()
    vid = need_id(raw, what)
    body = {**common(), key: vid}
    md, res = run(op, body, 0.1)
    extra = {}
    if op == "video/detail":
        extra["post"] = post_info(vid, raw if raw.startswith("http") else None)
    out(wrap(md, op, body, res, extra))


def cmd_by_shop(op):
    sid = need_id(arg("--shop") or positional(), "shop")
    body = {**common(), "shop_id": sid}
    md, res = run(op, body, 0.1)
    note = ("ad = 1 marks a video Kalodata saw promoted; ad_revenue_ratio is the share of its revenue from ads, "
            "ads_roas Kalodata's estimate. belonged_creator_handle tells the brand's own account from paid creators."
            if op == "video/rank" else
            "Creators ranked by revenue they drove for this shop. The brand's own account usually shows here too.")
    out(wrap(md, op, body, res, {"note": note}))


def post_info(vid, url=None):
    when = datetime.fromtimestamp(int(vid) >> 32, timezone.utc)
    res = {"video_id": vid, "postedAt": when.isoformat(timespec="seconds")}
    if url:
        status, o = _fetch("https://www.tiktok.com/oembed?" + urllib.parse.urlencode({"url": url}))
        if status == 200 and isinstance(o, dict):
            res.update({"caption": o.get("title"), "author": o.get("author_unique_id") or o.get("author_name"),
                        "authorUrl": o.get("author_url")})
    return res


def cmd_post():
    url = positional()
    m = re.search(r"tiktok\.com/@([\w.]+)/(?:video|photo)/(\d{15,22})", url or "")
    if not m:
        out({"error": "bad_url", "message": "give a full https://www.tiktok.com/@handle/video/<id> link"}, 4)
    info = post_info(m.group(2), url)
    info.setdefault("author", m.group(1))
    out({"mode": "public", **info, "source": "TikTok oEmbed + the date encoded in the video id",
         "note": "Views and likes are not in oEmbed: `video <id>` (Kalodata, 0.1 credit) or open the page in a browser."})


def cmd_adlib():
    name = positional()
    if not name:
        out({"error": "empty", "message": "give the advertiser's legal name (the company, e.g. POPTACULAR LTD)"}, 4)
    days = int(arg("--days") or 365)
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    q = {"region": "all", "start_time": end - days * 86_400_000, "end_time": end, "adv_name": name, "query_type": 1}
    out({"mode": "public", "url": "https://library.tiktok.com/ads?" + urllib.parse.urlencode(q),
         "coverage": "EU, EEA and UK ads only: US ads are NOT in TikTok's library, so an empty result says nothing about the US.",
         "howToRead": "Open it in a browser and scroll; each card gives the advertiser, first and last shown dates and a "
                      "unique-users band, never spend. adv_name matches the legal advertiser name only.",
         "usAds": "For US ads use `videos --shop <id>` (Kalodata's ad flag) or TikTok Creative Center Top Ads (incomplete)."})


def cmd_api():
    if mode() != "whm":
        out({"error": "wrong_mode", "mode": mode(), "message": "api runs in WHM mode (WHM_API_KEY)"}, 2)
    out({"mode": "whm", **whm_get(positional())[1]})


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    usage_ping(cmd)
    if cmd == "mode":
        md = mode()
        out({"mode": md, "keys": {"WHM_API_KEY": has("WHM_API_KEY"), "KALODATA_API_KEY": has("KALODATA_API_KEY")},
             **({} if md != "none" else NO_KEYS), "free": ["post", "adlib"], "skill": SKILL, "version": VERSION})
    {"balance": cmd_balance,
     "shops": lambda: cmd_rank("shop/rank"),
     "products": lambda: cmd_rank("product/rank"),
     "shop": cmd_shop,
     "product": lambda: cmd_detail("product/detail", "product_id", "product"),
     "creator": lambda: cmd_detail("creator/detail", "creator_id", "creator"),
     "video": lambda: cmd_detail("video/detail", "video_id", "video"),
     "videos": lambda: cmd_by_shop("video/rank"),
     "creators": lambda: cmd_by_shop("creator/rank"),
     "post": cmd_post, "adlib": cmd_adlib, "api": cmd_api}.get(
        cmd, lambda: out({"error": "usage", "message": __doc__}, 4))()


if __name__ == "__main__":
    main()
