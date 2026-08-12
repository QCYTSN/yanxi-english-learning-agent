---
name: 言蹊 (Yanxi)
description: A calm, evidence-led academic reading room for focused IELTS practice.
colors:
  paper: "#FBFCFA"
  surface: "#FFFFFF"
  surface-muted: "#F2F4F1"
  surface-subtle: "#F7F8F6"
  ink: "#18211F"
  muted: "#66736E"
  border: "#DDE3DF"
  border-strong: "#B7C1BB"
  primary: "#254C61"
  primary-hover: "#1B3B4C"
  primary-soft: "#E9F0F3"
  evidence: "#0D6B62"
  evidence-soft: "#E5F2EF"
  warning: "#A4641B"
  warning-soft: "#FBF0DF"
  danger: "#A33B35"
  danger-soft: "#F9E8E6"
  focus: "#1976A5"
typography:
  display:
    fontFamily: 'Charter, "Iowan Old Style", "Palatino Linotype", "Source Han Serif SC", "Songti SC", SimSun, serif'
    fontSize: "clamp(2.15rem, 3.7vw, 2.85rem)"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.04em"
  headline:
    fontFamily: '"Segoe UI Variable", "Microsoft YaHei UI", "Noto Sans CJK SC", "Segoe UI", sans-serif'
    fontSize: "clamp(1.15rem, 1.5vw, 1.45rem)"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.025em"
  body:
    fontFamily: '"Segoe UI Variable", "Microsoft YaHei UI", "Noto Sans CJK SC", "Segoe UI", sans-serif'
    fontSize: "0.90625rem"
    fontWeight: 400
    lineHeight: 1.62
    letterSpacing: "normal"
  reading:
    fontFamily: 'Charter, "Iowan Old Style", "Palatino Linotype", "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", SimSun, Georgia, serif'
    fontSize: "1.06rem"
    fontWeight: 400
    lineHeight: 1.8
    letterSpacing: "normal"
  label:
    fontFamily: '"Segoe UI Variable", "Microsoft YaHei UI", "Noto Sans CJK SC", "Segoe UI", sans-serif'
    fontSize: "0.75rem"
    fontWeight: 700
    lineHeight: 1.35
    letterSpacing: "0.08em"
  mono:
    fontFamily: '"Cascadia Mono", "SFMono-Regular", Consolas, monospace'
    fontSize: "0.78rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
rounded:
  xs: "4px"
  sm: "6px"
  md: "10px"
  lg: "14px"
  composer: "20px"
  pill: "99px"
spacing:
  xxs: "4px"
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  xxl: "48px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "44px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "44px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "9px 12px"
    height: "44px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "24px"
  status:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.muted}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
    height: "24px"
  composer:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.composer}"
    padding: "14px 18px 8px"
---

# Design System: 言蹊 (Yanxi)

> This file is the visual and interaction authority for the product. `PRODUCT.md` owns product truth; this file owns the durable visual world. When older visual notes or current CSS conflict with this file, implement toward this file and update the tokens only through an explicit design decision.

## Overview

**Creative North Star: "The Academic Reading Room / 学术阅读室"**

言蹊 (Yanxi) should feel like a quiet place where serious learning becomes easier to begin: editorial enough to invite reading, structured enough to support a learning path, and restrained enough that the learner's passage, answer, essay, or conversation remains the dominant object. The product is not a generic AI chat shell and not a school administration dashboard. It is an English teacher's desk expressed as a local desktop application.

The visual system combines a paper-like neutral field, measured typography, one-pixel rules, and sparse semantic color. It may learn from DeepTutor's calm proportions, generous reading widths, and state-dependent chat composition, but it must retain its own IELTS identity, evidence-led teaching language, four-module workflows, and local-first trust model. No visual resource may require a network request at runtime.

Most screens are in **Operate** mode: compact controls, clear hierarchy, and predictable task state. Reading passages, feedback, and teacher responses enter **Read** mode: wider line-height, fewer borders, and longer uninterrupted text. The dialogue surface is a hybrid: the composer is operational; the teacher response is editorial.

**Key Characteristics:**

- Calm academic editorial tone, never sterile enterprise software.
- Paper, ink, ruled divisions, and an evidence margin instead of decorative dashboards.
- A compact global shell with learning in the foreground and configuration kept inside Settings.
- Flat by default; elevation appears only for floating controls, overlays, and the active composer.
- Serif typography earns attention on reading and reflection; sans-serif typography manages the application.
- Motion is brief, interruptible, and subordinate to input latency and scroll stability.

## Colors

The palette is an ink-and-paper system with two deliberately different accents: Oxford blue for action and navigation, evidence teal for verified learning evidence and progress.

### Primary

