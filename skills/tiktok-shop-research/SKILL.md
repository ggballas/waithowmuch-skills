---
name: tiktok-shop-research
description: Find out what a brand sells and advertises on TikTok - its TikTok Shop revenue, units and month-by-month sales, the split between its own posts, paid creators and the shop page, which creators and videos drive it, which videos run as ads (with ROAS), follower counts, a post's date, and TikTok's public ad library. Use when the user asks whether a brand or competitor sells on TikTok Shop, how much it makes there, who promotes it, whether it runs TikTok ads, or whether a sales spike came from a TikTok video. US, UK and about 14 other TikTok Shop markets.
---

# TikTok Shop and TikTok ads, from outside

**Nothing here is the seller's own number.** Kalodata estimates TikTok Shop sales from public data (USD).
The ad library shows ads, never spend. Say both are third-party estimates, give the date range, and
never add TikTok revenue into an Amazon figure.

## Keys and mode

Helper: `scripts/whm.py` (Python 3, no dependencies). It never prints keys; don't echo one.
`python3 scripts/whm.py mode` says which keys are set.

| mode | used when | serves |
|---|---|---|
| WaitHowMuch | `WHM_API_KEY` set | not live yet: every Kalodata command returns `whm_route_not_live` |
| Direct | `KALODATA_API_KEY` set | everything, on the user's Kalodata credits (~$0.01 a call) |

With both set, WHM answers first and Kalodata fills the gap. Neither → `no_keys`: tell the user,
briefly, to set **either** key, then stop. `post` and `adlib` need no key.

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## Commands

```bash
python3 scripts/whm.py shops "<brand>"    [--region US|GB|...] [--date last30Day]  # top 10 shops, 0.1 credit
python3 scripts/whm.py products "<brand>" [--region ..] [--date ..]   # top 10 products, 0.1
python3 scripts/whm.py shop <shop_id> [--date ..]                     # one shop, 0.1
python3 scripts/whm.py shop <shop_id> --months 12                     # month by month, 0.1 x N
python3 scripts/whm.py product <product_id>                           # one listing + its shop_id, 0.1
python3 scripts/whm.py videos --shop <shop_id>                        # top videos, ad flag, ROAS, 0.1
python3 scripts/whm.py creators --shop <shop_id>                      # top creators, 0.1
python3 scripts/whm.py creator <creator_id>                           # followers, revenue, 0.1
python3 scripts/whm.py video <video_id | TikTok URL>                  # views, revenue, ad spend signals, 0.1
python3 scripts/whm.py post <TikTok video URL>                        # post date (+ caption), free
python3 scripts/whm.py adlib "<advertiser legal name>" [--days 365]   # ad library link, free
python3 scripts/whm.py balance                                        # credits left, free
```

`--date`: `last7Day` … `last365Day`, a month `2026-09`, or `2026-09-01~2026-09-30`. Default `last30Day`.

## Workflow

1. **Find the shop.** `shops "<brand>"` in `US`, and in `GB` if the brand is British or sells there.
   Then `products "<brand>"`. 🚨 Rank calls return only the top 10 and match fuzzily: filter the names,
   try other spellings ("100PICS" vs "100 pics"), and read a product's `product_shop_id` to find shops
   whose names don't match. A shop missing from a rank is **not** zero. Regions are separate shops.
2. **Size it.** `shop <id> --months 12` for the series (explicit zeros; the current month is partial).
   Use the shop's own figures, not the rank row: they can differ. Tell the user the credit cost before
   `--months` above 12.
3. **Who sells it.** `creators --shop <id>` and `videos --shop <id>`. A handle with
   `creator_status: BELONGED_TO_SELLER` (in `creator`) is the brand's own account. A large
   `affiliate_revenue` share means paid creators, not the brand's ads.
4. **Ads.** In `videos`/`video`: `ad: 1` = promoted, `ad_revenue_ratio`, `ads_roas`; `video` also gives
   `ad_cpa`, so `ad_cpa × sales_volumn` is a rough implied ad spend (label it Kalodata-derived).
   `adlib` gives the public library link: **EU, EEA and UK ads only**, so an empty result says
   nothing about the US. It matches the legal advertiser name.
5. **A spike.** `post <URL>` dates a post from its id, free. Line it up with the month in step 2 or an
   Amazon rank jump (offer `brand-outside-traffic` or `amazon-revenue-sales`).

The brand's profile page (bio, follower count) needs a logged-out browser; TikTok blocks plain fetches.
If you have a browser tool, read `#__UNIVERSAL_DATA_FOR_REHYDRATION__` →
`webapp.user-detail.userInfo` (`stats.followerCount`, `user.signature`, `user.ttSeller`). Otherwise use
`creator <id>` (`creator_followers`).

## Answer

- One line: does the brand sell on TikTok Shop, in which regions, under which shop name.
- Revenue for the period (a small month table when you ran `--months`), units, and the split: own
  account / creators / shop page. Number of creators and videos.
- Ads: promoted videos, ROAS, implied spend if read; the ad library line with its EU/UK caveat.
- Caveats in one line: Kalodata's estimate, dated; top-10 rank limits if the shop wasn't found.

## Errors (JSON `error`, non-zero exit)

- `whm_route_not_live` (`route` named): WaitHowMuch doesn't serve TikTok data yet; a Kalodata key covers it.
- `kalodata_credits_low`: top up at the `topUp` link. `kalodata_key_rejected`: wrong or inactive key.
- `kalodata_error` with `message` (e.g. "creator not found": `creator` needs the numeric id from
  `videos`/`creators`, not the @handle). `bad_id`, `bad_region`, `bad_date`: fix the input.
