# High-quality content acquisition plan

Status: product inventory baseline for the local IELTS Academic system.

The numbers below are internal planning targets for variety and repeat
avoidance. They are not IELTS rules and do not make a source official. The live
counts are available in the UI under **Content and Library → Readiness** and via:

```powershell
ielts-coach content readiness
```

## 1. Minimum and recommended inventory

| Module | Minimum useful inventory | Recommended sustained inventory |
|---|---:|---:|
| Reading | 8 reviewed full tests; 24 IELTS-length passages; 320 keyed questions | 20 full tests; 60 passages; 800 questions |
| Listening | 8 reviewed full tests; 32 audio-backed parts; 320 keyed questions | 20 full tests; 80 parts; 800 questions |
| Writing Task 1 | 56 complete readable prompts | 105 prompts |
| Writing Task 2 | 100 reviewed prompts | 200 prompts |
| Speaking Part 1 | 30 reviewed topic groups | 60 groups |
| Speaking Part 2–3 | 60 linked sets | 120 linked sets |

Cambridge IELTS 15–21 is a candidate private batch only when the learner owns
the books. If each owned volume contains four eligible Academic tests, the
working estimate is 28 tests; the importer must verify the actual edition and
contents instead of assuming that count. No book text, scan or audio is bundled
with this repository.

## 2. Reading material still required

Each full pack needs three passages, 40 questions, a 60-minute contract and a
reviewed answer key. Each passage should carry stable paragraph labels and each
question should carry an evidence location and explanation.

Coverage backlog:

- multiple choice;
- True/False/Not Given and Yes/No/Not Given;
- matching information, headings and features;
- matching sentence endings;
- sentence, summary, note, table and flow-chart completion;
- diagram labels and short answers.

Import priorities are complete test packs first, then high-quality independent
passages for type drills. A standalone “ordering question” is not added unless
it maps to an official IELTS question family.

## 3. Listening material still required

Every full test requires four ten-question parts, playable local audio, a
transcript, one-play-only metadata, answer keys and—where possible—timestamps
for review.

Coverage backlog:

- multiple choice and matching;
- plan, map and diagram labelling;
- form, note, table, flow-chart and summary completion;
- sentence completion and short answers.

The existing 50-expression high-frequency corpus remains a `skill_drill`; it
does not count toward these test inventories.

## 4. Writing material still required

Task 1 must cover line, bar, pie, table, map, process and mixed visuals. Every
prompt needs the complete readable visual or structured data, the unit, time
period, minimum-word contract and review state.

Task 2 should balance opinion, discussion plus opinion, problem/solution,
advantages/disadvantages and two-part prompts across education, work,
technology, environment, cities, health, culture, media, government and social
issues. Prompt quality is reviewed separately from any sample answer.

## 5. Speaking material still required

Part 1 is stored as topic groups rather than isolated questions. Part 2 Cue
Cards store cue points structurally. Part 3 questions must share a
`speaking_set_id` with the selected Part 2 topic.

The target topic spread includes home, study, work, people, places, objects,
events, activities, technology, society, education and environment. Complete
flow practice needs enough Part 1 questions for two topic groups, one Cue Card
and three to five linked Part 3 questions.

## 6. Quality tiers

1. `official_external` or legally owned `licensed_private`: retain source and
   edition/page references; keep private files local.
2. High-quality third-party practice: label the publisher and rights status;
   never call it an official test.
3. Project-original practice: independently review instructions, answer key,
   evidence and difficulty.
4. Seasonal reported or synthetic items: useful only with visible uncertainty;
   never enter a verified full-mock pool without reconstruction and review.

## 7. Local ingestion workflow

```text
Upload PDF / audio / image
→ local inbox (needs_structuring)
→ prepare passages/questions/assessment_packs JSONL
→ add manifest with source and rights
→ schema and conformance validation
→ human review
→ indexed corpus
→ verified assessment pack
→ eligible practice mode
```

Raw uploads do not become questions automatically. The UI accepts prepared
`manifest.yaml` plus referenced JSONL as a structured package; PDFs and media
remain in the local inbox until a page-aware preprocessing workflow produces
reviewable records.
