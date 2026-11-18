# amazon-adspend-estimator

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/amazon-adspend-estimator.svg)](https://api.waithowmuch.com/go/site?from=amazon-adspend-estimator)

What an Amazon competitor spends on ads a month, as a modelled low/central/high band (keywords x searches x their share of sponsored results x click-through x bid), with their ad strategy and the keywords they pay for. A model, not their bill.

**Try:** "How much does Virora Mahjong spend on Amazon ads?"

## Keys

- **Option A, your own keys:** `JUNGLESCOUT_API_KEY` ([get a key](https://api.waithowmuch.com/go/junglescout-api?from=amazon-adspend-estimator); `"<key name>:<key>"`; a Jungle Scout plan with the API add-on, from $29/month for 1,000 requests, $0.05 a request over): the full band, about 28 requests a run.
  - or `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` ([get a key](https://api.waithowmuch.com/go/dataforseo-api?from=amazon-adspend-estimator); pay as you go, $50 minimum top-up): where their ads show, about $0.014 an ASIN, no dollar figure.
  - Optional: `KEEPA_API_KEY` ([get a key](https://api.waithowmuch.com/go/keepa-api?from=amazon-adspend-estimator), paid Keepa API plan; 1 token an ASIN, about 21 for a brand) adds revenue and the ad rate; `AMAZON_ADS_CLIENT_ID`, `AMAZON_ADS_CLIENT_SECRET`, `AMAZON_ADS_REFRESH_TOKEN`, `AMAZON_ADS_PROFILE_ID` (your own Amazon Ads API app, free) price clicks at Amazon's suggested bids.
- **Option B, one WaitHowMuch key** (`WHM_API_KEY`, [get a key](https://api.waithowmuch.com/go/whm-key?from=amazon-adspend-estimator)): the ad-spend band and ad strategy for any ASIN or brand.

How to set keys on each agent: [Data providers](../../README.md#data-providers).

## Install

Every method, including the whole plugin: [Install](../../README.md#install). This skill alone:

- Any CLI agent: `npx skills add ggballas/waithowmuch-skills --skill amazon-adspend-estimator`
- claude.ai or Claude desktop: download [amazon-adspend-estimator.zip](https://api.waithowmuch.com/go/zip-amazon-adspend-estimator?from=amazon-adspend-estimator), then Customize > Skills > Upload a skill.
