# amazon-brand-valuation

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/amazon-brand-valuation.svg)](https://api.waithowmuch.com/go/site?from=amazon-brand-valuation)

What an Amazon brand might be worth: trailing-twelve-month net profit times a multiple built up factor by factor (age, reviews, rating, seasonality, concentration, sourcing, differentiation), with every adjustment shown. An estimate, not an appraisal or financial advice.

**Try:** "What's Songbird Specialties worth on Amazon?" or "My FBA brand made $180K net profit last year. What multiple might it sell for?"

## Keys

- **Option A, your own keys:** `KEEPA_API_KEY` ([get a key](https://api.waithowmuch.com/go/keepa-api?from=amazon-brand-valuation), paid Keepa API plan). Prices any brand's catalogue (twelve months of revenue, first listing, reviews, rating, seasonality) for about 11 + 2N Keepa tokens (N listings, default 50), or about 2 an ASIN when you name the listings.
  - No key: give a trailing-twelve profit and the facts you know, and it scores them offline.
- **Option B, one WaitHowMuch key** (`WHM_API_KEY`, [get a key](https://api.waithowmuch.com/go/whm-key?from=amazon-brand-valuation)): valuations for any brand, and the stamped valuation of every brand WaitHowMuch has researched.

How to set keys on each agent: [Data providers](../../README.md#data-providers).

## Install

Every method, including the whole plugin: [Install](../../README.md#install). This skill alone:

- Any CLI agent: `npx skills add ggballas/waithowmuch-skills --skill amazon-brand-valuation`
- claude.ai or Claude desktop: download [amazon-brand-valuation.zip](https://api.waithowmuch.com/go/zip-amazon-brand-valuation?from=amazon-brand-valuation), then Customize > Skills > Upload a skill.