- **Oxford Study Blue:** use for the single primary action, active links, selected controls, and high-level navigation. It should not flood entire panels.
- **Mist Blue:** use as a low-contrast selected or hover background, never as a substitute for hierarchy.

### Secondary

- **Evidence Teal:** reserve for grounded evidence, confirmed progress, correct-answer states, and the active rail marker. It signals instructional meaning, not decoration.
- **Evidence Wash:** use behind short evidence notes and verified states where a full teal fill would be too loud.

### Tertiary

- **Review Amber:** use for learner attention, incomplete evidence, review priorities, and limitations.
- **Correction Red:** use only for destructive actions, failed validation, and errors that block continuation. Do not use red for ordinary IELTS mistakes.

### Neutral

- **Reading Paper:** the application canvas and long-form reading field.
- **Desk Surface:** primary panels, forms, and content sheets.
- **Quiet Rail:** navigation and subdued grouped regions.
- **Study Ink:** all high-emphasis copy and icons.
- **Pencil Grey:** secondary descriptions, metadata, and inactive controls.
- **Ruled Line:** structural separation; prefer it to extra cards and shadows.

### Named Rules

**The Two Accents Rule.** Oxford blue means action; evidence teal means verified learning evidence. Never swap them merely to add variety.

**The Rare Warning Rule.** Amber and red must remain visually scarce. If a screen appears warm or red at a glance, warning color is being overused.

**The Paper Continuity Rule.** Large reading and conversation regions remain on the reading-paper field; do not fragment them into alternating tinted cards.

## Typography

**Display Font:** platform editorial serif stack, led by Charter and Iowan Old Style with appropriate CJK serif fallbacks.

**Body Font:** platform UI sans stack, led by Segoe UI Variable and Microsoft YaHei UI with appropriate CJK sans fallbacks.

**Label/Mono Font:** the body stack for labels; Cascadia Mono or the platform monospace stack only for paths, IDs, logs, and technical values.

**Character:** serif text should feel considered and readable, not literary or ornamental. Sans-serif text should feel neutral, compact, and familiar on Windows. Fonts and icons are distributed with the application or resolved from the operating system; no CDN font request is allowed.

### Hierarchy

- **Display** (600, fluid 34–46px, 1.15): Today greeting, major learning result, and rare empty-state invitation. Use at most once per view.
- **Headline** (700, fluid 18–23px, 1.3): section and panel headings in learning and settings surfaces.
- **Title** (650–720, 15–18px, 1.4): exercise titles, dialogue titles, list items, and component headings.
- **Body** (400, 14.5–16px, 1.62): UI explanations and ordinary prose. Keep explanatory lines below roughly 72 characters when possible.
- **Reading** (400, 17–18px, 1.8–1.9): passages, essays, teacher explanations, and feedback evidence. Keep uninterrupted reading columns around 62–78 characters.
- **Label** (650–750, 11–12px, 1.35): metadata, statuses, small controls, and eyebrows. Uppercase is limited to short English evidence labels, never Chinese navigation.

### Named Rules

**The Serif Earns Attention Rule.** Serif is for reading, reflection, and the one major invitation on a page. Navigation, controls, tables, and settings remain sans-serif.

**The One Display Rule.** A viewport may have one display-sized statement. Additional headings must step down decisively instead of competing.

**The Comfortable Measure Rule.** Teacher answers and passages must be constrained by reading measure, not merely by the available screen width.

## Layout

The desktop shell uses a stable 220px learning rail and a 56px context bar. Between 721px and 1180px the rail may collapse to a 72px icon rail; at 720px and below navigation becomes a bottom bar. The content region owns the only page-level vertical scrollbar. Fixed or sticky subregions must never create ambiguous nested page scrolling.

Use four container families:

- **Dialogue:** 960–980px reading axis; the empty composer may begin at 768–920px and expands only after a conversation starts.
- **Settings:** 1024px maximum so forms remain scannable rather than becoming wide dashboards.
- **Standard learning:** 1240px maximum for Today, Library, Progress, and feedback summaries.
- **Immersive practice:** up to 1480px for split Reading, Writing, and full mock workspaces.

Spacing follows a 4px base rhythm. Default section gaps are 32–48px; card padding is 20–24px; dense row padding is 12–16px; control gaps are 8–12px. Large empty areas are acceptable only when they create a single, obvious starting point. Empty space must never separate the learner from the next action.

Reading uses a split workbench: passage on the left and questions on the right, with the original paragraph structure, headings, labels, figures, and answer constraints preserved. Writing uses prompt/evidence on the left and the editor on the right. On narrow screens these stack in task order and preserve a reachable sticky action bar.

The signature recurring spatial device is the **Evidence Margin**: a slim ruled or tinted rail beside feedback, explanations, and progress evidence. It creates continuity between Reading evidence, Writing annotations, Speaking observations, and Listening error review without turning each into a separate card type.

