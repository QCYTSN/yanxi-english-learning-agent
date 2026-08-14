# Usage workflows

Current usage guide for Yanxi (言蹊). Two entry surfaces share the same
authoritative Teaching Runtime: the conversation-first browser UI and the
`xiyan` CLI (the `ielts-coach` name remains a compatibility alias).

## Fast natural-language entry

Learners do not need to invoke the router before a clear task. Requests such
as "练一篇写作", "解释这道阅读题为什么选 C" or "给我一个口语练习场景" should
trigger the matching specialist directly. The Agent must not run full progress
and diagnostic reports before teaching.

Use `xiyan study-context --module <module>` only when selecting or
personalising a task. Use the command without `--module` only for a daily
plan, first-use setup or a cross-module decision.

## Everyday entry: the conversation

The default General English track is conversation-first. Writing, reading,
vocabulary and grammar work happens in the Today composer or a Study Thread:

```text
把写好的英文贴给老师 → 证据与优先级先行 → 学习者修改 V2 → 对比与替代版本
贴一段文章 → 讲解、生词自动成为候选词 → 确认后进入间隔复习
```

## Writing (IELTS track)

The browser Practice workspace runs the formal loop: independent V1 →
evidence score → three priorities → learner V2 → comparison → final review →
`versions`, `criterion_scores` and errors saved.

The same loop is available over the CLI when a Session already exists:

```powershell
xiyan session start --module writing
xiyan session submit-writing <session.md>
xiyan session apply-writing-review <session.md>
xiyan session finish <session.md>
```

## Reading guided solving and wrong-answer review

Start a Reading Session from the Practice workspace (the public install starts
with an empty question bank; import your own material first). During an
unanswered task the teacher gives progressive hints only; after an attempt the
review is passage-grounded:

```powershell
xiyan session hint-reading <session.md>
xiyan session submit-reading <session.md>
xiyan session apply-reading-review <session.md>
```

## Speaking: two-step practice

Speaking uses a lightweight handoff instead of in-app recording:

1. In the conversation, ask for a scenario ("给我一个口语练习场景") and take
   the prompt to any voice tool you like;
2. Practice uninterrupted — no correction during the run;
3. Paste the transcript back into the conversation for review on clarity,
   naturalness and grammar. A transcript supports fluency and range feedback;
   it cannot support pronunciation judgement without audio.

## Listening: typing and 听言 practice

The bundled practice entries (打词 / 听言) need no model and no imported
material: the system speaks your own words plus the starter list through the
browser's local speech, and you type what you hear. Misses feed learner memory
and schedule a one-day review.

## Vocabulary loop

Words the tutor explains in conversation become confirmable candidates (undo
and already-known dedup). High-frequency words carry offline word cards
(phonetic, part of speech, definitions, inflections); other words can be
enriched on demand through the configured model. Review uses an adaptive
1-2-4-7-14-30-60 day ladder: recalled words advance, missed words return the
next day.

## Corpus and weekly planning

```powershell
xiyan corpus import <manifest.yaml>
xiyan corpus list
xiyan learning-profile
xiyan trends
xiyan weekly-report
```

## Errors, stories and diagnostics

```powershell
xiyan error list
xiyan error set-status <tag> resolved
xiyan story add <story.md>
xiyan diagnostic start
```

## Backups and health

Automatic backups run weekly (five kept). Manual control stays available:

```powershell
xiyan backup create
xiyan backup list
xiyan doctor
```
