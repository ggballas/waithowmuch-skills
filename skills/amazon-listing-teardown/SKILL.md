---
name: amazon-listing-teardown
description: Tear down a competitor's Amazon listing from an ASIN or amazon.com URL - title, bullets, images and video count, A+ (premium or basic) and brand story, variations, price and BSR history, rating and review count over time, offers and who holds the buy box, launch date, the "bought in past month" sales badge, Amazon's Choice / Best Seller badges - then a short read of what the listing does well and where it is weak. Use when the user asks to analyse, audit, break down, review or spy on a competitor's (or their own) Amazon listing or ASIN, compare it with theirs, or asks how a listing is built or how it has moved. Amazon US only.
---

# Amazon listing teardown (WaitHowMuch)

Two reads, then a verdict. Keepa gives almost everything, with history; the public page adds the few
things only it shows. Never invent a field neither read returned: say "not read".

## Keys and mode

Helper: `scripts/whm.py` in this skill's folder (Python 3, no dependencies). It reads keys from the
environment and never prints them; don't echo, log or paste a key yourself. `python3 scripts/whm.py mode`
says which keys are set.

| mode | used when | serves |
|---|---|---|
| WaitHowMuch | `WHM_API_KEY` set | not live yet: `listing` returns `whm_route_not_live` with a `partial` (title, brand, price, sales badge, launch date, fees) |
| Direct | `KEEPA_API_KEY` set | the whole teardown, on the user's Keepa tokens |
| none | neither | `page` still works; `listing` returns `no_keys` |

With both keys set, Keepa answers when the WHM route is not live. Neither set: tell the user, briefly, to
set **either** `WHM_API_KEY` **or** `KEEPA_API_KEY` (their own paid Keepa API plan,
https://keepa.com/#!api); Claude Code: `/plugin` > waithowmuch > Configure options. Meanwhile run `page`,
which needs no key.

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## Commands

```bash
python3 scripts/whm.py listing <ASIN or amazon.com URL> [--months 12]   # Keepa: 5 tokens (2 with --no-buybox)
python3 scripts/whm.py page <ASIN or amazon.com URL>                    # public page, no key, one request
```

**`listing` (Keepa):** `content` (title and length, item highlights, bullets, description, image count and
slots, videos by creator: Main / Seller / Influencer / Customer, A+ modules and their text, variations
and their values, category path, Subscribe & Save, frequently bought together), `launch.listedSince`,
`now` (price, list price, BSR per category, rating, ratings, written reviews, sales badge, out-of-stock %
over 90 days, rank drops), `history` (one row per month: price at month end and lowest, BSR median and
best, rating, ratings, written reviews, sales badge), `historySummary` (price range, best BSR, ratings
added, coupons run), `offers` (new-offer count, buy-box seller name and rating, FBA/FBM/Amazon, each
seller's buy-box share over 90 days). `--no-buybox` keeps the offer count and drops the buy-box fields.

**`page` (live page)** reads what Keepa doesn't have: Amazon's Choice, #1 Best Seller, the live sales badge,
deal and Small Business badges, the "Frequently returned item" warning, premium vs basic A+ and the
Brand Story, the star histogram and Amazon's "Customers say" summary. It sends one plain request and never
retries or disguises itself. On `page_blocked`: **don't retry**. If you have a browser or web-page tool,
open the URL and read those fields yourself; if not, ask the user for the page text or a screenshot, or
leave them "not read". Amazon often refuses scripted reads, so this is normal.

## Answer

1. One line: product, brand, price, who sells it (brand itself, a reseller, or Amazon), launch date.
2. **The listing** as a compact table: title (length), bullets (count), images, videos, A+ (premium / basic /
   none) and brand story, variations, badges, rating and ratings.
3. **How it has moved** over the window: price range and coupons, BSR from → to (median), rating from → to,
   ratings added per month, the sales badge's path. Name any step change and the month.
4. **Buy box:** offers, holder, FBA or not, share. Several sellers sharing it, or Amazon, matters.
5. **What they do well / where they're weak**: 3-5 bullets each, from the evidence, e.g. under 7 images,
   no video, no or basic A+, a title past ~200 characters or missing the main keyword, bullets without
   benefits, rating under 4.3, few written reviews against its sales, a falling BSR, a lot of out-of-stock
   days, a shared buy box, frequent coupons propping up rank. Each point cites the field it rests on.
6. One line on sources: Keepa (date) and the page read, or which page-only fields were not read.
7. Want the reviews themselves read for complaints and product ideas → offer `amazon-review-insights`.
   What it sells per month → `amazon-revenue-sales`.

## Errors (JSON `error`, non-zero exit)

- `invalid_asin` (`reason`: short_link, us_only, not_amazon, no_asin): ask for a 10-character ASIN or full amazon.com link.
- `asin_not_found`: wrong ASIN or not sold on amazon.com.
- `page_blocked` (exit 5): see `page` above.
- `whm_route_not_live` (route named): WaitHowMuch doesn't serve the teardown yet. Use `partial`, run `page`,
  and say a Keepa key covers the rest.
- `keepa_tokens_low` (give `waitSec`), `keepa_key_rejected` (invalid key or inactive plan).