Responsive behavior must be proven at 320px, 720px, 980px, 1180px, 1440px, and 200% browser zoom. Touch targets remain at least 44px. Content order, keyboard order, and visual order must match.

Motion uses opacity and transforms only for ordinary state changes, normally 120–220ms. Respect `prefers-reduced-motion`. Streaming dialogue must not repeatedly trigger smooth scrolling; auto-follow occurs only while the learner remains near the bottom, and manual scrolling suspends it. Route-level pages and heavy overlays remain lazy-loaded; long message, question, and library lists use containment or virtualization before they become large enough to degrade input response.

### Named Rules

**The One Scroll Owner Rule.** Each primary view has one obvious scroll container. Split practice panes may scroll internally, but the surrounding page must remain stable.

**The Reading Axis Rule.** Long-form content aligns to a consistent 960–980px axis even on very wide displays; extra width becomes breathing room, not longer lines.

**The No Reflow Surprise Rule.** Loading, streaming, model changes, and attachment processing reserve their space and must not shift the learner's current reading position.

## Elevation & Depth

The system is flat by default. Hierarchy comes from surface tone, one-pixel rules, typography, spacing, and the Evidence Margin. Resting cards do not need a shadow. The small ambient shadow is reserved for the active composer, dropdowns, dialogs, and a deliberately lifted primary action on hover. Backdrop blur is allowed only on the sticky top context bar and overlays, and must have an opaque fallback.

### Shadow Vocabulary

- **Ambient Rest** (`0 10px 28px rgba(24, 33, 31, 0.06)`): rare floating surface such as the active composer.
- **Floating Control** (`0 8px 24px rgba(24, 33, 31, 0.10)`): menus and dialogs that must separate from content.
- **Primary Hover** (`0 4px 12px rgba(31, 83, 109, 0.18)`): primary action hover only.

### Named Rules

**The Flat by Default Rule.** If a border, spacing change, or surface tone can express hierarchy, do not add a shadow.

**The State Creates Depth Rule.** Elevation should explain that an element is floating, active, or transient; it is never ambient decoration.

## Shapes

The form language is gently squared: 6px controls, 10px content containers, and 14px large composed surfaces. The 20px radius belongs only to the conversation composer, where it indicates a single floating input object. Full pills are reserved for short statuses and compact filters. Avoid stacking rounded containers inside other rounded containers.

Borders are one pixel and neutral. Active navigation may combine a subtle surface, a thin border, and a 3px evidence marker. Images, PDF pages, and Task 1 figures preserve their own geometry and receive a restrained frame rather than decorative clipping.

### Named Rules

**The Radius Has Meaning Rule.** Small radii mean controls, medium radii mean content groups, and the large composer radius means active dialogue. Do not choose a radius by visual whim.

**The No Nested Bubbles Rule.** One content idea gets one container. Metadata, attachments, and actions should sit inside its rhythm rather than each receiving another rounded box.

## Components

### Buttons

- **Shape:** gently squared control (6px) with a minimum 44px target.
- **Primary:** Oxford blue fill, white text, compact horizontal padding, and one clear verb. A surface should normally expose only one filled primary action.
- **Hover / Focus:** darken the fill and optionally add the primary-hover shadow; keyboard focus always uses the visible focus token and is not replaced by hover styling.
- **Secondary:** white or paper surface with a strong neutral border. Hover uses the pale blue surface rather than a dark fill.
- **Ghost / Icon:** no permanent container when the surrounding context already supplies one; give it a 44px hit area and reveal a quiet surface on hover.
- **Destructive:** red appears only after the destructive intent is explicit. Confirmation copy must state the local data affected and whether recovery is possible.

### Chips

- **Style:** 24px minimum height, full pill, short label, subtle neutral or semantic wash.
- **State:** chips report state or apply a compact filter. They do not replace ordinary buttons, section headings, or question-type titles.

### Cards / Containers

- **Corner Style:** medium radius (10px), with large radius (14px) for a singular composed launcher or modal.
- **Background:** white desk surface on paper; muted surface is for navigation and grouped secondary information.
- **Shadow Strategy:** flat at rest. Use a ruled border and spacing before elevation.
- **Border:** one-pixel neutral rule; a one-pixel semantic rule or compact marker may identify an active task or evidence group.
- **Internal Padding:** 20–24px standard; 12–16px for dense list rows.

### Inputs / Fields

