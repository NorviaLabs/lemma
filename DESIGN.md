---
name: Lemma
description: A research paper turned into field-guide plates, each a live model with numbered notes that point at it.
colors:
  paper: "#ffffff"
  ink: "#1d2321"
  body: "#2c3430"
  mute: "#545d58"
  faint: "#8a938e"
  rule: "#dfe3de"
  rule-strong: "#c2c9c3"
  plate: "#eef1ec"
  plate-2: "#e1e6e0"
  green: "#2f7a52"
  green-press: "#24623f"
  green-soft: "#e4f0e8"
  ochre: "#c98a12"
  ochre-ink: "#85590a"
  ochre-soft: "#fbf1dc"
  blue: "#3567b0"
  violet: "#7a4c98"
  good: "#23704a"
  good-bg: "#e4f0e8"
  bad: "#b3261e"
  bad-bg: "#fbecea"
  model-0: "#3567b0"
  model-1: "#a8700c"
  model-2: "#00845f"
  model-3: "#7a4c98"
  model-4: "#a8508a"
  model-5: "#2a8fcc"
  model-6: "#7d7000"
  model-7: "#6b7280"
typography:
  display:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "clamp(36px, 3.6vw, 52px)"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "clamp(32px, 3.6vw, 46px)"
    fontWeight: 700
    lineHeight: 1.12
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "clamp(26px, 2.3vw, 32px)"
    fontWeight: 700
    lineHeight: 1.12
    letterSpacing: "-0.02em"
  title-sm:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  lead:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 400
    lineHeight: 1.5
  body:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.55
    fontFeature: "\"kern\", \"liga\""
  label:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.3
  readout:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "25px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.01em"
    fontFeature: "\"tnum\""
  pin:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "11.5px"
    fontWeight: 700
    lineHeight: 1
    fontFeature: "\"tnum\""
  words:
    fontFamily: "Literata, Georgia, Times New Roman, serif"
    fontSize: "23px"
    fontWeight: 400
    lineHeight: 1.45
  words-small:
    fontFamily: "Literata, Georgia, Times New Roman, serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.35
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  hairline: "2px"
  sm: "4px"
  r: "6px"
  r-lg: "10px"
  pill: "9999px"
  pin: "50%"
spacing:
  xs: "6px"
  sm: "10px"
  md: "14px"
  lg: "22px"
  xl: "32px"
  section: "40px"
  column-gap: "56px"
  block: "80px"
components:
  button-primary:
    backgroundColor: "{colors.green}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.r}"
    padding: "0 20px"
    height: "46px"
  button-primary-hover:
    backgroundColor: "{colors.green-press}"
    textColor: "{colors.paper}"
  button-primary-disabled:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.faint}"
  button-default:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.r}"
    padding: "0 20px"
    height: "46px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.r}"
    padding: "0 20px"
    height: "46px"
  button-ghost-hover:
    backgroundColor: "{colors.plate}"
  button-bar:
    backgroundColor: "{colors.green}"
    textColor: "{colors.paper}"
    rounded: "{rounded.r}"
    padding: "0 26px"
    height: "50px"
  input-text:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.r}"
    padding: "10px 13px"
    height: "46px"
  option-chosen:
    backgroundColor: "{colors.green-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.r-lg}"
    padding: "14px 18px"
    height: "60px"
  pin-current:
    backgroundColor: "{colors.green}"
    textColor: "{colors.paper}"
    typography: "{typography.pin}"
    rounded: "{rounded.pin}"
    size: "22px"
  pin-said:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.pin}"
    rounded: "{rounded.pin}"
    size: "22px"
  pin-pending:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.mute}"
    typography: "{typography.pin}"
    rounded: "{rounded.pin}"
    size: "22px"
  plate-ground:
    backgroundColor: "{colors.plate}"
    rounded: "{rounded.r-lg}"
    padding: "32px 48px"
  readout-highlight:
    backgroundColor: "{colors.ochre-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.readout}"
    rounded: "{rounded.sm}"
    padding: "8px 16px 10px"
  thumb-tab-current:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.ink}"
    padding: "6px 10px 8px"
  tag:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.body}"
    rounded: "{rounded.pill}"
    padding: "0 9px"
    height: "24px"
  tag-attention:
    backgroundColor: "{colors.ochre-soft}"
    textColor: "{colors.ochre-ink}"
    rounded: "{rounded.pill}"
    padding: "0 9px"
    height: "24px"
  action-bar:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.body}"
    padding: "14px 20px"
  action-bar-good:
    backgroundColor: "{colors.good-bg}"
    textColor: "{colors.good}"
  action-bar-bad:
    backgroundColor: "{colors.bad-bg}"
    textColor: "{colors.bad}"
