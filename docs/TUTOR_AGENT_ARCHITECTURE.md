# IELTS Tutor Agent architecture

Status: frozen product decision and implementation boundary.

## Product core

言蹊 (Yanxi) has three connected learning surfaces:

```text
Tutor conversation <-> Formal practice and assessment -> Review and progress
        ^                                                   |
        +---------------------------------------------------+
```

Conversation is the low-friction teaching entry. Formal Practice remains the
authority for attempts, answer reveal, scores and learning records. Review and
Progress turn validated evidence into longitudinal learning work.

The product is not a general autonomous Agent. The Tutor Agent cannot use a
shell, inspect arbitrary files, issue SQL, alter answer keys or write formal
learning state.

## Turn execution

Each message is routed into one of two paths:

```text
simple greeting or fixed IELTS fact
  -> one constrained model call

material, history, review, planning or multi-step request
  -> planning contract
  -> allowlisted Runtime tool calls
  -> observations
  -> at most three planning rounds and six tool calls
  -> one validated study-help response
```

Planning and final teaching use separate JSON contracts. Runtime events retain
planning stages and tool observations. The final `study-help@1` result still
passes Schema, semantic and answer-policy validation before it becomes a
persisted assistant message.

## Authority model

| Object | Owner | Persistence | Authority |
|---|---|---|---|
| Study Thread and messages | Conversation Runtime | automatic, local | informal dialogue |
| Thread Learning State | Conversation Runtime | automatic, versioned | soft teaching continuity |
| Teaching Cycle and events | Learning Agent Kernel | revisioned, Runtime/learner mutations only | current pedagogical phase |
| Tutor Proposal | Conversation Runtime | pending until learner decision | no formal effect |
| Session, attempt, score and error | Teaching Runtime | validated and idempotent | formal IELTS learning record |
| Objective, activity, mastery evidence and schedule | Learning Agent Kernel | revisioned or idempotent, local | longitudinal learning state |
| Learner Memory and revisions | learner through confirmation | versioned, conflict-aware, expirable and removable | personalisation only |

Thread Learning State records the current material, question, learner answer
and reasoning when explicitly supplied, teaching goal, hint level, answer
stage, evidence references, unresolved issue and correction status. The model
does not directly overwrite this object. Runtime derives it from canonical
context, validated output and recorded tool execution.

An active Teaching Cycle is linked to the thread when dialogue becomes a
specific learning task. The Tutor may recommend a move, while the Runtime owns
the explicit diagnose, teach, guided-practice, independent-practice, assess,
review and consolidate transition graph. Validated Tutor fields can create an
observation; Tutor prose and hidden reasoning cannot mutate the cycle.

## Answer integrity

Conversation follows the same Reading boundary as Practice:

- during an unanswered task: progressive hints and answer withholding;
- after an attempt: passage-grounded review is allowed;
- explicit answer request: reveal only when evidence is sufficient;
- no authoritative key: correctness remains unverified;
- formal mock: explanation and answer reveal are locked.

Writing keeps evidence and priorities before learner revision and any model
alternative. Speaking keeps correction out of an active mock.

## Tools

The initial tool registry contains only bounded IELTS operations:

- inspect registered thread material and extracted text;
- locate passage evidence and return anchored quotes;
- read learner-visible question context without hidden answers;
- read learner snapshot, due reviews, approved materials, Session status,
  learning objectives, skill mastery, learning history and learner-managed
  memories;
- read teaching policy and compare learner Writing versions;
- propose Practice, review items, memories or material promotion.

Read tools execute inside the Runtime. Command tools only create proposals.
After learner confirmation, the Runtime validates and executes the supported
action.

Only effective learner memories are returned: active, current, non-expired and
not in an unresolved contradiction. Duplicate confirmations are idempotent.
Conflicting statements remain local and visible for learner resolution instead
of being silently selected by the model.

## Retrieval strategy

The implementation uses direct multimodal context, structured tables, bounded
rolling summaries and SQLite FTS5 history search. A deterministic Context
Engine applies separate budgets to recent messages, attachments, summary,
learning state, proposals and retrieved history. Every request records selected
and omitted source IDs plus a context fingerprint, so a long conversation can
be reproduced without resending its entire transcript.

Embeddings, a vector database, Docker and a separate RAG service are not
dependencies of the product core. They require measured retrieval failures and
a separate product decision rather than being introduced as speculative
infrastructure.

The learner snapshot is assembled across two explicit authority layers:
IELTS-specific Sessions, scores, errors and answer state remain in the Teaching
Runtime; objectives, skill evidence and review timing come from the Learning
Agent Kernel. See [Learning Agent Kernel](LEARNING_AGENT_KERNEL.md).

## Speaking boundary

Speaking practice is two-step: the Tutor prepares a scenario prompt (role,
cue, follow-ups) that the learner takes to the voice tool of their choice,
then evaluates the attempt the learner brings back. The product does not
integrate STT/TTS; real-time audio conversation remains external until a
separate product decision is made.
