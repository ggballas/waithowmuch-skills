# amazon-review-insights

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/amazon-review-insights.svg)](https://api.waithowmuch.com/go/site?from=amazon-review-insights)

What buyers praise and complain about on any Amazon US listing, how many mention each thing, and the product changes that would answer them. Up to five competitors side by side; always says how many reviews it rests on.

**Try:** "What do people complain about in reviews of B0F1H6B5VJ?" or "Compare the complaints on these three competitors and tell me what to fix in mine"

## Keys

- **Option A, your own keys:** no key needed for the reviews: they come from the public product page (Amazon's review summary, topic counts with quotes, the star histogram).
  - Optional: `KEEPA_API_KEY` ([get a key](https://api.waithowmuch.com/go/keepa-api?from=amazon-review-insights), paid Keepa API plan) adds the rating and review count month by month, 2 tokens a listing.
- **Option B, one WaitHowMuch key** (`WHM_API_KEY`, [get a key](https://api.waithowmuch.com/go/whm-key?from=amazon-review-insights)): adds the rating and review-count history.

How to set keys on each agent: [Data providers](../../README.md#data-providers).

## Install

Every method, including the whole plugin: [Install](../../README.md#install). This skill alone:

- Any CLI agent: `npx skills add ggballas/waithowmuch-skills --skill amazon-review-insights`
- claude.ai or Claude desktop: download [amazon-review-insights.zip](https://api.waithowmuch.com/go/zip-amazon-review-insights?from=amazon-review-insights), then Customize > Skills > Upload a skill.
