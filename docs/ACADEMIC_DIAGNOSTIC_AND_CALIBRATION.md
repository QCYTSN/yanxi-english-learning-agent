# Academic scope, diagnostics and calibration

## Academic-only scope

IELTS AI Coach supports IELTS Academic. It does not treat General Training as a
cosmetic setting: General Training uses different Reading material and a letter
for Writing Task 1. A General Training Profile is therefore rejected rather than
silently evaluated against Academic workflows.

## Quick diagnostic

The quick diagnostic is the recommended first-use baseline:

- recent verified Listening result or keyed user-owned practice result;
- one 20-minute Reading passage with no hints;
- one 40-minute Academic Writing Task 2 response;
- one uninterrupted three-part Speaking mock.

```powershell
ielts-coach diagnostic start --mode quick
ielts-coach diagnostic attach <diagnostic-id> <completed-session-id>
ielts-coach diagnostic status <diagnostic-id>
ielts-coach diagnostic complete <diagnostic-id>
```

Only one diagnostic can be active. Use `ielts-coach diagnostic cancel
<diagnostic-id>` when abandoning a run.

Completing all components means the diagnostic has enough task coverage. It does
not guarantee four numeric Bands. Unsupported, partial or low-confidence values
remain unknown.

## Full diagnostic

The full mode requires a complete keyed 40-question Listening test, a complete
60-minute 40-question Academic Reading test, timed Academic Writing Task 1 and
Task 2, and an uninterrupted three-part Speaking mock of at least 11 minutes with
actual audio/transcript observations. Full-length copyrighted practice material
is supplied by the user and is not bundled with this repository.

## Strict timed Reading

Start the Session before displaying the passage set:

```powershell
ielts-coach session start reading --passage-id START-RP-001 --mode timed-practice --time-limit-minutes 20
ielts-coach question set START-RP-001
```

Before submission the Agent gives no hints, vocabulary help, partial marking or
answer feedback. The data layer blocks answer-bearing views for an active timed
Session. The Session must save `submitted_at` before answer reveal and review.

Starter passages demonstrate the workflow but are shorter than official IELTS
Academic passages; they are not a full mock substitute.

## Blind Writing and Speaking calibration

Calibration needs user-authorised scored references. Store the response in a
neutrally named file and register its official result separately. A case
declares `reference_kind: official_scored_sample` so informal tutor scores are
not silently mixed into the official-reference calibration set:

```powershell
ielts-coach calibration case-import case.yaml
ielts-coach calibration case-list
ielts-coach calibration prepare --model codex-model-label --output blind-run.yaml
```

The prepared worksheet contains the response path, hash and empty prediction
fields, but no official score. The active Agent applies the official IELTS Band
Descriptors and fills the prediction. Then import and report:

```powershell
ielts-coach calibration import-run blind-run.yaml
ielts-coach calibration report
```

Calibration reports model error; it does not certify the model as an examiner.
Small or biased reference sets support only low-confidence conclusions. Do not
commit or redistribute third-party scored samples unless their licence permits it.
