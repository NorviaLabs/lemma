---
name: OpenLemma
description: A learning app you can touch — every idea a live model on a bright white card, one step at a time, with ink actions, ultramarine live marks and lemon highlights.
colors:
  canvas: "#f4f5f7"
  surface: "#ffffff"
  ink: "#111318"
  body: "#343844"
  mute: "#626877"
  faint: "#9ca1ad"
  rule: "#e6e8ed"
  rule-strong: "#cfd3dc"
  fill: "#e9ebf0"
  ultramarine: "#3a4ff0"
  ultramarine-press: "#2a3cd0"
  ultramarine-soft: "#e9ecff"
  lemon: "#ffe46b"
  lemon-soft: "#fff6cc"
  lemon-ink: "#4d3b00"
  lemon-edge: "#b38a00"
  link: "#2f45d8"
  good: "#137a4b"
  good-bg: "#e3f6ec"
  bad: "#c2362b"
  bad-bg: "#fde8e5"
  model-0: "#2563d9"
  model-1: "#b56f00"
  model-2: "#12865a"
  model-3: "#7a4fd6"
  model-4: "#cc3b82"
  model-5: "#0b86a6"
  model-6: "#727100"
  model-7: "#687087"
typography:
  display:
    fontFamily: "Archivo, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "clamp(44px, 5vw, 74px)"
    fontWeight: 800
    lineHeight: 0.98
    letterSpacing: "-0.045em"
  headline:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "clamp(32px, 3.6vw, 46px)"
    fontWeight: 800
    lineHeight: 1.12
    letterSpacing: "-0.032em"
  title:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "clamp(26px, 2.3vw, 32px)"
    fontWeight: 800
    lineHeight: 1.12
    letterSpacing: "-0.03em"
  section:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "clamp(24px, 2.4vw, 30px)"
    fontWeight: 800
    lineHeight: 1.12
    letterSpacing: "-0.025em"
  title-sm:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  lead:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 400
    lineHeight: 1.5
  body:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.3
  readout:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "27px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.03em"
    fontFeature: "tnum"
  quote:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 500
    lineHeight: 1.45
    letterSpacing: "-0.01em"
  pin:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "11.5px"
    fontWeight: 700
    lineHeight: 1
    fontFeature: "tnum"
  mono:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "6px"
  md: "12px"
  tile: "16px"
  lg: "22px"
  card: "26px"
  pill: "9999px"
spacing:
  xs: "6px"
  sm: "10px"
  md: "14px"
  lg: "22px"
  xl: "32px"
  2xl: "40px"
  3xl: "80px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "0 20px"
    height: "46px"
  button-primary-hover:
    backgroundColor: "#2a2d36"
  button-default:
    backgroundColor: "{colors.fill}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 20px"
    height: "46px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.bad}"
    rounded: "{rounded.md}"
  nav-new-lesson:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    rounded: "{rounded.pill}"
    padding: "10px 14px"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
  model-card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: "clamp(20px, 2.4vw, 32px)"
  readout-tile:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.readout}"
    rounded: "{rounded.tile}"
    padding: "12px 14px 14px"
  readout-tile-highlight:
    backgroundColor: "{colors.lemon-soft}"
  goal-chip:
    backgroundColor: "{colors.lemon}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "6px 12px"
  tag:
    backgroundColor: "{colors.fill}"
    textColor: "{colors.body}"
    rounded: "{rounded.pill}"
    height: "26px"
    padding: "0 10px"
  step-current:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.tile}"
    padding: "16px 18px 18px"
  step-mark-current:
    backgroundColor: "{colors.ultramarine}"
    textColor: "{colors.surface}"
    rounded: "{rounded.pill}"
    size: "22px"
  note-current:
    backgroundColor: "{colors.lemon-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
  option:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.tile}"
    padding: "14px 18px"
  option-chosen:
    backgroundColor: "{colors.ultramarine-soft}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    height: "50px"
  action-bar:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.body}"
    padding: "14px 20px"
  action-bar-good:
    backgroundColor: "{colors.good-bg}"
    textColor: "{colors.good}"
  action-bar-bad:
    backgroundColor: "{colors.bad-bg}"
    textColor: "{colors.bad}"
---

# Design System: OpenLemma

## Overview

**Creative North Star: "The Live Card"**

OpenLemma is a learning app, not a page. Each idea is a tactile model on a bright white card that floats on a cool off-white canvas, and the learner moves through it one step at a time: a short note, the model, a goal, Continue. The feel is a modern 2026 product: confident type, generous space, soft depth and big touchable controls. It explains rather than decorates, and nothing about it reads as a blog post or a scholarly page.

