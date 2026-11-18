---
name: brand-outside-traffic
description: How much traffic and attention a brand gets outside Amazon and where it comes from - its own website's visits and channel mix (Similarweb), Google search traffic and how many people search the brand's name each month, its store platform, social accounts and YouTube/TikTok/Instagram followings, whether its site sends shoppers to Amazon (Amazon Attribution links), and the dates its Amazon rank jumped so they can be matched to posts, press or search spikes. Use when the user asks where a brand's demand comes from, whether an Amazon seller has an audience off Amazon, how much traffic a brand's website gets, how big its socials are, or whether a sales spike came from outside Amazon.
---

# A brand's traffic outside Amazon

Every figure is a third-party estimate or a public reading, dated. Say which, and never present a
visit estimate as the brand's analytics. Keep it out of any Amazon revenue figure.

## Keys and mode

Helper: `scripts/whm.py` (Python 3, no dependencies). It never prints keys; don't echo one.
`python3 scripts/whm.py mode` says which keys are set.

| mode | used when | serves |
|---|---|---|
| WaitHowMuch | `WHM_API_KEY` set | `researched`: the readings for a WaitHowMuch case-study brand (live). `traffic`, `brand-search`, `spikes` for other brands: not live yet |
| Own keys | `SIMILARWEB_API_KEY`, `DATAFORSEO_LOGIN`+`DATAFORSEO_PASSWORD`, `KEEPA_API_KEY` (any) | each command uses the key it needs |

With both set, WHM answers first and own keys fill what it can't. No key at all → `no_keys`: tell the
user briefly to set `WHM_API_KEY` **or** their own provider keys, then carry on with the free commands.
`site` and `youtube` need no key.

Usage count: each `whm.py` command sends one anonymous GET to `api.waithowmuch.com/health` with only the skill, version, command name and key mode (whm/own/none), never arguments, inputs or keys. `WHM_USAGE=0` turns it off.

## Commands

```bash
python3 scripts/whm.py researched "<brand>"              # WHM case study: website visits, followers, sources
python3 scripts/whm.py site <domain>                     # free: platform, socials, links to Amazon
python3 scripts/whm.py traffic <domain> [--months 6]     # Similarweb visits + channels; DataForSEO Google traffic (~$0.012)
python3 scripts/whm.py brand-search "<brand>" [--also "alt name,product name"]   # Google US searches, 12 months (~$0.012)
python3 scripts/whm.py youtube <@handle | channel URL>   # free: subscribers, videos
python3 scripts/whm.py spikes <ASIN> [--days 730]        # Amazon rank and badge jumps (Keepa: 1 token)
```

## Workflow

1. WHM mode: `researched "<brand>"` first. A case study already has the readings; report them with
   their read dates and link `caseStudy`. Otherwise:
2. **Find the site.** Ask for or look up the brand's website (not Amazon). `site <domain>`: the store
   platform, whether it sells direct, the social links it lists, and its Amazon links.
   `amazonAttribution: true` (a `maas=` tag) means the brand deliberately sends and measures traffic
   to Amazon. That is the clearest off-Amazon → Amazon signal.
3. **Size the site.** `traffic <domain>`. Similarweb gives monthly visits and the channel mix (direct,
   search, social, paid, referral); DataForSEO gives Google US organic visits and paid keywords. They
   often disagree: show both, don't pick. With neither key, Similarweb's public page
   (`similarweb.com/website/<domain>/`) works in a browser. 🚨 Its headline is **"Total Visits Last 3
   Months"**: divide by 3, and say the division is yours.
4. **Brand demand.** `brand-search "<brand>"` with the main product name in `--also`. Searches for the
   name are demand the brand built off Amazon; the 12-month history shows when it spiked.
5. **Socials.** `youtube` for each channel `site` found. TikTok and Instagram block plain fetches: with
   a browser tool, read the profile's follower count (TikTok: `#__UNIVERSAL_DATA_FOR_REHYDRATION__` →
   `webapp.user-detail.userInfo.stats.followerCount`); without one, list the account as "exists,
   unsized". For TikTok Shop sales and TikTok ads, offer the `tiktok-shop-research` skill.
6. **Did it reach Amazon?** `spikes <ASIN>` on the brand's best seller: dates the sales rank jumped
   (≥3× better, sustained two weeks) and the "bought in past month" badge doubled. Line them up with
   brand-search months, viral posts (TikTok post dates are in `tiktok-shop-research post`), press and
   TV. A jump with no Amazon cause (deal, price cut, ad push) that matches an outside event is the
   signal. Say it is correlation, not proof.

## Answer

- One line: where the brand's demand comes from, in order of size.
- A small table, one row per channel: channel, figure (visits / followers / searches), source, date
  read. Mark each **measured** (a public count), **estimate** (Similarweb, DataForSEO, Kalodata) or
  **exists, unsized**.
- The off-Amazon → Amazon read: Amazon links and Attribution on the site, plus rank spikes matched to
  outside events, each with its date.
- Caveats in one line: estimates disagree, rounded follower counts, homepage-only link scan.

## Errors (JSON `error`, non-zero exit)

- `whm_route_not_live` (`route` named): WaitHowMuch doesn't serve that for this brand yet; name the own key that covers it.
- `similarweb_key_rejected` (Similarweb API needs a paid plan with API access), `dataforseo_key_rejected`,
  `dataforseo_balance_low`, `keepa_key_rejected`, `keepa_tokens_low` (give `refillInSec`).
- `site_unreachable`: bot check or down; use a browser if available. `bad_domain`: they gave Amazon or a
  malformed address. `channel_not_found`, `invalid_asin`: fix the input.
