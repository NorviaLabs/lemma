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
  button-small:
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "38px"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.body}"
    rounded: "{rounded.md}"
  button-danger-hover:
    backgroundColor: "{colors.bad-bg}"
    textColor: "{colors.bad}"
  button-confirm-danger:
    backgroundColor: "{colors.bad}"
    textColor: "{colors.surface}"
    rounded: "{rounded.md}"
  button-icon:
    backgroundColor: "transparent"
    textColor: "{colors.body}"
    rounded: "{rounded.md}"
    size: "40px"
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
**The Ink Action Rule.** The action is black. One primary button per screen; everything else is a soft-fill default or a quiet ghost (see Buttons and links).

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

**Home:** one two-column grid shared by the first view, "Try it yourself" and the hall (`--home-col` minmax(300px, 400px), `--home-gap` clamp(28px, 4vw, 56px)), so the column edges line up down the page, and 80px between sections; the sticky header's content edges match the page's (24px gutters on phones too). The first view's grid areas: `intro` and `ways` on the left, `film` on the right, then `recent` and `try` across both. Home section headings ("Your recent lessons", "Try it yourself", the hall, the gallery) are a step larger than the Section size, clamp(28px, 2.8vw, 38px), because home is a Persuade page. Left, top to bottom: the display headline "See how complex ideas work"; a three-line lead (18px, 1.5); the ways in. The ways in treat a concept and a source as equal doors: the label "What do you want to understand?" (label style, ink), a white search field beside the screen's one black "Find sources" button (both 52px, 17px), three concept chips below; then an "or" row, the muted word "or" (600, 15px) beside a full-width default "Bring a source" button at the same 52px height with a document icon; then the example line, a small ghost ink "Try the example lesson" link with a play icon (a link, so Back returns home) and a muted caption "About 10 minutes. No account or key needed.". Right: the film, embedded: a white 28px card in 16:9 showing a poster ("Don't read about it. Watch it move.") with only an ink play disc bottom-left (48px below 640px); its accessible name gives the length. Pressing it loads the film in place (1080p, or 720p at 900px and below), with native controls and sound; when it ends a near-opaque panel offers "Ask about a concept" (the one black button), "Bring a source" and Replay. Nothing loads or plays until asked. Signed in with saved lessons (the same on your own computer as hosted), a "Your recent lessons" row follows the first view on the same two columns: the heading and a small ghost "All in your library" link with an arrow on the left, and on the right the three newest lessons as the library's own grouped white card of rows (title, source, subject, concept count and "Saved …"; the whole row opens the lesson), without the library's row actions. Signed out, or with nothing saved, there is no row and no empty state. Then a "Try it yourself" block (section heading) puts the section heading and the step guide in the left column, with a second "Try the example lesson" (no caption: the hero already says how long it takes) pinned to the column foot above a hairline, and the live Galton regression model on its raised white card on the right. The card starts level with the heading and ends level with the foot. From 700px the card is an instrument panel, the chart (at most 320px tall) and its note on the left, the readouts stacked and the slider (label on its own line, then the value and Play) on the right; from 1100px it sits beside the steps and stays in view (sticky) while they grow. Below 1100px "Try it yourself" is one column, heading, model, then the guide and its foot (at most 640px wide), so the steps never stand beside a hole. The readouts are ordered so the two numbers the Notice step compares, the parents' and the child's lead over average, sit side by side ahead of the expected height, and at Notice both turn lemon wash and carry pin 2. Unopened steps stay muted and take the fill grey on hover, so they read as openable. On phones (900px and below) the first view is one column too: intro, film, ways in, then any recent lessons and "Try it yourself" with the model above its guide; below 420px the "Find sources" button wraps under the field at full width. Below the first view: the hall, "How OpenLemma teaches a concept" (four steps beside the source-to-lesson figure, whose white card starts level with the heading and ends level with the column's foot; Replay keeps its place, invisible, while the figure plays, so the card never changes height), then the gallery, "Lessons to explore", as a model wall: six hand-picked lessons from different subjects (attention, early COVID-19, two slits, Mendel, ice-albedo, opinion dynamics), each tile only its live model on a 4:3 white plate, the field (600, 14px, muted) and the title up to its colon (20px); no sources, authors or counts, so a first-time visitor scans pictures, not paragraphs. A default "See all 18 lessons" button with an arrow closes it. Three columns, two at 1100px, two compact columns on phones. While the list loads, both the wall and the Gallery page hold empty tiles of the final shape (white plates, pale text bars), so nothing jumps when the lessons land; if it fails, one white card says so with a "Try again" button.

**Gallery page:** an Experience page where every lesson's own live model leads. The head is two columns: "Gallery" and the lead on the left, and on the right, aligned to the lead's foot, "Find a lesson": a 52px white search field (lifted, no border at rest, a search icon inside) and a muted tabular count beneath ("18 lessons", or "3 of 18 lessons" while filtering, announced politely). Typing filters the tiles at once on every word, across the title, field, source title, authors, year and concept titles, ignoring case and accents; Escape clears it. The query lives in the hash (`#/gallery?q=…`, replaced in place, not a new history entry), so opening a lesson and pressing Back returns to the same filtered list, scrolled to and focused on the tile just opened. No match shows a white card, "No lesson matches “…”." with a ghost "Clear the search". There is no field filter: each of the 18 lessons has its own field, so field chips would sort nothing. Each tile is the model on a 4:3 white plate (a table model too tall for it is shrunk to fit whole; a lesson without a model shows its quote poster), then the full title (Title small, 700), the source title (15px, body, up to two lines) over its short authors and year (14px, muted, one line), and at the foot the field and the concept count (600, 14px, muted, a faint middle dot between). The whole tile is the link to the lesson, with the ultramarine focus ring around it. Three columns, two at 1100px, one below 640px; the head stacks at 900px.

**Library:** an Operate page for the signed-in account (`#/library`), the same on your own computer as hosted. The head is "Library" and a one-line lead (18px). Below, two columns from 1000px: "Saved lessons" on the left and "In progress" (only while any build hasn't finished) in a 300–380px column on the right; below 1000px they stack with In progress first, and with no builds the lessons take the full width. Each section heading (22–26px) carries a 26px fill-grey count pill. Both lists are one grouped white card (22px corners, `--lift`, 6px inset) of 16px-cornered rows with inset hairlines between them; a row fills with the canvas tint on hover, and the whole row is the link (the title's stretched link; the ultramarine ring goes round the row on keyboard focus). A lesson row is the title (700, 18px, ink), the source title (15px, body, one line, two on phones), then the subject, the concept count and "Saved today / yesterday / 12 Oct" (600, 14px, muted, faint middle dots), with quiet ghost text actions on the right: Download (down-arrow icon; "Preparing…" while the file is made, named after the lesson's title and cut at a word), Edit, and Delete, which turns red only on hover. From seven lessons, a 52px lifted search field (search icon, "Title, source or subject") replaces the count pill, with a muted tabular "3 of 14 lessons" under it; it filters on every word across title, source and subject, Escape clears it, the query lives in the hash (`#/library?q=…`, replaced in place), and Back from a lesson returns to the same filtered list focused on the row just opened. No match hides the list and shows a white card, "No saved lesson matches “…”." with a ghost "Clear the search". A build row leads with a 30px state mark, then the title (17px), the state in words and "Started today at 14:05": Building now (an ultramarine spinning ring, Deep Ultramarine words; View progress, Cancel), Outline ready to review (an ink disc with a document icon; Review outline, Delete), Stopped with an error or Interrupted when the server stopped (bad-wash disc with a red cross, red words; Retry, Delete), Cancelled (a fill-grey dash; Retry, Delete). Retry without a connected AI provider goes through the connect step first. Nothing is deleted or cancelled without asking in the row: the row turns bad-wash, its actions give way to the question (600, 15px; "This can't be undone." for a lesson, that retrying starts again from reading the sources for a cancel) beside a solid red action and a ghost "Keep it" / "Keep building", which takes focus; Escape puts the row back. When the server refuses (a build still running), the row is redrawn as it now is and the reason sits in it, on a bad-wash strip with a red cross, never a browser dialog. While a build runs, the page checks every few seconds and redraws in place, keeping focus, but never while a question is open. A first visit shows one raised white card (28px corners, `--lift-hi`, at most 640px): "No saved lessons yet", what happens when you make one, then the black "Make a lesson" and a ghost "Try the example lesson"; with builds but no lessons yet, a hairline-ringed note says a lesson appears when its build finishes. If the lists can't load, a white card says so with "Try again".

**New lesson:** a segmented control, "Ask about a concept" or "Bring sources". Bring sources is one ordered list of rows, each a 52px field-style row (12px corners, the field border, an ultramarine field focus on the whole row) with a 30px plate mark (link or document icon) and a muted remove cross. A link row holds a borderless URL input; a file row shows its name (600, ellipsis) over its kind and size (13.5px, muted, tabular). Below: small "Add a link" and "Add files" buttons with plus icons, then one muted line counting the filled sources, which turns red to name any file turned away. Files can also be dropped on the pane, which shows a green outline while dragging. Up to 10 sources, 5 of them files; the black button reads "Read the source" or "Read N sources", and while uploading "Reading <file name>…". Under either way in, "Your level" is a second segmented control, Beginner · Intermediate · Advanced (a radio group: the chosen segment is the lifted white tab with `aria-checked`), set before Find sources because it shapes what is found and how the lesson explains. It starts on the account's last level, Beginner for a new account. Left untouched, a search uses the level the account last chose for the question's field; once the learner sets it, their choice wins and is remembered for that field.

**Field line:** under the results heading, one line: "Searching as **Psychology** · Beginner", the field in ink 600 (two fields read "Physics & astronomy + Psychology"), then a small ghost "Change" button (`aria-expanded`). It opens an inline panel with the card border: "Field" over the likely fields as chips (a radio group; the chosen chip is filled ink with white text), an "Another field…" select of every field, "Your level" as the segmented control, then a small black "Search again" button, disabled until something changed, with a muted note that a new search counts toward today's searches. When a subject the learner needs has no readable source, one muted small line under the intro names it: "Not covered by these sources: X. The lesson will assume you know it."

**Outline:** title, summary, the folded "The idea in brief" card, then one grouped white card holding a row per concept (number dot, title and tags, idea, controls on the right), then the actions. The tags are plain words, never schema values: the role ("Background", "Core idea", "Main result"), how it is shown ("Graph", "Bar chart", "Table", "Simulation", "Network", "Cause and effect", "Sampling", "Diagram", "Reading only"), "Has a quiz", "Uses concept 2's model" and "Comes after 1 and 3". The actions are "Build N concepts", "Cancel this lesson", "Return later" and "Back to home". For a lesson asked as a question, a muted "Your question: …" line and a bordered "What this lesson builds on" card come before the concepts: up to three short lists, **Covered** ("Cortisol: concept 2"), **Assumed** ("The lesson takes these as known.") and **Later** ("Not in this lesson."), which follow the learner's edits; a concept marked known moves its subject to Assumed. The lesson intro then says "This lesson assumes you know …".

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

### Buttons and links
One system, each role with one job. The CSS lives in one block near the top of `styles.css`; tokens `--ink-hover`, `--fill-hover`, `--action`, `--action-hi`, `--ring` and `--ring-gap` carry the shared values.

**Roles**
- **Primary** (`.primary`): the one main action on a view. Ink fill, white text, the action shadow; hover lightens to #2a2d36 and rises 1px, press goes black and drops its shadow.
- **Default** (no class, or `.btn` on a link): the fill (#e9ebf0), ink text, no border; hover darkens the fill to #dfe2e9. Secondary actions beside a primary ("Bring a source", "Review outline", "Retry build", "Try again").
- **Ghost** (`.ghost`): quiet, transparent, ink text; hover fills with the fill grey. Every ghost looks the same wherever it sits (action rows, the action bar, library rows). A ghost that starts a left-aligned row (in `.actions`, the home's example line and try foot, Replay under the hall) pulls left by its padding so its text lines up with the copy above, and its hover fill reaches outward.
- **Danger** (`.danger`): destructive and quiet until hovered: body text at rest, red text on the bad wash on hover (library Delete, outline Remove, the remove cross on a source row). The confirm inside an in-row question is solid red with white text (`.lib-yes`); its partner is a ghost.
- **Icon-only** (`.icon-btn`): a 40px transparent square in body colour, hover fill; it always has an `aria-label` (lesson close, back, sound, remove source).
- **Chips** (`.chip`): 38px white pills with a 1.5px inset rule that firms on hover; they fill the field with a topic. "Surprise me" is lemon.
- **Segmented** (`.segmented` / `.seg`): a fill track with 10px segments; the chosen one is a lifted white tab (`aria-selected`).
- **Nav pills** (`.site-nav a`): 600 15px body text on a pill that fills grey on hover; the current page (`aria-current="page"`, set by the router) keeps that fill in ink text. "New lesson" is the ink pill; signed out, "Sign in" is the outlined pill.
- **Tool pills** (`.ctl .play`, `.trail-btn`): 32px default pills inside a model card; Trails pressed turns ink.
- **Bare buttons**: rows, lines and posters that are buttons for keyboard and touch but carry no chrome (the film poster, narration lines, the lesson contents list, the brief's steps, the home step heads). They keep their own looks on hover and do not move when pressed.
- Google's "Sign in with Google" is Google's own image, unaltered; only the shared ring and a hover shadow sit around it.

**Sizes.** 46px default; 52px large for the home's ways in and the action bar (17px text); 38px small (`.small`, 15px, 14px padding) for row actions and inline adds; 32px tool pills; 40px icon squares. Buttons are 600 at 16px with 12px corners; chips, nav and tool pills are full pills. On coarse pointers buttons are 48px and small buttons, chips, segments, tool pills and icon squares 44px.

**States.** Hover as above (none on `hover: none` devices). Pressed moves 1px down. Disabled is the fill with faint text (ghost, icon and danger stay transparent) and uses the real `disabled` attribute. A button waiting on the server is disabled with `aria-busy="true"` (the `busy()` helper in `app.js`) and keeps its own colours with a progress cursor, so "Searching…", "Reading <file>…", "Preparing…", "Checking the key…" read as working, not unavailable; a busy primary stays ink at 78% opacity.

**Focus.** One ring everywhere: a 2px ultramarine outline 3px outside the control's own shape (pills stay pills). Rows inside a grouped white list (library rows, FAQ questions, the account's library row, provider choices) draw the same ring 2px inside the row; a whole-tile link (gallery) draws it round the tile. Fields take focus as an ultramarine border with a soft ultramarine wash instead; sliders, checkboxes and radios take the ring, and an option card or provider row rings the card rather than its radio.

**Links.** A body link is Link blue (#2f45d8) with a 1px underline at 45% and a 3px offset, the underline firming to full colour on hover; this holds on the Privacy, Terms and FAQ pages too. A link that opens a new tab (`ext()` in `app.js` and `player.js`) carries the 13px out arrow and a visually hidden "(opens in a new tab)". Quiet links (the footer, the documents' meta line, the sign-in fine print) are body-coloured and turn ink on hover: footer links are underlined only on hover, meta and fine-print links keep a rule-strong underline; the footer marks the current page in ink at 600. Stretched row links (library, gallery, account) carry no underline; the row is the affordance.

### Navigation
A sticky translucent bar: the wordmark left, pill-hover links, and "New lesson" as a black pill at the end. The links depend on whether the visitor is signed in, the same on your own computer as hosted. Signed out: Gallery, then "Sign in" as an outlined pill (1.5px `--rule-strong` ring, ink on hover; filled grey on the sign-in page itself, as the current page) beside the black pill, since Library would only ask to sign in. Signed in: Gallery, Library, then the avatar and name, which open the account page. At 600px and below the bar is always two rows: the wordmark, then a full-width row of links (14px, 8px 9px pills) whose first link's text lines up with the wordmark and whose "New lesson" pill ends on the right gutter, 8px between the rows; no link is hidden. There is no separate Settings page: the AI provider is a section of the account page, and `#/settings` scrolls to it and focuses its heading. The account page is a centred column (at most 640px) of two raised white cards (28px corners, 22px on phones): the profile card (`--lift`) with the 64px avatar (52px on phones), the name (28–34px) and the email in mute, then a hairline-ringed list of three rows: Library (the saved-lesson count, or "No saved lessons yet", with a chevron; the whole row opens the library), Signed in with, and Member since. Then the AI provider card (`--lift-hi`, the page's main task): the "AI provider" heading, a status plate read from the server's status (green with a tick, "Connected. Lessons are built with <provider> using <model>."; lemon wash with a plus, "Not connected yet."; or bad-red with a cross, "Needs attention.", when the saved key fails its model check), the note on where a source's text goes, then the provider form, its choices framed by a hairline ring inside the card rather than a second card, the chosen one with a 2px ultramarine ring. Below the cards, outside them, a muted "Signed in as <email>" and a quiet ghost "Sign out" with a leave icon, side by side (centred and stacked on phones). The sign-in page is one raised white card (28px corners, `--lift-hi`, at most 460px) centred on the page: the 40px mark, "Sign in to OpenLemma", then what happens after Google, said before the button (the question the visitor asked, set as a quoted plate, or the page they'll return to), any sign-in error, the button, a hairline, three checked points (searching is free; every lesson is saved to your library; lessons use your own AI model and a key stays in this browser) with green-tinted ticks, and a 13.5px note on what OpenLemma keeps with a Privacy link. Below the card, centred: "Not ready yet? Try the example lesson, with no account or key." It shows Google's own pre-approved "Sign in with Google" button (light theme, pill: white, 1px #747775 ring, the gradient G, Google Sans), used unaltered from Google's sign-in asset bundle as `static/google-sign-in-{1..4}x.png` and scaled evenly to 216 × 48, as Google's branding guidelines require (no restyled colours, type, logo or spacing). Only a focus ring and a hover shadow sit outside it. Any other provider uses the site's own button. Signing in returns to the page the visitor was on, or to what they were about to do.

### FAQ page
`/faq` (`static/faq.html`) is a Read page in the Privacy and Terms document style (`main.doc`, 808px): the title "Questions and answers", a 19px lead, a muted line with the contact address and links to Privacy and Terms, then the white "In short" card with four points. Below, four sections (Getting started; Your key and your data; Sources and lessons; Limits and your account), each a section heading over one white grouped list (22px corners, `--lift`, hairlines between rows). Every question is a native `<details>`: the summary is 600 17px ink with a 30px fill disc and a drawn chevron on the right, which turns and goes ultramarine-soft when open; hover tints the row plate, and focus is the ultramarine ring drawn inside the row. Answers are short plain paragraphs and lists at body size, every fact taken from Privacy, Terms, README and the app's own copy. Each `<details>` has an id, so `faq#key-safe` links to one question: `static/faq.js` (the page's only script, allowed by the static pages' `script-src 'self'`) opens it and scrolls it below the sticky header, and the summary washes lemon-soft and fades over 2.4s (no wash with reduced motion). Without JavaScript every answer still opens by hand.

### Footer

Below every page except a lesson, under a hairline (`--rule`), on the page grid (1240px, 24px gutters), 40px above it and 48px of room below. Left: the wordmark at 20px with its 24px mark, the line "See how complex ideas work." (600, 15px, ink), and the AI-errors note (14px, muted, at most 48ch). Right: two short link groups, "Learn" (New lesson, Gallery, Example lesson) and "OpenLemma" (FAQ, Send feedback, Privacy, Terms, contact@openlemma.org; on the static pages Send feedback links `./#/feedback?from=<page>`), under 13px muted labels; links are quiet links (body-coloured 15px text that turns ink and underlines on hover; the current page in ink at 600). At 720px and below it is one column, the groups side by side under the brand. It is static markup, the same on your own computer as hosted, and links nothing that isn't public (no GitHub while the repository is private).

### Feedback
Feedback goes to the people who run OpenLemma, from signed-in accounts only, the same on your own computer as hosted. It is always asked for in place, never in a modal, and every entry point uses one form (`feedbackForm()` in `app.js`): a rating as a segmented pair, "Helpful" and "Not helpful" with drawn thumb icons, that can be left unset (`aria-pressed`; pressing the chosen one again clears it; the chosen tab is the lifted white segment with its thumb in good-green or bad-red); an optional message (textarea, at most 2,000 characters, with a muted tabular "1,850 / 2,000" that appears only from 1,700 and turns ink at the limit); the reply line before sending, "We'll reply from contact@openlemma.org to **email** if you ask something." (14.5px, muted, the address in body 600); any error in a bad-wash box inside the form; then Send, busy ("Sending…") while it waits. Validation mirrors the server: a rating or a message. Once sent, the form gives way to one line with a green tick disc, "Thanks. Sent to the people who run OpenLemma. If you asked something, we'll reply from contact@openlemma.org to <the address the server returned>.", which takes focus and fades in over 320ms (instant with reduced motion).
- **The page** (`#/feedback`, from the footer and the FAQ's "How do I report a problem or contact you?"): one raised white card centred like sign-in (28px corners, `--lift-hi`, at most 560px; 22px corners on phones), "Send feedback", a 17px lead, the question "Is OpenLemma helpful so far?" (label style) over the rating, the message (six rows), the reply line and the screen's one black Send. The thank-you sits on a pale good wash tile. It records where it was opened from (`?from=`, the previous route without its query, or the static page's name). Signed out, it goes to sign in ("Sign in to open the feedback form. You'll go straight back to it.") and the held route brings the person back to the form.
- **The end of a lesson**: a quiet white card (22px corners, `--lift`) after the finish screen's actions, so it never stands between the learner and finishing: "How was this lesson?" (700, 19px) with the rating on the right (stacked and full width on phones). Choosing a rating opens "Anything to add? (optional)", the reply line and a default (fill) Send, since the screen already has its black button. Sent, the card becomes the thank-you tile. The app hands the player a `feedback` hook only when someone is signed in; the player keeps the element across redraws and sends nothing itself, so a downloaded lesson (mounted with no hooks) has no prompt and no network request.
- **Report this**: a small ghost "Report this" with a flag icon, under an error that carries an error id ("(error 1a2b3c4d)" from a build, or "with error id 1a2b3c4d." from the server's 500 answer) and under a build that stopped with an error (the build page and the library's build row, which reports the build's id). Ordinary refusals and input errors have none. It opens the form in place without a rating: "What happened?", a muted line saying the error's or build's id is sent with the message, the reply line, a default "Send report" and a ghost Cancel; Escape or Cancel closes it and returns focus to "Report this". Inside an error box the form sits on the error's own wash (no inner card; Send is white, ghost hovers tint red, secondary text is body colour). On a library build row it opens below the row's text on a canvas plate (16px corners), the row's actions hidden while it is open, and the library's polling never redraws a row that is reporting.
- **The inbox** (`#/feedback/inbox`, admins only; the server answers 404 to everyone else, which shows a plain white "Not found" card with a default "Go to the home page"). An Operate page in the library's language: "Feedback" with a New / Done / All segmented filter on the right (in the hash as `?status=`, replaced in place) over a muted tabular count, then one grouped white card of rows, newest first. A row is a rating pill (good-wash "Helpful" or bad-wash "Not helpful" with its thumb; none when unrated), the kind tag (General, Lesson, Error, Build) and, under All, a "Done" tag; the message (17px ink, line breaks kept, "No message." muted when empty); the context (14.5px, muted labels: Lesson <title>, Error / Build / Page in mono); then the sender's name, email and time as library meta. Actions on the right (under the text on phones): Reply (a `mailto:` with the subject "Your OpenLemma feedback"), Mark done / Mark new, and Delete, which asks inside the row as the library does. Rows are not links, so they don't tint on hover. Admins' account page adds a last row to its facts list, "Feedback · N new" with a chevron, linking to the inbox (from `status.feedback_new`, present only for admins).

### Wordmark
"OpenLemma" in Archivo at 22px, letter-spacing -0.035em, as one word in two weights: "Open" at 500, "Lemma" at 800, both ink. It sits 10px after the logo, the open dial: an ink ring (3.6 of 28 units, round caps) broken at the upper right, a lemon knob with an ink outline sitting in the gap, and an ink centre dot. It reads as the O of Open and as a dial you can turn. 28px in the top bar, 22px in the lesson top bar. The source is `lemma/static/logo.svg`; `favicon.svg` sets it on a white 8px-cornered tile, and `icon-180.png` is the home-screen icon. The mark is drawn in ink and lemon only, never ultramarine (the Live Rule). The weight change is the only thing that separates the two halves; no colour, space or capital tricks.

### Cards and grouped lists
White, 22px corners, the lift shadow, no border. Lists (outline, results, library, build steps, providers) are one grouped card with 1px rule dividers between rows, never a card per row.

### Step guide (home and lesson)
A stepper: inactive steps are plain rows with a circular number mark; done marks fill ink; the current step becomes a white card with an ultramarine mark and its body (notes, goal chip, count).

### Numbered notes and pins (signature)
In the current step, the narrated notes are numbered lines; the line being read gets a lemon-wash fill and an ultramarine mark, read lines get an ink mark. The note's number pins onto each control, readout or drawn mark it names: ultramarine while read, ink once said.

### Model card
The live model on a white card with high lift: a sentence-case title and "Teaching model" tag, the chart, readout tiles, then sliders. Labels on a chart never sit on each other: a point keeps its label beside it (moving to its other side or below it if it must), and a marker's or reference line's label makes way, a row lower, across its line, or to the plot's other end.

### Readouts
Soft canvas tiles (16px corners) with a muted sentence-case label and an 800-weight tabular value. The readout a note names turns lemon wash with a lemon inner ring; once the note is read it goes back to its canvas tile, keeping only its ink pin. On phones they become one-column label/value rows.

### Sliders
A 10px rounded track filled in the control's series ink over the fill grey, with a 28px white knob ringed in the series ink. A row a note names gets a lemon-wash fill. The Play button is a small pill.

### Concept progress
In the lesson top bar, each concept shows its name, reading time and a 6px progress pill: ultramarine for the current concept, a lighter ultramarine for done, fill grey for pending.

### Options and checks
Large tappable white cards (16px) with an inset rule; chosen options turn ultramarine wash with a 2px ultramarine inset; the correct answer on reveal turns good-green.

### Goal chip
The goal sentence on a lemon fill, 12px corners, 700 weight.

### Action bar
A frosted white sheet fixed to the bottom with the bar shadow; it tints good-green or bad-red with an icon and words when a check is answered. Its buttons are the large size (52px, 12px corners); see Buttons and links.

### Tags and chips
Tags are 26px pills on the fill grey, 600 at 13px, sentence case. Topic chips are white pills with an inset rule; "Surprise me" is lemon.

## Words we use

One name for each thing, everywhere: the app, the static pages, error messages and these docs.

| Concept | Use | Don't use |
|---|---|---|
| The company whose model writes lessons, and its key | **AI provider**, **key** (or "AI provider key") | "AI model you connect", "your own AI model" |
| The model chosen within a provider | **model** | "AI model" as a synonym for the provider |
| The interactive figure in a concept | **model** ("Teaching model" labels it) | "deck", "exhibit", "the blue deck" |
| Where the provider is set | **account page** | "Settings" |
| What you bring or OpenLemma finds | **source** (papers, articles and chapters are kinds of source) | "paper" as the generic word, "resource" |
| The finished thing | **lesson** | "combined lesson" |
| Making a lesson | **build** ("Building", "Cancel build", "Retry build") | "job", "repairs" |
| Unfinished builds in the Library | **In progress** | "Builds" as a heading |
| Starting a lesson | **New lesson** | "Make a lesson", "Start a lesson" |
| The proposed list of concepts | **outline** | "path of concepts" |
| The short intro pages | **The idea in brief** | "the source in brief", "the paper in brief" |
| A lesson's units | **concept** | "idea" as a unit label (fine in prose) |
| The two ways in | **Ask about a concept** · **Bring sources** | "Ask a question", "Search a topic" |
| How much the learner knows | **level**: **Beginner** · **Intermediate** · **Advanced** | "audience", "who is it for", "expert" |
| The discipline a question is read in | **field** ("Searching as Psychology") | "category" or "subject" in learner copy |
| The bundled lesson | **the example lesson**, with the verb **Try** | "Walk the example lesson" |
| Saved lessons | **Library** | "My library" |
| Signing in | **Sign in / Sign out** | "log in" |
| The quality gate | **checks** | "Jev", "grounding", "rules" in learner copy |
| Feedback on an answer | **That's it** / **Not yet**, said and announced alike | "Correct", "Not quite", "Reconsider this" |

Numbers for limits are numerals ("up to 10 links and files"). Spelling is British. Each screen names itself in the tab: "Library · OpenLemma", "<lesson title> · OpenLemma"; the home page is just "OpenLemma".

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