---

# Design System: Lemma

## Overview

**Creative North Star: "The Field Guide Plate"**

Every concept is a plate in a naturalist's field guide. The live model sits on a pale painted ground (the plate), and beside it, on white book paper, a column of numbered notes points at it. When a note is read, its number is pinned onto the slider, readout or drawn mark it names, so text and model are read together. The interface speaks of a lesson, its outline and its concepts; each concept is one plate. Everything else on the page is plain paper and ink, divided by hairlines.

The system is quiet and dense in a way that reads easily: one sans family set large for reading, rules instead of boxes, and range-map colours that each have one job. Green is the single action colour and marks the note being read now. Ochre-soft marks whatever is being talked about. Blue, ochre, green and violet are the data inks on the model and the concept tab colours. The paper's own words, and only those, are set in Literata italic, the way a species name is set on a plate.

The world rejects the centred lesson card and boxed chrome around a model: no frames around content, no shadows on cards, no kicker labels above headings, no costumed controls. Controls are native range sliders, radios, selects and buttons, restyled and labelled in sentence case.

**Key Characteristics:**
- White paper for reading, the plate ground (#eef1ec) only under live models.
- Hairline rules (1px, rule / rule-strong) separate notes, lists and readouts; nothing is framed.
- Small round number pins tie notes to the controls, readouts and drawn marks they name.
- One green action per screen, in a fixed bottom action bar.
- Atkinson Hyperlegible Next for everything; Literata italic only for the paper's words.
- Native controls, restyled: the slider track fills in its series ink.

## Colors

Book paper and green-black ink, with four range-map colours that each carry a job, never decoration.

### Primary
- **Range-map Green** (green): the one action colour. Primary buttons, the Continue button in the action bar, the current note's pin, the active step mark, focus outlines, checkbox and radio accents, the default slider ink. Pressed and hover state is **Deep Green** (green-press); **Green Wash** (green-soft) fills a chosen option, text selection and the current note's pin halo.

### Secondary
- **Ochre** (ochre) and its **Ochre Wash** (ochre-soft): attention. Ochre-soft is the "being talked about" highlight: a readout or slider row that a note or a term is currently naming, a highlighted table cell, the highlighted idea line in the home figure's paper excerpt, the attention tag. **Ochre Ink** (ochre-ink) is the text colour on ochre-soft.

### Tertiary
- **Map Blue** (blue): links and a concept tab ink; also the first data ink.
- **Map Violet** (violet): a concept tab ink and the fourth data ink.
- **Data inks** (model-0 to model-7): series colours on the plate, led by blue, deepened ochre (model-1), green (model-2) and violet, then deepened Okabe-Ito. Each holds 3:1 or more on the plate ground. Series also differ by dash, marker shape and label.

### Neutral
- **Book Paper** (paper): the page, the notes column, the action bar, cards set on the plate (the statement, the equation, the paper excerpt).
- **Field Ink** (ink): headings, values, the said-note pin, done marks, the dark caption.
- **Body Ink** (body): running text. **Mute** (mute): metadata, captions, tick labels, unread notes. **Faint** (faint): disabled text only.
- **Hairline** (rule) and **Strong Hairline** (rule-strong): dividers, input and option borders, the empty pin ring, slider track remainder.
- **Plate Ground** (plate) and **Deep Plate** (plate-2): the painted ground under a live model, and the dividers between readouts on it.
- **Feedback** (good, good-bg, bad, bad-bg): correct and wrong states in the action bar and reveal, always paired with an icon and words.

### Named Rules
**The Live Ground Rule.** The plate ground means "live model here". It is never a callout fill; callouts and notes are text between hairlines. (It may also tint a hover, the current thumb tab, a neutral tag or a command well, which are states, not containers.)

**The One Green Rule.** Green is the only action colour. One green button per screen; everything else is a paper or ghost button.

**The Ink Has A Job Rule.** Each range-map colour has a role (action, attention, link, concept tab, data series). A colour that means nothing does not go on the page.

## Typography

**Display Font:** Atkinson Hyperlegible Next (with system-ui, -apple-system, Segoe UI, Roboto, sans-serif)
**Body Font:** Atkinson Hyperlegible Next, variable 200 to 800
**Words Font:** Literata italic (with Georgia, Times New Roman, serif)
**Mono:** ui-monospace stack, for commands and source only

**Character:** one legible humanist sans does every job, from 46px headings to 11.5px pin numerals, with tabular figures wherever numbers change. Literata italic is the paper speaking: quotes, paper titles, the paper excerpts in the home figure.

### Hierarchy
- **Display** (700, clamp(36px, 3.6vw, 52px), 1.05): the home page's opening headline and overview titles.
- **Headline** (700, clamp(32px, 3.6vw, 46px), 1.12): page h1.
- **Title** (700, clamp(26px, 2.3vw, 32px), 1.12): the concept title at the head of the notes column; section h2 at clamp(24px, 2.4vw, 30px).
- **Title small** (700, 19px, 1.25): list item titles, step titles, h3 in lists.
- **Lead** (400, 19px, 1.5, max 60ch): the paper in brief and page introductions; 20px on the plate.
- **Body** (400, 17px, 1.55): notes and running text; explanations cap at 64ch.
- **Label** (600, 15px, 1.3): form labels, slider labels, note heads, buttons (16px).
- **Readout** (600, 25px, 1, tabular): live values on the plate; 19px on small screens.
- **Pin** (700, 11.5px, tabular): numerals inside the round pins.
- **Words** (Literata italic 400, 23px, 1.45): concept quotes, with curly quotes added; 17px for paper titles on the plate, 14px for excerpt lines.

### Named Rules
**The Paper's Own Words Rule.** Literata italic is reserved for words that come from the paper: quotes, paper titles, excerpts. Lemma's own copy is never set in it.

**The Sentence Case Rule.** Headings, buttons and labels are sentence case. No uppercase labels, no tracking, no kicker line above a heading.

**The Tabular Numbers Rule.** Every number that moves (readouts, slider values, pins, reading times, stats) uses tabular figures.

## Layout

The lesson is a two-column field-guide spread: a notes column on paper (minmax(320px, 440px), sticky contents, hairline on its right edge) and the plate filling the rest (padding 32px clamp(20px, 3vw, 48px), inner max 960px). A thin sticky top bar (60px minimum) carries the wordmark, the paper's citation and title, and one thumb tab per concept; a fixed bottom action bar (about 80px) carries the hint, Show me and the green Continue. The home page reuses the spread: intro and notes left (minmax(320px, 440px)), a plate-ground figure right.

Outside the lesson, content sits in a 1240px container with 24px side padding (respecting safe areas), and reading blocks cap at 760px. Rhythm runs on 6, 10, 14, 22, 32, 40, 56 and 80px; lists are rows between hairlines with 12 to 20px vertical padding.

Responsive: at 1100px overview and home grids collapse to one column; at 900px the lesson stacks (notes above plate) and the notes column shows only the active step and the current note; at 640px brief step labels hide; at 520px readouts fall to a three-up grid, controls move above readouts and the action bar buttons go full width. Coarse pointers get 48px buttons and 30px slider thumbs. Short landscape screens unstick the top bar and keep two columns.

## Elevation & Depth

Depth is tonal, not cast: paper sits on paper, the model sits on the plate ground, and white cards (statement, equation, paper excerpt) sit on the plate. Shadows are few and functional: a 1px lift under the green button, a soft lift under a slider thumb and the selected segment, and real elevation only for things that float over content (the floating error, the home demo prompt, the action bar's faint upward shade). Number pins and empty marks use inset rings, not shadows.

### Shadow Vocabulary
- **Action lift** (`box-shadow: 0 1px 2px rgba(29, 35, 33, .14)`): primary button at rest only; removed when pressed or disabled.
- **Thumb lift** (`box-shadow: 0 1px 3px rgba(29, 35, 33, .25)`): slider thumbs.
- **Segment lift** (`box-shadow: 0 1px 3px rgba(29, 35, 33, .16)`): the active segment in a segmented control.
- **Bar shade** (`box-shadow: 0 -4px 18px rgba(29, 35, 33, .05)`): the fixed action bar.
- **Float** (`box-shadow: 0 10px 30px rgba(29, 35, 33, .16), 0 0 0 1px #dfe3de`): an error that floats over the lesson.
- **Focus ring** (`box-shadow: 0 0 0 3px` green at 22%): text inputs on focus; other elements use a 2px green outline with 2px offset.

### Named Rules
**The Flat Card Rule.** Cards, notes and list rows never carry a shadow. Only floating layers and touchable thumbs are lifted.

## Shapes

Gently softened corners: 6px on buttons, inputs and slider rows, 10px on the plate ground, options and white cards on the plate, 4px on readouts and table cells, 2px on the paper excerpt. Pills (9999px) for tags, chips and scrollbar thumbs. Pins, step marks and key dots are circles. Borders are 1px hairlines; pin rings are 1.5px insets; the active note's ring is 2px. Concept thumb tabs are marked by a 3px ink bar on their bottom edge (4px when current), rounded only on top.

## Components

### Buttons
Quiet, sentence case, one green action.
- **Shape:** softened corners (6px), 46px tall, 0 20px padding, label weight 600 at 16px.
- **Primary:** green fill, white text, action lift; hover and press go to green-press. Disabled turns to plate fill with faint text.
- **Default:** paper fill with a strong hairline border; hover darkens the border to ink; press fills with plate.
- **Ghost:** transparent, hover fills plate; a ghost after the first button in a row becomes an underlined text action.
- **Action bar buttons:** 50px tall, 0 26px padding, 17px.
- **Focus:** 2px green outline, 2px offset.

### Chips
- **Tag:** 24px pill, plate fill, body text, 13px weight 600. The attention variant uses ochre-soft and ochre-ink.
- **Topic chip:** 36px pill paper button; the "surprise" chip uses ochre-soft.

### Cards / Containers
- **Corner Style:** 10px.
- **Background:** the plate ground for the live model; paper for the statement, equation and paper excerpt set on it.
- **Shadow Strategy:** none (see The Flat Card Rule).
- **Border:** none. Everything else is a row between hairlines.
- **Internal Padding:** 20 to 26px for cards on the plate; 22px to 34px for the home plate.

### Inputs / Fields
- **Style:** paper fill, strong hairline border, 6px corners, 46px tall, 17px text, green caret.
- **Focus:** border turns green with a 3px green ring at 22%.
- **Choices:** radios and checkboxes stay native with a green accent. Answer options and provider options are 60px rows with a strong hairline and 10px corners; chosen fills green-soft with a green border; on reveal the answer goes good-bg, a wrong choice goes dashed.
- **Sliders:** native range inputs restyled: 6px pill track filled in the series ink up to the value, strong hairline for the rest; a 22px paper thumb ringed in the series ink. The slider row has its label, a tabular value and an optional Play button.

### Navigation
- **Site head:** a thin bar, wordmark (a green ring dot and "Lemma" at 700 21px) left, nav links (600 15px, body ink) right, hairline below; links hover to a plate fill.
- **Lesson top bar:** sticky, paper at 96% with blur, hairline below. Concept thumb tabs show the concept number and title (two lines, 600 13px) and reading time (tabular). Inks cycle violet, green, ochre, blue by concept order; the current tab takes a plate fill and a 4px ink bar; done tabs a full-ink 3px bar; future tabs a 40% bar and muted text. On narrow screens tabs shrink to number and time.
- **Brief steps:** a row of 4px bars above the paper in brief: ink once read, green for the current one.

### Numbered Notes and Pins (signature)
The notes column lists the concept's steps between hairlines, each with a 22px round mark: empty ring when unread, green ring with a green centre dot when active, ink fill with a check when done. Inside the active step, the narrated tour is a numbered list: each line's 22px pin is a pale ring while waiting, green with a green-soft halo while being read, and ink once read. A note may name one part or a list of one to four: sliders, readouts, or drawn marks that carry an id (curve series, points, markers, horizontal reference lines, bars, causal nodes). While a note plays, its number is pinned onto each part it names, green; once the note has been read the pin stays in ink, and all pins clear when the screen changes.

- **On controls and readouts:** a 22px round pin on the row's top-left corner with a 2px plate-coloured halo; the row takes the ochre-soft highlight while the note plays.
- **On drawn marks:** an SVG pin (11px radius circle, green fill, 2.5px plate-coloured ring, 700 11.5px white numeral) placed at the anchor the mark reports: a bar's right edge, min(18px, half its height) below its top; a series about 82% across, clamped inside the plot; 15px up and left of a point; a marker's foot; 16px in from the plot's left on a reference line; a causal node's top-right corner.
- **Concept pin:** the concept's own big pin (34px) at the head of the notes column takes its thumb tab's ink.

### Readouts
Live values on the plate in a row of cells divided by deep-plate hairlines: a muted 14px label with a colour key dot, a 25px tabular value. The highlighted cell takes ochre-soft.

### Quote
The paper's words in Literata italic at 23px, with curly quotes, and a muted 14px sans caption naming where they come from. Set on paper, with a hairline above in the brief.

### Action Bar
Fixed at the bottom on paper with a hairline above. Left: the message or hint; right: Show me and the green Continue. It turns good-bg or bad-bg with a matching head colour and icon when an answer is checked, and lifts 3px briefly.

## Do's and Don'ts

### Do:
- **Do** put every live model on the plate ground (#eef1ec), and nothing else.
- **Do** separate notes, lists, readouts and settings with 1px hairlines instead of boxes.
- **Do** pin a note's number onto every control, readout or drawn mark it names (up to four): green while it is read, ink once said, cleared when the screen changes.
- **Do** use ochre-soft to mark what is being talked about, and green for the one action and the current note.
- **Do** cycle concept tab inks violet, green, ochre, blue, and give the concept's pin its tab's ink.
- **Do** order data inks blue, ochre, green, violet, and also vary dash, shape and label.
- **Do** give any drawn mark a note may name an id, so its pin has an anchor.
- **Do** use native sliders, radios, selects and buttons, restyled, with sentence-case labels.
- **Do** set the paper's own words in Literata italic, and everything else in Atkinson Hyperlegible Next.
- **Do** use tabular figures for every changing number.

### Don't:
- **Don't** use the plate ground as a callout or panel fill; callouts are text between hairlines.
- **Don't** put a kicker or eyebrow label above a heading.
- **Don't** put shadows on cards, notes or list rows, and don't frame content in bordered boxes.
- **Don't** add a second green button to a screen.
- **Don't** set Lemma's own copy in Literata, or use it for headings.
- **Don't** use uppercase or letter-spaced labels.
- **Don't** costume controls; a slider stays a slider.
- **Don't** let colour alone tell series or feedback apart.
