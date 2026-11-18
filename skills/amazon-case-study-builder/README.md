# amazon-case-study-builder

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/amazon-case-study-builder.svg)](https://api.waithowmuch.com/go/site?from=amazon-case-study-builder)

A full WaitHowMuch-style case study of any Amazon US brand, as one self-contained HTML page: a profit headline, revenue, profit and ad spend month by month, the sales breakdown with product photos, a margin waterfall, how it sells, advertising and keywords, traffic outside Amazon, the listing and its reviews, the brand owner, a valuation and a written read. Every figure says whether it was given, derived or assumed, and where it came from. It runs the other WaitHowMuch skills, so install the whole plugin.

**Try:** "Build me a case study of Songbird Specialties (B0F1H6B5VJ). The pourer costs about $2.87 to make."

## Keys

- **Option A, your own keys** (the union of what the sibling skills use):
  - `KEEPA_API_KEY` (**required**, [get a key](https://api.waithowmuch.com/go/keepa-api?from=amazon-case-study-builder), paid Keepa API plan): revenue, the chart, the breakdown, photos, the listing, fees, valuation inputs. About 40-90 tokens a case study (a 25-listing brand: ~36 for the catalogue, 5 teardown, ~6 photos, ~4 fees, box and rank spikes).
  - `JUNGLESCOUT_API_KEY` ([get a key](https://api.waithowmuch.com/go/junglescout-api?from=amazon-case-study-builder); Jungle Scout plan + API add-on, from $29/month for 1,000 requests, $0.05 a request over): the ad-spend band and top keywords, ~29 requests (~$1.45 at the overage price). Or `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` ([get a key](https://api.waithowmuch.com/go/dataforseo-api?from=amazon-case-study-builder), pay as you go): keywords and where their ads show, no dollar figure, ~$0.03.
  - Optional: DataForSEO also adds Google traffic and brand searches (~$0.012 each); `SIMILARWEB_API_KEY` ([get a key](https://api.waithowmuch.com/go/similarweb-api?from=amazon-case-study-builder), Similarweb plan with API access) adds website visits; `KALODATA_API_KEY` ([get a key](https://api.waithowmuch.com/go/kalodata-api?from=amazon-case-study-builder)) adds TikTok Shop sales (~1.5 credits, ~$0.15).
  - Rough metered cost of a full case study on top of your plans: **under $2** (most of it Jungle Scout requests past your monthly allowance). Freight (Freightos), duty (USITC), the site scan and the review read are free.
- **Option B, one WaitHowMuch key** (`WHM_API_KEY`, [get a key](https://api.waithowmuch.com/go/whm-key?from=amazon-case-study-builder)): brands WaitHowMuch has already researched, in full, plus similar case studies. Other brands need Option A until the general routes ship. No per-call credit price is set yet.

Cost of goods can't be read from public data: give a factory price or supplier quote, or the page stops at "before cost of goods". Sections your keys can't fill are left out with a one-line note, never filled with a guess.

How to set keys on each agent: [Data providers](../../README.md#data-providers).

## Output

One HTML file (inline CSS, inline SVG charts, no scripts). In Claude apps it is shown as an artifact; in CLI agents it is saved to the working directory and the path printed. Nothing is uploaded or published.

## Install

Every method, including the whole plugin: [Install](../../README.md#install). This skill alone: `npx skills add ggballas/waithowmuch-skills --skill amazon-case-study-builder` (it needs the sibling skills too).
