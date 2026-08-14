# Academic diagnostic policy

The diagnostic creates a training baseline, not an official IELTS result.

## Quick diagnostic

Recommend this for first use. It requires:

- a recent verified Listening result or a user-owned practice result with a key;
- one Reading passage in strict `timed-practice` mode, normally 20 minutes;
- one Academic Writing Task 2 response, normally 40 minutes;
- one uninterrupted three-part Speaking mock.

Start and track it with:

```bash
xiyan diagnostic start --mode quick
xiyan diagnostic attach <diagnostic-id> <completed-session-id>
xiyan diagnostic status <diagnostic-id>
xiyan diagnostic complete <diagnostic-id>
xiyan diagnostic cancel <diagnostic-id>
```

Only one diagnostic may be active at a time. Cancel an abandoned run before
starting another.

## Full diagnostic

Use a complete timed 40-question Academic Listening test, a complete 60-minute
40-question Academic Reading test, timed Academic Writing Task 1 and Task 2, and
an uninterrupted three-part Speaking mock of at least 11 minutes with actual
audio/transcript observations. The learner supplies legally obtained full-length
material.

## Interpretation

- A completed component can satisfy coverage without producing a numeric Band.
- Missing or low-confidence numeric evidence remains unknown.
- Only verified objective results and medium/high-confidence local rubric
  estimates may populate the stored baseline.
- Never average incomplete components into a pretend overall score.
