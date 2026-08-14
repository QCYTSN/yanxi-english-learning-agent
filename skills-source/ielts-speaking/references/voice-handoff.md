# Voice handoff

Prepare this compact instruction for the voice-capable assistant:

```text
Session ID: S-YYYYMMDD-001
Run an IELTS Speaking practice in three parts.
Do not correct or evaluate me during the mock.
After the final Part 3 answer, return:
- all questions asked;
- the fullest transcript available, otherwise an answer summary;
- observed long pauses, fillers, repetition and self-correction with locations;
- pronunciation or intelligibility observations only when you actually heard them;
- major grammar and vocabulary errors;
- repeated fillers or long pauses you observed;
- three priorities for the next session.
If you provide a score, label it as the source voice model's provisional AI
training estimate. Do not present it as Yanxi's final evaluation.
```

The returned report should be saved under
`IELTS_HOME/sessions/speaking/` and independently reviewed locally against the
official IELTS Speaking Band Descriptors.
