# IELTS Study Desk design system

**Direction:** IELTS Academic reading room
**Density:** 5/10 · **Motion:** 2/10 · **Tone:** calm, exact, inviting

The interface is an adult IELTS Academic workspace, not an AI dashboard. It
should make the learner want to begin one useful task. Model configuration,
runtime diagnostics and developer tools stay out of learning pages.

## Principles

1. Put one learning intention before statistics and configuration.
2. Keep normal navigation to Today, Practice, Library and Progress.
3. Isolate Settings at the bottom of the navigation rail.
4. Show Agent/model provenance in feedback evidence and Settings, not as global
   chrome on every learning page.
5. Prefer one strong surface and a small number of quiet rows over card walls.
6. Preserve module integrity: Writing revision order, Reading progressive
   hints, Speaking mock silence and confidence-labelled estimated scores.
7. Use Chinese for product language and English only for IELTS terms or compact
   evidence labels.

## Tokens

| Role | Value |
|---|---|
| Academic ink | `#18211F` |
| Oxford blue | `#254C61` |
| Oxford blue hover | `#1B3B4C` |
| Evidence teal | `#0D6B62` |
| Evidence teal hover | `#095950` |
| Pencil amber | `#A4641B` |
| Danger | `#A33B35` |
| Exam paper | `#FBFCFA` |
| Navigation paper | `#F2F4F1` |
| Sheet | `#FFFFFF` |
| Muted sheet | `#F4F6F4` |
| Rule | `#DDE3DF` |
| Secondary text | `#66736E` |
| Focus | `#1976A5` |

Typography must work offline:

- UI/body: `"Segoe UI Variable", "Microsoft YaHei UI", "Noto Sans CJK SC", sans-serif`
- Editorial/reading: `Charter, "Iowan Old Style", "Palatino Linotype", "Source Han Serif SC", "Songti SC", serif`
- IDs/evidence: `"Cascadia Mono", "SFMono-Regular", Consolas, monospace`

Use a 4 px spacing base and the 8 / 12 / 16 / 20 / 24 / 32 / 40 / 56 / 72
steps. The type scale is 12 / 13 / 14.5 / 16 / 20 / 24 / 40 px. Standard
radii are 6 px, 10 px and 14 px. Pills are
reserved for short statuses. Shadows are subtle and used only for the active
task, launcher focus and floating submission controls.

## Layout

- Desktop: 220 px navigation rail + 56 px workspace bar.
- Today content: centered 920 px launcher column with generous vertical space.
- Settings content: maximum 1024 px.
- General content: maximum 1280 px. Reading and Writing workspaces may use
  1480 px.
- Tablet: 72 px icon rail, then single-column content.
- Mobile: four learning items plus a separated Settings item in the bottom
  navigation; minimum touch target 44 px; no content behind the bar.
- Learning page headers are compact. The Today launcher is the only page that
  uses a large editorial question.

## Core surfaces

### Today

- one editorial learning question;
- one natural-language intent input;
- four compact module shortcuts;
- at most one resumable activity row;
- at most one recommendation line;
- no review queue, model selector, system health or diagnostic cards.

The intent input routes deterministically and is not presented as a chat
history. Its heading states one useful learning intention; decorative rules do
not substitute for explanatory copy.

### Settings

The overview uses a small status strip and category cards:

- Profile;
- Models;
- Data and backups;
- Teaching trust;
- Advanced;
- System health.

Detailed forms appear only after opening a category. External CLI Agents live
under Advanced and are labelled as non-teaching tools.

### Practice and feedback

- use split or ruled workspaces rather than nested dashboards;
- keep source text and learner writing visually quiet;
- attach evidence to exact TextAnchors;
- display score confidence and actual model provenance;
- never display deterministic pipeline output as IELTS feedback.

## Components

- Use Lucide icons; no emoji, CSS drawings or inline handcrafted SVG icons.
- Buttons are rectangular with 6 px radius and stable hover states.
- Cards use 1 px rules and little or no elevation.
- Fields use visible labels, 16 px text on mobile and a 3 px focus ring.
- Charts include text summaries and accessible titles; colour is never the
  only signal.
- Motion is limited to 140–220 ms colour or position transitions and respects
  `prefers-reduced-motion`.

## Forbidden

- global Agent/model badges on learning pages;
- generic chat history as the default learning experience;
- purple/pink AI gradients, glassmorphism or decorative blobs;
- a page made entirely of rounded cards;
- remote fonts or assets required for first render;
- hover scaling, layout shifts, emoji icons or low-contrast body text;
- placing OAuth, API Key and CLI Agents as peer choices in the same primary
  screen.

The implementation rationale and DeepTutor source study live in
`docs/DEEPTUTOR_UI_STUDY_2026-07-31.md`.

## Delivery checks

- keyboard navigation, skip link, visible focus and semantic landmarks;
- contrast at least WCAG AA;
- verify 390, 768, 1024 and 1487 px widths;
- verify long Chinese and English text, empty/loading/error states;
- verify the launcher, four shortcuts, resume row and all Settings categories;
- typecheck, lint, unit tests and production build pass;
- compare the rendered Today route with the selected 1487 x 1058 reference
  before visual acceptance.
