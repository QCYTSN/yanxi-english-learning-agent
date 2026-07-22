# Speaking report template

The report passed to `ielts-coach speaking import-report` may be Markdown with
YAML frontmatter. Keep source observations, the Voice model's estimate and the
local rubric evaluation separate.

```yaml
report_version: 2
session_id: S-YYYYMMDD-001
mode: full_mock
occurred_at: 2026-07-22T19:00:00+08:00
duration_minutes: 14
source:
  provider: openai
  model: voice-model-name
  interaction_mode: voice
source_observations:
  evidence_types: [transcript, timing, voice_model_observation]
  parts:
    - part: 1
      topics: [study, home]
    - part: 2
      topic: a useful skill
    - part: 3
      topics: [education, technology]
  transcript: "..."
  fluency_events:
    - type: long_pause
      count: 3
      location: Part 2
  pronunciation_observations: []
source_model_estimate:
  model: voice-model-name
  estimated_overall: 6.0
  confidence: low
  criterion_scores:
    - criterion: FC
      score: 6.0
      confidence: medium
      evidence_source: timing
      evidence: ["Several long pauses in Part 2"]
local_evaluation:
  status: partial
  evaluator_model: local-agent-model
  rubric:
    publisher: IELTS
    standard: IELTS Speaking Band Descriptors
    version: "current"
    source_reference: https://ielts.org/cdn/ielts-guides/ielts-speaking-band-descriptors.pdf
  criterion_scores:
    - criterion: FC
      score_low: 6.0
      score_high: 6.5
      confidence: medium
      evidence_source: mixed
      evidence: ["The learner develops Part 3 answers but pauses when searching for language."]
    - criterion: LR
      score: 6.0
      confidence: medium
      evidence_source: transcript
      evidence: ["Meaning remains clear, but 'important' is repeatedly reused."]
    - criterion: GRA
      score_low: 5.5
      score_high: 6.0
      confidence: medium
      evidence_source: transcript
      evidence: ["Complex clauses are attempted but tense control is inconsistent."]
errors:
  - tag: FC_LONG_PAUSE
    count: 3
    evidence: Part 2
feedback:
  priorities:
    - Extend Part 3 answers with a reason and example.
```

A text-based partial profile must not contain a complete Speaking overall. Add a
local PRON estimate only when audio or explicit voice-model pronunciation
observations exist.