Colour does three jobs. Ink is the action: buttons are black. Ultramarine marks whatever is live: the slider you can move, the step you are on, the progress you've made, focus. Lemon marks what is being talked about: the current note, the readout a note names, the goal. Everything else is neutral, so the model's data inks stay readable.

This world replaced the earlier ones. The user rejected the cream-and-walnut card catalogue because it "does not look like it's made in 2026", and rejected essay-style explainers (Ciechanowski) as "a normal blog post". Earlier rounds also ruled out generic SaaS, dark and techy, and childish. Brilliant's lesson flow is the reference for the interaction, and Granola or Anthropic for the shell, but OpenLemma borrows neither brand. The product was renamed from Lemma to OpenLemma on 2026-10-19 (a concept-first refocus); the rename is brand-only and the Live Card world is unchanged.

**Key Characteristics:**
- A cool canvas (#f4f5f7) with white cards; cards are separated by soft shadows, not hairline frames.
- Black buttons for the action; ultramarine (#3a4ff0) for the live mark; lemon (#ffe46b) for attention.
- Archivo for everything, heavy and tight in headlines; sentence case throughout; tabular numbers.
- Big tactile controls: thick slider tracks, round white knobs, readouts as soft tiles.
- One step at a time: a stepper of steps, a segmented progress bar per concept, a bottom Check/Continue bar.

## Colors

A neutral canvas, white cards and ink, with one live colour and one attention colour.

The CSS custom properties predate this world, so their names don't match their colours. `--green`, `--green-press` and `--green-soft` hold ultramarine; `--ochre`, `--ochre-soft` and `--ochre-ink` hold the lemon family; `--paper` is the canvas and `--surface` the card white. Use the variables, not literal hex.

### Primary
- **Ink** (#111318, `--ink`): the action. Primary buttons, the nav's "New lesson" pill, the Continue button, done marks, headings and values. Hover is #2a2d36.
- **Ultramarine** (#3a4ff0, `--green`): the live mark. The current step's mark, the current note's pin, the current concept's progress bar, focus rings, chosen options, checkbox and radio accents, the slider fill when a control has no series ink. **Deep Ultramarine** (#2a3cd0, `--green-press`) is its text colour on light fills; **Ultramarine Wash** (#e9ecff, `--green-soft`) fills a chosen option, the outline's number dots and the current mark's halo.

### Secondary
- **Lemon** (#ffe46b, `--lemon`): attention at full strength. The goal chip, the "Surprise me" chip, the highlighted line in the paper-to-lesson figure, the logo dot.
- **Lemon Wash** (#fff6cc, `--ochre-soft`): the quiet attention fill. The current numbered note, a readout or slider row a note is naming, a highlighted table cell. **Lemon Ink** (#4d3b00, `--ochre-ink`) is the text colour on it; **Lemon Edge** (#b38a00, `--ochre`) is its outline where one is needed.
- **Link** (#2f45d8, `--blue`): links in running text.
- **Data inks** (model-0 to model-7): series colours on a white card, led by blue, amber, green and violet, each 3:1 or more against white. Series also differ by dash, marker shape and label.

### Neutral
- **Canvas** (#f4f5f7, `--paper`): the app background behind everything, including the lesson's notes column.
- **Surface** (#ffffff, `--surface`): cards, the model card, fields, the top bar and the action bar.
- **Body** (#343844): running text. **Mute** (#626877): metadata, captions, ticks, unread steps. **Faint** (#9ca1ad): disabled text only.
- **Fill** (#e9ebf0, `--plate-2`): default buttons, tags, empty progress segments, slider track remainder. **Canvas** doubles as the quiet fill inside a card (readout tiles, table cells).
- **Rule** (#e6e8ed) and **Strong Rule** (#cfd3dc): row dividers inside a grouped list, field borders, empty marks.
- **Feedback** (good, good-bg, bad, bad-bg): right and wrong in the action bar and reveal, always with an icon and words.

### Named Rules
**The Ink Action Rule.** The action is black. One primary button per screen; everything else is a soft-fill default, a ghost or a text action.

**The Live Rule.** Ultramarine means "this is live or current" and nothing else: never a decorative fill, never a heading colour.

**The Lemon Rule.** Lemon means "this is what we're talking about". It marks one thing at a time.

## Typography

**Display, body and label font:** Archivo (variable, 400–800), self-hosted.
**Mono:** Spline Sans Mono, for code and commands only.

**Character:** one grotesque does every job. Headlines are set heavy (800) and tight, which gives the app its confident, current voice; body copy stays at 400 for comfortable reading. The paper's own words are set in Archivo too, at a larger weight-500 size, not in an italic or a serif. The one exception is a gallery card for a lesson taught without a model: a short excerpt set bold italic on an ultramarine-soft ground under a large ultramarine quote mark, credited to its author.

### Hierarchy
- **Display** (800, clamp(44px, 5vw, 74px), 0.98, -0.045em): the home headline.
- **Headline** (800, clamp(32px, 3.6vw, 46px), 1.12, -0.032em): page h1, lesson overview titles.
- **Title** (800, clamp(26px, 2.3vw, 32px), -0.03em): the concept title at the top of the notes column.
- **Section** (800, clamp(24px, 2.4vw, 30px), -0.025em): section h2.
- **Title small** (700, 19px, 1.25): outline rows, list items, gallery titles.
- **Lead** (400, 19px, 1.5, max 60ch): page introductions.
- **Body** (400, 17px, 1.55): notes and running text, capped near 64ch.
- **Label** (600, 15px): form labels, slider labels, nav, step labels; buttons are 600 at 16px.
- **Readout** (800, 27px, -0.03em, tabular): live values in readout tiles; 21px on phones.
- **Quote** (500, 22px, 1.45): the paper's own words on a concept.
- **Pin** (700, 11.5px, tabular): numerals in note marks and pins.

### Named Rules
**The Sentence Case Rule.** Headings, buttons, tags and labels are sentence case. No uppercase, no letter-spaced labels, no eyebrow above a heading.

**The Tabular Numbers Rule.** Every number that changes uses tabular figures.

**The Mono Is Code Rule.** Spline Sans Mono appears only for commands and code, never as a "technical" costume for labels.

## Layout

The app sits on the canvas. Outside the lesson, content lives in a 1240px container with 24px side padding (safe areas respected), and reading blocks cap at 760px. The header is a sticky translucent bar across the full width, its content aligned to the container.

**Home:** one two-column grid shared by the first view, "Try it yourself" and the hall (`--home-col` minmax(300px, 400px), `--home-gap` clamp(28px, 4vw, 56px)), so the column edges line up down the page, and 80px between sections; the sticky header's content edges match the page's (24px gutters on phones too). The first view's grid areas `intro` and `ways` on the left, `film` on the right, then `try` across both). Left, top to bottom: the display headline "See how complex ideas work"; a three-line lead (18px, 1.5); the ways in. The ways in treat a concept and a source as equal doors: the label "What do you want to understand?" (label style, ink), a white search field beside the screen's one black "Find sources" button (both 52px, 17px), three concept chips below; then an "or" row, the muted word "or" (600, 15px) beside a full-width default "Bring a source" button at the same 52px height with a document icon; then the example line, a small ghost ink "Walk the example lesson" link with a play icon (a link, so Back returns home) and a muted caption "10 minutes, no account or key". Right: the launch film, embedded: a white 28px card in 16:9 showing a poster ("Don't read about it. Watch it move.") with only an ink play disc bottom-left (48px below 640px); its accessible name gives the length. Pressing it loads the film in place (1080p, or 720p at 900px and below), with native controls and sound; when it ends a near-opaque panel offers "Ask about a concept" (the one black button), "Bring a source" and Replay. Nothing loads or plays until asked. Below the first view, a "Try it yourself" block (section heading) puts the section heading and the step guide in the left column, with "Walk the whole lesson" and its muted caption pinned to the column foot above a hairline, and the live Galton regression model on its raised white card on the right. The card starts level with the heading and ends level with the foot. From 1100px the card is an instrument panel, the chart (at most 320px tall) and its note on the left, the readouts stacked and the slider (label on its own line, then the value and Play) on the right, and it stays in view (sticky) while the steps grow. On phones (900px and below) everything is one column: intro, film, ways in, then "Try it yourself" with the model above its guide; below 420px the "Find sources" button wraps under the field at full width. Below the first view: the hall, "How OpenLemma teaches a concept" (four steps beside the source-to-lesson figure), then the gallery, "Concepts to explore", as a model wall: six hand-picked lessons from different subjects (attention, early COVID-19, two slits, Mendel, ice-albedo, opinion dynamics), each tile only its live model on a 4:3 white plate, the field (600, 14px, muted) and the title up to its colon (20px); no sources, authors or counts, so a first-time visitor scans pictures, not paragraphs. A default "See all 18 lessons" button with an arrow closes it. Three columns, two at 1100px, two compact columns on phones. The Gallery page keeps the full cards (source, authors, field and concept count).

**New lesson:** a segmented control, "Ask a question" or "Bring sources". Bring sources is one ordered list of rows, each a 52px field-style row (12px corners, the field border, a green focus ring on the whole row) with a 30px plate mark (link or document icon) and a muted remove cross. A link row holds a borderless URL input; a file row shows its name (600, ellipsis) over its kind and size (13.5px, muted, tabular). Below: small "Add a link" and "Add files" buttons with plus icons, then one muted line counting the filled sources, which turns red to name any file turned away. Files can also be dropped on the pane, which shows a green outline while dragging. Up to ten sources, five of them files; the black button reads "Read the source" or "Read N sources", and while uploading "Reading <file name>…".

**Outline:** title, summary, the folded "paper in brief" card, then one grouped white card holding a row per concept (number dot, title and tags, idea, controls on the right), then the actions.

**Lesson:** a sticky white top bar (close, back, wordmark, paper citation, one progress segment per concept). Below it, the notes column on the canvas (minmax(320px, 440px), sticky) with the concept title and the step stepper, and the stage on the canvas holding the model card (max 1000px). A fixed bottom action bar (~84px) carries the hint, Show me and Continue.

Rhythm runs on 6, 10, 14, 22, 32, 40 and 80px. Responsive: at 1100px overview grids collapse to one column; at 900px the lesson stacks (notes above the model) and shows only the current step and current note; at 560px the nav tightens and readouts become a one-column list of label/value rows; at 520px the action bar's buttons go full width. Coarse pointers get 48px buttons and 30px slider knobs.

## Elevation & Depth

Depth is soft and ambient: cards lift off the canvas with a two-layer shadow, and floating layers lift further. There are no hairline frames around cards and no hard offset shadows.

### Shadow Vocabulary
- **Lift** (`--lift`: `0 1px 2px rgba(17,19,24,.05), 0 6px 20px rgba(17,19,24,.06)`): ordinary cards, grouped lists, the current step, notes.
- **High lift** (`--lift-hi`: `0 2px 4px rgba(17,19,24,.05), 0 18px 48px rgba(17,19,24,.10)`): the model card, the home model card, a hovered gallery card, a floating error.
- **Action** (`0 1px 2px rgba(17,19,24,.2), 0 6px 16px rgba(17,19,24,.14)`): the primary button at rest; it rises 1px on hover and drops its shadow when pressed.
- **Knob** (`0 0 0 3px <series ink>, 0 3px 10px rgba(17,19,24,.22)`): the slider knob.
- **Bar** (`0 -8px 30px rgba(17,19,24,.06)`): the action bar.
- **Frost**: the header, the lesson top bar and the action bar are translucent with a 14px backdrop blur, because content scrolls under them.

## Shapes

Soft, friendly corners: 12px on buttons and fields, 16px on readout tiles, options, slider rows and the current step, 22px on cards and grouped lists, 26px on the model card (28px on the home model card). Pills for tags, chips, the nav's "New lesson" and the Play/Trail buttons. Marks, pins and number dots are circles; the logo is a 7px-rounded black square with a lemon dot. Progress segments are 6px pills.

## Components

### Buttons
- **Primary:** ink fill, white text, the action shadow; hover lightens to #2a2d36 and rises 1px; press darkens and drops 1px.
- **Default:** fill (#e9ebf0), ink text, no border; hover darkens the fill.
- **Ghost:** transparent; hover fills. In an action row, ghosts after the first button read as text actions.
- **Danger:** transparent with bad-red text; hover fills with bad-bg.
- **Focus:** 2px ultramarine outline, 3px offset.

### Navigation
A sticky translucent bar: the wordmark left, pill-hover links, and "New lesson" as a black pill at the end. The links depend on whether the visitor is signed in, the same on your own computer as hosted. Signed out: Gallery, then "Sign in" as an outlined pill (1.5px `--rule-strong` ring, ink on hover) beside the black pill, since Library would only ask to sign in. Signed in: Gallery, Library, then the avatar and name, which open the account page. There is no separate Settings page: the AI provider is a section of the account page (profile facts, then "AI provider", then Sign out below a hairline), and `#/settings` opens that section. The sign-in page shows Google's own pre-approved "Sign in with Google" button (light theme, pill: white, 1px #747775 ring, the gradient G, Google Sans), used unaltered from Google's sign-in asset bundle as `static/google-sign-in-{1..4}x.png` and scaled evenly to 216 × 48, as Google's branding guidelines require (no restyled colours, type, logo or spacing). Only a focus ring and a hover shadow sit outside it. Any other provider uses the site's own button. Signing in returns to the page the visitor was on, or to what they were about to do.

### Wordmark
"OpenLemma" in Archivo at 22px, letter-spacing -0.035em, as one word in two weights: "Open" at 500, "Lemma" at 800, both ink. It sits 10px after the logo, the open dial: an ink ring (3.6 of 28 units, round caps) broken at the upper right, a lemon knob with an ink outline sitting in the gap, and an ink centre dot. It reads as the O of Open and as a dial you can turn. 28px in the top bar, 22px in the lesson top bar. The source is `lemma/static/logo.svg`; `favicon.svg` sets it on a white 8px-cornered tile, and `icon-180.png` is the home-screen icon. The mark is drawn in ink and lemon only, never ultramarine (the Live Rule). The weight change is the only thing that separates the two halves; no colour, space or capital tricks.

### Cards and grouped lists
White, 22px corners, the lift shadow, no border. Lists (outline, results, library, build steps, providers) are one grouped card with 1px rule dividers between rows, never a card per row.

### Step guide (home and lesson)
A stepper: inactive steps are plain rows with a circular number mark; done marks fill ink; the current step becomes a white card with an ultramarine mark and its body (notes, goal chip, count).

### Numbered notes and pins (signature)
In the current step, the narrated notes are numbered lines; the line being read gets a lemon-wash fill and an ultramarine mark, read lines get an ink mark. The note's number pins onto each control, readout or drawn mark it names: ultramarine while read, ink once said.

### Model card
The live model on a white card with high lift: a sentence-case title and "Teaching model" tag, the chart, readout tiles, then sliders.

### Readouts
Soft canvas tiles (16px corners) with a muted sentence-case label and an 800-weight tabular value. The readout a note names turns lemon wash with a lemon inner ring. On phones they become one-column label/value rows.

### Sliders
A 10px rounded track filled in the control's series ink over the fill grey, with a 28px white knob ringed in the series ink. A row a note names gets a lemon-wash fill. The Play button is a small pill.

### Concept progress
In the lesson top bar, each concept shows its name, reading time and a 6px progress pill: ultramarine for the current concept, a lighter ultramarine for done, fill grey for pending.

### Options and checks
Large tappable white cards (16px) with an inset rule; chosen options turn ultramarine wash with a 2px ultramarine inset; the correct answer on reveal turns good-green.

### Goal chip
The goal sentence on a lemon fill, 12px corners, 700 weight.

### Action bar
A frosted white sheet fixed to the bottom with the bar shadow; it tints good-green or bad-red with an icon and words when a check is answered. Buttons are 52px with 14px corners.

### Tags and chips
Tags are 26px pills on the fill grey, 600 at 13px, sentence case. Topic chips are white pills with an inset rule; "Surprise me" is lemon.

## Do's and Don'ts

### Do:
- **Do** put each live model on its own white model card on the canvas.
- **Do** use black for the one primary action on a screen.
- **Do** keep ultramarine for what is live or current, and lemon for what is being talked about, one thing at a time.
- **Do** group list rows inside one white card with rule dividers.
- **Do** keep controls big and touchable: thick tracks, round knobs, 46–52px buttons.
- **Do** use sentence case and tabular figures everywhere.
- **Do** order data inks blue, amber, green, violet, and also vary dash, shape and label.
- **Do** use the CSS variables; remember the legacy names (`--green` is ultramarine, `--ochre-*` is lemon).
- **Do** offer a concept and a source as equal ways in where a lesson starts; the concept field carries the one black button and the source door is a default button at the same height.

### Don't:
- **Don't** make a screen read like a blog post or an essay page: long ruled prose, a margin column of citations, a hairline-only layout.
- **Don't** bring back cream, walnut, manila, or uppercase mono labels.
- **Don't** frame cards with borders or use hard offset shadows; depth is the soft lift.
- **Don't** put a coloured border-left on cards, notes or callouts.
- **Don't** use ultramarine or lemon as decoration, or add a second accent colour.
- **Don't** put an eyebrow or kicker above a heading.
- **Don't** set labels or "technical" text in mono; mono is for code.
- **Don't** let colour alone tell series or feedback apart.
