# Third-party notices

## Original code and upstream references
redreview's original code is MIT licensed (see LICENSE). No CoLRev, Buhos or ASReview source, assets, models or dependencies are copied, vendored or executed. Their licences do not determine the licence of their dependencies.

| Reference | Inspected version / revision | Licence | Use |
| --- | --- | --- | --- |
| CoLRev | manifest 0.16.2 on main | MIT | Workflow and record provenance design reference only. |
| Buhos | master; systematic_review.rb metadata 2026-06-23 | BSD-3-Clause; copyright Claudio Bustos Navarrete 2016–2025 | Review management and blinding design reference only. |
| ASReview | main, dynamic version (no exact release asserted) | Apache-2.0 | Future ranking architecture reference only; no AI in v1. |

Links and inspection details: docs/architecture.md. If future work copies upstream code, preserve its complete required licence, copyright and NOTICE files; independently audit each selected dependency first.

## Runtime components
No third-party Python or JavaScript packages are bundled. Requires an external Python >=3.11 installation (PSF licensing and bundled third-party notices apply to that installation), its standard library and SQLite. Verified Python 3.14.4 / SQLite 3.46.1 here. SQLite upstream core is public domain: https://www.sqlite.org/copyright.html . Native browser PDF viewing is supplied by the user's browser and is not redistributed. No external fonts, icon libraries or image assets.

## Development-only components
Node 22.22.1 (external installation), TypeScript 5.9.3 and jsdom 26.1.0 were used. Node has its own MIT licence and third-party notices; TypeScript is Apache-2.0, jsdom MIT. Development dependency versions/integrities are locked in package-lock.json using the versions of installed packages actually exercised. These are tools only; the generated app.js contains original application code, not their runtimes.

The following manifest licence declarations were checked individually against the installed dependency tree, not inferred from jsdom. Dependency source packages and their licence/notice files are retained by npm in node_modules when installed; no dependency source is committed here. If distributing node_modules, include each package's actual licence/notice files. Manifest metadata is an inventory, not a replacement for those texts.

| Component | Version | Declared licence |
| --- | --- | --- |
| @asamuzakjp/css-color | 3.2.0 | MIT |
| @csstools/color-helpers | 5.1.0 | MIT-0 |
| @csstools/css-calc | 2.1.4 | MIT |
| @csstools/css-color-parser | 3.1.0 | MIT |
| @csstools/css-parser-algorithms | 3.0.5 | MIT |
| @csstools/css-tokenizer | 3.0.4 | MIT |
| agent-base | 7.1.4 | MIT |
| cssstyle | 4.6.0 | MIT |
| data-urls | 5.0.0 | MIT |
| debug | 4.4.3 | MIT |
| decimal.js | 10.6.0 | MIT |
| entities | 6.0.1 | BSD-2-Clause |
| html-encoding-sniffer | 4.0.0 | MIT |
| http-proxy-agent | 7.0.2 | MIT |
| https-proxy-agent | 7.0.6 | MIT |
| iconv-lite | 0.6.3 | MIT |
| is-potential-custom-element-name | 1.0.1 | MIT |
| jsdom | 26.1.0 | MIT |
| lru-cache | 10.4.3 | ISC |
| ms | 2.1.3 | MIT |
| nwsapi | 2.2.28 | MIT |
| parse5 | 7.3.0 | MIT |
| punycode | 2.3.1 | MIT |
| rrweb-cssom | 0.8.0 | MIT |
| safer-buffer | 2.1.2 | MIT |
| saxes | 6.0.0 | ISC |
| symbol-tree | 3.2.4 | MIT |
| tldts | 6.1.86 | MIT |
| tldts-core | 6.1.86 | MIT |
| tough-cookie | 5.1.2 | BSD-3-Clause |
| tr46 | 5.1.1 | MIT |
| typescript | 5.9.3 | Apache-2.0 |
| w3c-xmlserializer | 5.0.0 | MIT |
| webidl-conversions | 7.0.0 | BSD-2-Clause |
| whatwg-encoding | 3.1.1 | MIT |
| whatwg-mimetype | 4.0.0 | MIT |
| whatwg-url | 14.2.0 | MIT |
| ws | 8.22.0 | MIT |
| xml-name-validator | 5.0.0 | Apache-2.0 |
| xmlchars | 2.2.0 | MIT |

## Scholarly provider data

Crossref, OpenAlex and PubMed API adapters are original code using Python's standard library. No provider SDK is bundled. API access and metadata rights are distinct from the code's MIT licence. Crossref abstracts can be copyrighted; OpenAlex metadata is shared under CC0 but linked full text has separate rights. PubMed abstracts may be copyrighted. Users must respect [NCBI disclaimer/copyright](https://www.ncbi.nlm.nih.gov/About/disclaimer.html), provider terms and each full-text licence. The UI surfaces missing fields and separates provider-reported OA PDFs from article webpages. No upstream full-text content is bundled in the public repository. Only the labelled synthetic fixture PDF is included.
