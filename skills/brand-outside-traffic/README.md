# brand-outside-traffic

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/brand-outside-traffic.svg)](https://api.waithowmuch.com/go/site?from=brand-outside-traffic)

How much traffic a brand gets outside Amazon and where from: its website's visits and channel mix, Google searches for its name, its social followings, whether its site sends shoppers to Amazon, and the dates its Amazon rank jumped.

**Try:** "Where does Mount Cleverest's demand come from outside Amazon, and did it show up in their Amazon sales?"

## Keys

- **Option A, your own keys:** any of these; the site scan and YouTube counts are free:
  - `SIMILARWEB_API_KEY` ([get a key](https://api.waithowmuch.com/go/similarweb-api?from=brand-outside-traffic), a Similarweb plan with API access): monthly visits and channel mix, 2 API calls a site.
  - `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` ([get a key](https://api.waithowmuch.com/go/dataforseo-api?from=brand-outside-traffic); pay as you go, $50 minimum top-up): Google search traffic for a site and monthly searches for a brand name, about $0.012 each.
  - `KEEPA_API_KEY` ([get a key](https://api.waithowmuch.com/go/keepa-api?from=brand-outside-traffic), paid Keepa API plan): the dates a listing's Amazon rank jumped, 1 token.
- **Option B, one WaitHowMuch key** (`WHM_API_KEY`, [get a key](https://api.waithowmuch.com/go/whm-key?from=brand-outside-traffic)): site traffic, brand searches and rank spikes in one key.

How to set keys on each agent: [Data providers](../../README.md#data-providers).

## Install

Every method, including the whole plugin: [Install](../../README.md#install). This skill alone:

- Any CLI agent: `npx skills add ggballas/waithowmuch-skills --skill brand-outside-traffic`
- claude.ai or Claude desktop: download [brand-outside-traffic.zip](https://api.waithowmuch.com/go/zip-brand-outside-traffic?from=brand-outside-traffic), then Customize > Skills > Upload a skill.
