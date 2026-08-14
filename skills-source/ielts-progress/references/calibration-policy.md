# Writing and Speaking calibration

Calibration compares blind model estimates with authorised scored references.
It does not make an AI an official examiner.

1. The user registers a legally usable scored sample. Store the official result
   in the calibration case, not in the candidate response file. The case must
   declare `reference_kind: official_scored_sample`.
2. Prepare a blind worksheet. The worksheet exposes the response and criterion,
   but not the official score.
3. The active Agent applies the relevant official IELTS Band Descriptors and
   fills the prediction fields.
4. Import the completed worksheet and inspect MAE and the configured tolerance
   pass rate.

```bash
xiyan calibration case-import <case.yaml>
xiyan calibration prepare --model <client-model-label> --output <run.yaml>
xiyan calibration import-run <run.yaml>
xiyan calibration report
```

Use neutral response filenames so the official Band is not leaked through a
path. Never bundle copyrighted official samples in the repository. A small or
unrepresentative calibration set supports only a low-confidence conclusion.
