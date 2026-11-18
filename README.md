![WaitHowMuch](assets/logo.png)

# WaitHowMuch skills for Amazon sellers

Ask your AI agent what any Amazon product or brand sells, what it keeps after fees and ads, and where its customers come from. Every figure is an estimate and says what it rests on.

[![WaitHowMuch](https://api.waithowmuch.com/go/badge/root.svg)](https://api.waithowmuch.com/go/site?from=root)
[![release](https://img.shields.io/github/v/release/ggballas/waithowmuch-skills?color=5b3df5)](https://api.waithowmuch.com/go/releases?from=root)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![works with Claude Code](https://img.shields.io/badge/works_with-Claude_Code-D97757?logo=claude&logoColor=white)](#install)
[![works with Codex](https://img.shields.io/badge/works_with-Codex-555)](#install)

<!-- demo video: drag an mp4 into the GitHub editor and paste the user-attachments URL here -->

## Example

> **You:** How much does B0F1H6B5VJ sell a month?

> **Agent** (amazon-revenue-sales, 1 Keepa token): Songbird Specialties Singing Bird Wine Bottle Pourer, $29.99, figures for November 2026.
> This month: 800-899 units, **$24.0K-27.0K**, from Amazon's "800+ bought in past month" badge.
>
> | Month | Units | Revenue |
> |---|--:|--:|
> | 2026-06 | 200-299 | $6.0K-9.0K |
> | 2026-07 | 300-399 | $9.0K-12.0K |
> | 2026-08 | 300-399 | $9.0K-12.0K |
> | 2026-09 | 500-599 | $15.0K-18.0K |
> | 2026-10 | 500-599 | $15.0K-18.0K |
>
> Peak: September. Figures are a floor, and today's price is applied to past months.

## Install

| Where | How |
|---|---|
| **Claude Code** | `claude plugin install waithowmuch --marketplace ggballas/waithowmuch-skills`<br>Before v2.1.292: `claude plugin marketplace add ggballas/waithowmuch-skills` then `claude plugin install waithowmuch@waithowmuch` |
| **claude.ai, Claude desktop, Cowork** | [Customize > Plugins](https://api.waithowmuch.com/go/claude-plugins?from=root) > Add > Add marketplace > `ggballas/waithowmuch-skills`<br>Or one skill: download its zip from the [skills table](#skills), then Customize > Skills > Upload a skill |
| **Codex** | `codex plugin marketplace add ggballas/waithowmuch-skills`, then `/plugins` in Codex |
| **Cursor and other agents** | `npx skills add ggballas/waithowmuch-skills` |
| **ChatGPT (web)** | Not supported: ChatGPT skills can't call outside APIs yet. |

## Skills

| Skill | What it answers | Zip |
|---|---|---|
| [amazon-revenue-sales](skills/amazon-revenue-sales/) | Monthly units and revenue for any product, brand or store, back to mid-2023 | [zip](https://api.waithowmuch.com/go/zip-amazon-revenue-sales?from=root) |
| [amazon-profit-calculator](skills/amazon-profit-calculator/) | Monthly profit and margin after fees, COGS, ads and returns | [zip](https://api.waithowmuch.com/go/zip-amazon-profit-calculator?from=root) |
| [amazon-cogs-estimator](skills/amazon-cogs-estimator/) | Landed cost per unit: factory, freight, duty, prep | [zip](https://api.waithowmuch.com/go/zip-amazon-cogs-estimator?from=root) |
| [amazon-adspend-estimator](skills/amazon-adspend-estimator/) | What a competitor spends on Amazon ads, and on which keywords | [zip](https://api.waithowmuch.com/go/zip-amazon-adspend-estimator?from=root) |
| [amazon-top-organic-keywords](skills/amazon-top-organic-keywords/) | The keywords a listing ranks for, with volume and bids | [zip](https://api.waithowmuch.com/go/zip-amazon-top-organic-keywords?from=root) |
| [amazon-listing-teardown](skills/amazon-listing-teardown/) | A competitor's listing taken apart, with its history | [zip](https://api.waithowmuch.com/go/zip-amazon-listing-teardown?from=root) |
| [amazon-review-insights](skills/amazon-review-insights/) | What buyers praise and complain about, and what to fix | [zip](https://api.waithowmuch.com/go/zip-amazon-review-insights?from=root) |
| [amazon-brand-valuation](skills/amazon-brand-valuation/) | What an Amazon brand might sell for | [zip](https://api.waithowmuch.com/go/zip-amazon-brand-valuation?from=root) |
| [amazon-design-based-product-finder](skills/amazon-design-based-product-finder/) | New design-led brands that are already selling, ranked | [zip](https://api.waithowmuch.com/go/zip-amazon-design-based-product-finder?from=root) |
| [alibaba-automated-supplier-contact](skills/alibaba-automated-supplier-contact/) | Quotes, MOQs and lead times from matching Alibaba suppliers | [zip](https://api.waithowmuch.com/go/zip-alibaba-automated-supplier-contact?from=root) |
| [tiktok-shop-research](skills/tiktok-shop-research/) | A brand's TikTok Shop sales, creators and ads | [zip](https://api.waithowmuch.com/go/zip-tiktok-shop-research?from=root) |
| [brand-outside-traffic](skills/brand-outside-traffic/) | A brand's website traffic, searches and socials outside Amazon | [zip](https://api.waithowmuch.com/go/zip-brand-outside-traffic?from=root) |
| [amazon-case-studies](skills/amazon-case-studies/) | Researched brands similar to a product or niche | [zip](https://api.waithowmuch.com/go/zip-amazon-case-studies?from=root) |
| [amazon-case-study-builder](skills/amazon-case-study-builder/) | A full WaitHowMuch-style case study of any brand, built with all of the above | [zip](https://api.waithowmuch.com/go/zip-amazon-case-study-builder?from=root) |

## Data providers

Every skill works two ways. **Option A:** your own provider keys, as marked in the provider columns. **Option B:** one WaitHowMuch key (`WHM_API_KEY`) in place of all of them.

| Skill | Keepa | Jungle Scout | DataForSEO | Kalodata | Similarweb | **WaitHowMuch** (Option B) |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| amazon-revenue-sales | ✓ |  |  |  |  | ✓ |
| amazon-profit-calculator | ✓ |  |  |  |  | ✓ |
| amazon-cogs-estimator | opt |  |  |  |  | ✓ |
| amazon-adspend-estimator | opt | either | either |  |  | ✓ |
| amazon-top-organic-keywords |  | either | either |  |  | ✓ |
| amazon-listing-teardown | ✓ |  |  |  |  | ✓ |
| amazon-review-insights | opt |  |  |  |  | ✓ |
| amazon-brand-valuation | ✓ |  |  |  |  | ✓ |
| amazon-design-based-product-finder | ✓ |  |  |  |  | ✓ |
| alibaba-automated-supplier-contact |  |  |  |  |  | ✓ |
| tiktok-shop-research |  |  |  | ✓ |  | ✓ |
| brand-outside-traffic | opt |  | opt |  | opt | ✓ |
| amazon-case-studies | ✓ |  |  |  |  | ✓ |
| amazon-case-study-builder | ✓ | either | either | opt | opt | ✓ |
| **Get a key →** | [key](https://api.waithowmuch.com/go/keepa-api?from=root) | [key](https://api.waithowmuch.com/go/junglescout-api?from=root) | [key](https://api.waithowmuch.com/go/dataforseo-api?from=root) | [key](https://api.waithowmuch.com/go/kalodata-api?from=root) | [key](https://api.waithowmuch.com/go/similarweb-api?from=root) | [sign up](https://api.waithowmuch.com/go/whm-key?from=root) |

Provider columns: ✓ needed; either: one of the two; opt: adds data; no mark needs no key. The WaitHowMuch key alone covers every row. Each skill's README lists its costs. The variables are `KEEPA_API_KEY`, `JUNGLESCOUT_API_KEY`, `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD`, `KALODATA_API_KEY`, `SIMILARWEB_API_KEY`, and optionally `AMAZON_ADS_*` for Amazon's suggested bids.

Set them:

- **Claude Code:** `/plugin` > waithowmuch > Configure options. Keys are kept in your OS keychain. Exported variables also work.
- **Codex, Cursor and other CLI agents:** `export WHM_API_KEY=...` (or your provider keys) in your shell profile. Codex also needs network access: approve it when asked.
- **claude.ai and desktop:** under Settings > Capabilities, allow `api.waithowmuch.com` (or your providers' API domains), then give Claude the key when it asks. The key stays in that chat.

---

Usage counting: each skill run sends the skill name and version to `api.waithowmuch.com` (no prompts, files, keys or IPs are stored); set `WHM_USAGE=0` to turn it off. Links and the badge here are counted via `api.waithowmuch.com`. [MIT license](LICENSE).
