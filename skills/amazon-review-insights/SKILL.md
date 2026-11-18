---
name: amazon-review-insights
description: What buyers praise and complain about on an Amazon listing, and product-improvement ideas from it - Amazon's own review summary and its aspects (how many customers mention each, positive vs negative, with quotes), the star histogram, visible top and critical reviews, and how the rating and review count moved month by month. Works on one ASIN or compares up to five competitors. Use when the user asks what customers like or hate about a product, common complaints, review analysis or sentiment, pain points, why a listing's rating is low, or how to make a better version of a competitor's product. Amazon US only.
---

# Amazon review insights (WaitHowMuch)

What buyers say, read from what is publicly visible without signing in, then turned into fixes. 🚨
**Be honest about the sample in every answer.** Four different bases; never mix them up:

| base | what it covers | source |
|---|---|---|
| **ratings** | every star rating, with or without text | Keepa, page |
| **written reviews** | ratings that came with text (often 10-20% of ratings) | Keepa |
| **"Customers say" + aspects** | Amazon's AI read of the written reviews; per aspect, how many mention it and how many positive / negative | public page |
| **visible reviews** | the ~8-10 "top reviews" a browser shows: chosen by helpfulness, skewed positive | browser only |

So "16 customers mention noise, 7 negative" is out of the written reviews (say how many there are), and a
handful of visible reviews is anecdote, never a percentage. Keepa has no review text at all. The full
review list and star filters need an Amazon sign-in: **never sign in, never get around a bot check, never
page through reviews in bulk.**

## Keys and mode

Helper: `scripts/whm.py` in this skill's folder (Python 3, no dependencies). It never prints keys; don't
echo one. `page` needs **no key**. `ratings` needs one:

- `KEEPA_API_KEY` (own paid Keepa plan, https://keepa.com/#!api): 2 tokens.
- `WHM_API_KEY`: the WaitHowMuch route isn't live yet, so `ratings` returns `whm_route_not_live` (or falls
  back to Keepa when both keys are set). Say so only if the user asks for the rating history.
- Neither: run `page` anyway; mention, once, that `WHM_API_KEY` or `KEEPA_API_KEY` adds the history
  (Claude Code: `/plugin` > waithowmuch > Configure options).

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## Commands

```bash
python3 scripts/whm.py page <ASIN or URL> [<ASIN or URL> ...]     # up to 5, one plain request each, no key
python3 scripts/whm.py ratings <ASIN or URL> [--months 12]       # Keepa: 2 tokens
```

- **`page`** returns `rating`, `ratings`, `starHistogramPct`, `customersSay` (Amazon's summary), `aspects`
  (`aspect`, `mentions`, `positive`, `negative`, `summary`, up to 4 `quotes`), plus badges. A listing with
  few written reviews has no `customersSay` or aspects: say so.
- **`page_blocked`** (exit 5): don't retry. With a browser or web-page tool, open the URL and read the same
  things yourself: the histogram, "Customers say" and each aspect chip (click it for the positive / negative
  split and quotes), then the visible top reviews. Without one, ask the user to paste that part of the page.
- **Browser only, optional:** the visible top reviews. Note each one's stars, date, verified or not and the
  main point; don't open more pages to get more.
- **`ratings`**: per month `rating`, `ratings`, `netNewRatings` (Amazon removes some, so it can be
  negative), `writtenReviews`; `summary` with the rating's range and `writtenShareNow`.

## Answer

1. One line: product, rating, ratings, written reviews, and the base each figure below is out of.
2. **Praise** and **complaints**: from the aspects, biggest first, each with "N mention, X negative" and one
   short quote. Mixed aspects (e.g. noise 9 / 7) go in both and are often the best opportunity.
3. **Trend** (if `ratings` ran): rating from → to, ratings per month; a falling rating with rising volume
   usually means a quality or listing-accuracy problem.
4. **Product-improvement ideas**: 3-6 concrete changes, each tied to a complaint (design, material,
   size, packaging, instructions, listing accuracy), and which ones a new seller could use as a selling point.
   Comparing competitors: a small table of shared complaints, the gap nobody fixes first.
5. **Sample note** in one line: e.g. "From Amazon's summary of 28 written reviews (187 ratings); 8 visible
   reviews read." Never extrapolate a percentage to all buyers.
6. Weighing a better version → offer `amazon-listing-teardown` (the listing) and `amazon-profit-calculator`.

## Errors (JSON `error`, non-zero exit)

- `invalid_asin` (`reason`: short_link, us_only, not_amazon, no_asin): ask for an ASIN or full amazon.com link.
- `asin_not_found`: not sold on amazon.com. `too_many`: over 5 listings in one `page` run.
- `page_blocked` (exit 5): see above. In a multi-ASIN run the read stops there; `notRead` lists the rest.
- `whm_route_not_live`, `no_keys`: see Keys. `keepa_tokens_low` (give `waitSec`), `keepa_key_rejected`.