- **Style:** white background, strong neutral border, 6px radius, 44px minimum height, and a label that remains visible after entry.
- **Focus:** focus token outline or an equivalent 3px inset treatment with sufficient contrast.
- **Error / Disabled:** error text explains the recovery action; disabled controls retain legible labels and state why they are unavailable when that reason is not obvious.
- **Validation:** do not expose raw HTTP methods, provider payloads, stack traces, or schema errors to the learner. Technical details live in a collapsed diagnostic affordance inside Settings.

### Navigation

- **Desktop rail:** Today, Practice, Library, and Progress are the learning destinations. Settings is separated at the bottom. Conversation history appears only when relevant and supports rename and delete directly from each row's context menu.
- **Top context bar:** show location on the left and a compact active-model control plus date on the right. The model control displays the model name as the primary line; provider and connection detail move into its menu. It must not resemble a settings card.
- **Mobile:** use a four-item bottom navigation and place Settings in a secondary menu. Do not compress all desktop labels into a horizontal header.

### Study Launcher

The Today launcher has one display greeting, one calm sentence, and one composer. The attachment affordance is an icon button with an accessible label; long file-type helper text appears only on focus, hover, or after attachments are present. The four IELTS modules are compact entry points beneath the composer, not four promotional cards. One resumable task may appear below; repeated review queues do not dominate the first viewport.

### Model Switcher

The model switcher is globally available because changing the teaching model is a frequent action, but configuration is not. Its resting height is 36–40px and its desktop width is approximately 180–220px. It shows connection state without a loud badge, opens a keyboard-accessible menu, preserves the current choice during loading, and collapses to an icon at narrow widths. Provider setup, OAuth, API keys, local endpoints, and CLI agents remain in Settings.

### Conversation

Before the first message, the composer is centered as the primary invitation. After sending, the interface becomes a reading view: title in a compact header, messages on a constrained axis, and the composer anchored near the bottom. User messages are quiet right-aligned bubbles no wider than roughly 75%; assistant responses are borderless editorial blocks with generous paragraph spacing and a small `IELTS 教师` label.

Attachments belong to the message that introduced them. Show a collapsed `N 个材料` disclosure immediately below that message, with filenames inside when expanded. Do not maintain a permanent empty materials sidebar. Enter sends; Shift+Enter inserts a line break. Auto-scroll follows new output only while the learner is already near the bottom.

### Practice Workspaces

- **Reading:** preserve passage paragraphs and task-group instructions; left passage/right questions on desktop; progressive hints before reveal; evidence explanation after submission.
- **Writing:** show Task 1/Task 2 and a meaningful title; prompt or Task 1 media beside a distraction-free editor; feedback follows evidence, priorities, learner V2, then model alternative.
- **Listening:** player, question sheet, and transcript review are distinct states. Transcript and timestamps remain hidden until the integrity policy allows review.
- **Speaking:** Part 1/2/3 are visible classifications. Full mock mode gives no correction until the mock ends; voice/live tools may remain external when local integration is unavailable.
- **Feedback:** use the Evidence Margin, readable excerpts, three priorities, confidence labels, and version comparison. Do not present AI estimates as official scores.

### Loading, Empty, and Error States

Loading states use reserved space, plain language, and a compact progress indicator. Empty states always explain the next meaningful action. Learner-facing errors say what failed, what was preserved locally, and what to do next; diagnostic identifiers and provider traces remain available behind a disclosure for troubleshooting.

## Do's and Don'ts

### Do:

- **Do** make the learner's passage, question, essay, recording, or teacher answer the largest object on the page.
- **Do** separate learning surfaces from Settings and advanced model or Agent configuration.
- **Do** use meaningful titles and IELTS classifications instead of internal IDs, `full-mock`, or engineering status strings.
- **Do** preserve original question structure, answer constraints, passage formatting, and evidence anchors.
- **Do** keep navigation, the active model, save state, and the next action visible without turning them into competing cards.
- **Do** keep all fonts, icons, and visual assets offline-capable and test Windows first with full macOS and Linux usability.
- **Do** measure scroll stability, input response, bundle growth, long-list behavior, keyboard flow, reduced motion, and 200% zoom before calling a visual pass complete.

### Don't:

- **Don't** turn Today into a dashboard of metrics, queues, provider details, and repeated cards.
- **Don't** copy DeepTutor's logo, illustrations, exact component styling, or general-purpose product architecture; extract only transferable proportion and interaction principles.
- **Don't** use remote fonts, CDN icons, decorative gradients, glass panels, or shadows as a substitute for hierarchy.
- **Don't** wrap every paragraph, attachment, status, and action in its own rounded rectangle.
- **Don't** expose raw runtime, schema, HTTP, OAuth, or CLI errors in the learning flow.
- **Don't** auto-scroll a conversation after the learner has moved away from the bottom.
- **Don't** let a visual redesign weaken IELTS answer integrity, active revision, speaking mock integrity, privacy consent, or Runtime validation.
