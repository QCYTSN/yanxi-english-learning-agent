# Third-party notices

This repository does not bundle Cambridge IELTS books, test audio, reading
passages, answer keys, commercial question banks or other copyrighted third-
party teaching materials.

The documentation may identify official publishers and legitimate acquisition
channels so users can obtain materials independently. Such references do not
transfer copyright or grant redistribution rights.

IELTS is a registered trademark of its respective owners. This project is
independent and is not endorsed by IELTS, Cambridge University Press &
Assessment, the British Council or IDP Education.

## Bundled fonts

- **LXGW WenKai (霞鹜文楷)** — subset woff2 files shipped under the SIL Open
  Font License 1.1 (`frontend/src/assets/fonts/yanxi-logo.woff2`,
  `yanxi-heading.woff2`). Full font: https://github.com/lxgw/LxgwWenKai
  (Copyright © 2020–2026 LXGW / the LXGW WenKai contributors). The bundled
  files are static subsets used for the wordmark and heading text; they do not
  include any vocabulary content or definitions.

## Bundled word list

- **言蹊起步词表 (Starter 100)** — word forms derived from the public-domain
  General Service List (West, 1953), top-100 frequency band
  (`src/ielts_coach/resources/words/yanxi-starter-100.json`). Word forms and
  言蹊 self-assessed level bands only; no definitions, examples or commercial
  dictionary content is included.
- **言蹊高频词表 (Frequency 3000)** — word forms derived from the
  FrequencyWords `en_50k` list by hermitdave
  (https://github.com/hermitdave/FrequencyWords), MIT License, top-3000 by
  corpus frequency with heuristic 言蹊 A1/A1-A2/B1 bands
  (`src/ielts_coach/resources/words/yanxi-frequency-3000.json`). The list is
  compiled from public subtitle and web corpora; word forms only, no
  definitions or examples are included.
- **言蹊四级词表 / 六级词表 / 托福词表 (CET-4 / CET-6 / TOEFL)** — word
  forms extracted from the KyleBing `english-vocabulary` list
  (https://github.com/KyleBing/english-vocabulary, no LICENSE declared).
  That repository carries no licence declaration, so 言蹊 includes only the
  bare word forms (facts) — none of its definitions, examples or
  arrangement — and attributes the source here. Heuristic 言蹊 bands:
  CET-4 A2-B1, CET-6 B1-B2, TOEFL B1-C1
  (`yanxi-cet4.json`, `yanxi-cet6.json`, `yanxi-toefl.json`).
- **言蹊雅思学术核心词表 (AWL)** — 568 headwords of the Academic Word List
  (Coxhead, 1999), the recognised IELTS-academic core, from the data file
  in TheoSeo93/Academic_Words_list (https://github.com/TheoSeo93/Academic_Words_list,
  Open Software License 1.1). Word forms only
  (`yanxi-ielts-academic.json`).
- **言蹊雅思核心词表 (IELTS Core)** — 1647 word forms from
  hefengxian/ielts-vocabulary (https://github.com/hefengxian/ielts-vocabulary,
  MIT License, Copyright (c) 2023 Frank). Word forms only; its definitions,
  examples and thematic arrangement are not included
  (`yanxi-ielts-core.json`).
