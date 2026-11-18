# amazon-top-organic-keywords

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/amazon-top-organic-keywords.svg)](https://api.waithowmuch.com/go/site?from=amazon-top-organic-keywords)

The search keywords an Amazon product ranks for organically, biggest first: monthly search volume, organic rank, sponsored rank and suggested bid.

**Try:** "What keywords does B0H793VVWP rank for on Amazon?"

## Keys

- **Option A, your own keys:** `JUNGLESCOUT_API_KEY` ([get a key](https://api.waithowmuch.com/go/junglescout-api?from=amazon-top-organic-keywords); `"<key name>:<key>"`; a Jungle Scout plan with the API add-on, from $29/month for 1,000 requests, $0.05 a request over): 1 request per 100 keywords, up to 3 a lookup. Volumes on Amazon's scale, plus bids.
  - or `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` ([get a key](https://api.waithowmuch.com/go/dataforseo-api?from=amazon-top-organic-keywords); pay as you go, $50 minimum top-up): about $0.02 a lookup. Its volumes run about 20x below Amazon's scale, so they rank keywords rather than count searches.
- **Option B, one WaitHowMuch key** (`WHM_API_KEY`, [get a key](https://api.waithowmuch.com/go/whm-key?from=amazon-top-organic-keywords)): an ASIN's organic keywords with volumes and bids.

How to set keys on each agent: [Data providers](../../README.md#data-providers).

## Install

Every method, including the whole plugin: [Install](../../README.md#install). This skill alone:

- Any CLI agent: `npx skills add ggballas/waithowmuch-skills --skill amazon-top-organic-keywords`
- claude.ai or Claude desktop: download [amazon-top-organic-keywords.zip](https://api.waithowmuch.com/go/zip-amazon-top-organic-keywords?from=amazon-top-organic-keywords), then Customize > Skills > Upload a skill.
