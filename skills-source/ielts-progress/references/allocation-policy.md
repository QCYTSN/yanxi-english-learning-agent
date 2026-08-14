# Allocation policy

The default strategic split is approximately:

- Listening 35%
- Reading 35%
- Writing 20%
- Speaking 10%

Interpret this as “Listening and Reading raise overall score; Writing and
Speaking protect required sub-scores.” It is not immutable.

The CLI considers:

- recent module averages and sample size;
- target and minimum-required scores;
- structured Writing/Speaking criterion risks;
- inactivity by module;
- previous saved allocation;
- maximum per-period shift;
- proximity to the exam date.

Only comparable, usable evidence may influence automatic allocation:

- official results and verified answer-key estimates;
- medium/high-confidence local AI training estimates;
- medium/high-confidence local rubric criterion scores.

Exclude partial Speaking profiles, low-confidence AI estimates and source-model
provisional scores. Legacy records with unspecified provenance may remain visible,
but reports should identify them as legacy rather than silently relabel them.

Use `xiyan allocation` to persist one recommendation per planning cycle.
Do not manually make a larger change unless the user explicitly overrides the
policy with a reason.
