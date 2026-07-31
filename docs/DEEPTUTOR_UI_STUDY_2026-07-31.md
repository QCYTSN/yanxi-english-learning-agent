# DeepTutor UI study and IELTS translation

Date: 2026-07-31

This note studies DeepTutor as an interaction and proportion reference. It does
not copy DeepTutor branding, illustrations, product taxonomy, or page content.
The target remains an IELTS Academic learning product whose primary surfaces are
practice, evidence-based feedback, a local corpus, and progress.

## Public implementation reviewed

- `web/app/globals.css`
- `web/app/layout.tsx`
- `web/components/layout/AppShell.tsx`
- `web/components/sidebar/SidebarShell.tsx`
- `web/components/settings/SettingsHub.tsx`
- `web/components/settings/SettingsMain.tsx`
- `web/components/settings/SettingsSectionGrid.tsx`
- `web/components/settings/SettingsStatusPanel.tsx`
- `web/components/settings/SettingsBreadcrumb.tsx`
- `web/app/(workspace)/home/[[...sessionId]]/page.tsx`

Source: <https://github.com/HKUDS/DeepTutor> (Apache-2.0).

## Why DeepTutor feels calm

DeepTutor's quality does not come from a large number of visual effects. It
comes from consistently small decisions:

1. The expanded rail is only 220 px and the compact rail is 60 px. Navigation
   text is 13.5 px, icons are normally 16 px, and rows are short.
2. The main conversation axis is 960 px. Settings use a roughly 1024 px content
   frame. These widths remain consistent between header, content and controls.
3. Geist handles compact UI text while Lora is reserved for editorial titles
   and prose. Body prose is 16 px with a 1.75 line height.
4. The neutral theme uses almost-white surfaces, restrained borders and one
   chromatic primary. Most hierarchy comes from spacing and type, not colour.
5. Settings are a separate control plane. The overview shows a compact status
   strip and six categories; details use breadcrumbs and progressive disclosure.
6. Empty chat puts one large question and one input on a quiet canvas. Secondary
   controls live inside or beside that input rather than becoming dashboard
   cards.
7. Motion is usually 150–220 ms and communicates state. Reduced-motion support
   is global.
8. The app shell uses one viewport and deliberate internal scrolling, preventing
   the sidebar, composer and work area from drifting independently.

## What should not be copied

- Chat is DeepTutor's core product surface; it is not the core of IELTS Study
  Desk. Our home intent box routes to a structured learning flow and must not
  become a general conversation history.
- DeepTutor exposes many broad learning and agent surfaces. Our normal
  navigation should remain Today, Practice, Library and Progress.
- Its purple Glass theme, terracotta Cream theme and mascot branding are not
  appropriate IELTS identifiers.
- The IELTS product must preserve exam constraints that a general tutor does
  not have: Reading answer integrity, Writing V1/V2 order, silent Speaking mocks,
  Listening playback rules and confidence-labelled estimated scores.

## IELTS translation: Academic Reading Room

The visual subject is an adult learner's IELTS Academic reading room: clean exam
paper, an editorial title page, pencil annotations and evidence tabs. It should
feel focused and exact rather than institutional or decorative.

### Type

- UI and Chinese body: Segoe UI Variable, Microsoft YaHei UI and Noto Sans CJK.
- Editorial headings and passages: Charter, Iowan Old Style, Palatino Linotype,
  Source Han Serif SC and the platform serif fallback.
- IDs, timers and evidence coordinates: Cascadia Mono and Consolas.
- Scale: 12 / 13 / 14.5 / 16 / 20 / 24 / 40 px. Large type is reserved for the
  Today question and reading titles.

### Colour

- Exam paper: `#FBFCFA`
- Quiet rail: `#F2F4F1`
- Academic ink: `#18211F`
- Oxford blue: `#254C61`
- Evidence teal: `#0D6B62`
- Pencil amber: `#A4641B`
- Rule: `#DDE3DF`
- Secondary text: `#66736E`

Colour is functional: blue is navigation and primary structure; teal marks
grounded evidence and learning completion; amber marks timing and attention.

### Proportion

- Desktop rail: 220 px; compact tablet rail: 72 px.
- Context bar: 56 px.
- Today launcher: 920 px.
- Settings: 1024 px.
- Ordinary pages: 1240 px.
- Reading, Writing and full mocks: up to 1480 px.
- Comfortable desktop page padding: 32 px; mobile: 16 px.

### Spacing and surfaces

- Four-pixel base with 8 / 12 / 16 / 20 / 24 / 32 / 40 / 56 / 72 steps.
- Category cards are around 120–132 px tall, not dashboard-sized.
- Most surfaces use a one-pixel rule and no shadow. Floating submission or
  active timed-task controls may use one quiet shadow.
- Radii are 6, 10 and 14 px. Pills are reserved for short statuses.

### Signature

The recognisable IELTS element is the evidence margin: question numbers,
TextAnchors, answer states and examiner evidence share one ruled visual
language. This is structural, not decoration, and should appear consistently in
Reading, Writing feedback and review history.

## Page decisions

### Today

One question, one intent field, four compact subject shortcuts, and at most one
resume or recommendation row. No model selector, system health, review queue or
analytics wall.

### Practice

Four subject workspaces and complete mocks. The page chooses a learning action;
it does not expose backend terminology.

### Reading and full mocks

Desktop uses passage left and questions right, with stable independent positions
only where the exam workflow requires them. Paragraph labels, question groups,
word limits and navigation follow IELTS conventions. Answers remain hidden until
submission.

### Settings

The overview is status plus categories. Model details, OAuth, API keys, local
models and external agents are progressively disclosed. Every detail route has
Settings / Category breadcrumbs and a predictable way back.

## Acceptance

- Verify 390, 768, 1024, 1440 and 1680 px widths.
- Normal body contrast is at least 4.5:1.
- Minimum mobile control height is 44 px.
- Keyboard focus is visible and route changes focus the main landmark.
- No learning page exposes provider configuration.
- No page becomes a wall of equally weighted cards.
- Reading prose remains comfortable at 16–18 px and 1.7–1.8 line height.
- Motion respects `prefers-reduced-motion`.
