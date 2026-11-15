/* What the app and the lesson player share, in one place: building elements (h), which links may be followed
   (safeUrl), the icons, and words and dates said the same way everywhere. Loaded before the player and the app, and
   inlined in a downloaded lesson with the player. */
(function (root) {
  "use strict";

  /* A lesson's links are data, never script: a link is kept only if the browser would take it to a web page, a mail
     address or a place on this page. The browser's own parser decides, so no disguise (a tab or control character in
     "javascript:", odd case, an entity) gets through. Returns the link, or null to drop it. */
  function safeUrl(v, base) {
    if (typeof v !== "string") return null;
    const t = v.trim();
    if (t === "" || t.startsWith("#")) return v;
    let u;
    try { u = new URL(v, base || (typeof location !== "undefined" ? location.href : undefined)); } catch (e) { return null; }
    return ["http:", "https:", "mailto:"].includes(u.protocol) ? v : null;
  }
  function h(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if ((k === "href" || k === "src") && safeUrl(v) === null) continue;  // a lesson's links are data, never script
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return n;
  }

  // Icons: 16-unit line drawings in the text colour.
  const ICONS = {
    check: '<path d="M3.5 8.5l3 3 6-6.5"/>',
    cross: '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/>',
    copy: '<rect x="5.5" y="5.5" width="8" height="8"/><path d="M10.5 5.5V2.5h-8v8h3"/>',
    refresh: '<path d="M13 8a5 5 0 1 1-1.5-3.6M13 2.5v3h-3"/>',
    play: '<path d="M5 3.5v9l7-4.5z" fill="currentColor" stroke="none"/>',
    up: '<path d="M8 13V3M4 7l4-4 4 4"/>',
    down: '<path d="M8 3v10M4 9l4 4 4-4"/>',
    dash: '<path d="M4 8h8"/>',
    plus: '<path d="M8 3.5v9M3.5 8h9"/>',
    link: '<path d="M7 9l2-2M6.2 5.3l1.1-1.1a2.6 2.6 0 0 1 3.7 3.7l-1.1 1.1M9.8 10.7l-1.1 1.1a2.6 2.6 0 0 1-3.7-3.7l1.1-1.1"/>',
    search: '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5l3.5 3.5"/>',
    out: '<path d="M9.5 2.5h4v4M13.5 2.5L7.5 8.5M11.5 9.5v4h-9v-9h4"/>',
    shuffle: '<path d="M2.5 4.5h3l5 7h3M2.5 11.5h3l5-7h3M12 3l1.5 1.5L12 6M12 10l1.5 1.5L12 13"/>',
    next: '<path d="M3 8h10M9 4l4 4-4 4"/>',
    doc: '<path d="M9.5 2.5h-6v11h9v-8z"/><path d="M9.5 2.5v3h3M5.5 8.5h5M5.5 11h3.5"/>',
    chevron: '<path d="M6 3.5L10.5 8 6 12.5"/>',
    leave: '<path d="M6.5 2.5h-4v11h4M10 5l3 3-3 3M13 8H6"/>',
    up_thumb: '<path d="M5 7.2v6.3H2.5V7.2zM5 7.2l2.6-4.7c1 0 1.7.9 1.5 1.9l-.4 2.1h3.5c.9 0 1.5.8 1.3 1.7l-.9 4.1c-.2.7-.8 1.2-1.5 1.2H5"/>',
    down_thumb: '<g transform="rotate(180 8 8)"><path d="M5 7.2v6.3H2.5V7.2zM5 7.2l2.6-4.7c1 0 1.7.9 1.5 1.9l-.4 2.1h3.5c.9 0 1.5.8 1.3 1.7l-.9 4.1c-.2.7-.8 1.2-1.5 1.2H5"/></g>',
    flag: '<path d="M3.5 14V2.5M3.5 3h8.5l-2.2 3.2L12 9.5H3.5"/>',
    mail: '<rect x="2" y="3.5" width="12" height="9" rx="1.5"/><path d="M2.5 4.5L8 9l5.5-4.5"/>',
    share: '<path d="M8 10V2.5M5 5.5l3-3 3 3"/><path d="M4 8H3v5.5h10V8h-1"/>',
    eye: '<path d="M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8s-2.4 4.5-6.5 4.5S1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/>',
    clock: '<circle cx="8" cy="8" r="6"/><path d="M8 4.8V8l2.2 1.6"/>',
    back: '<path d="M13 8H3M7 4L3 8l4 4"/>',
    close: '<path d="M4 4l8 8M12 4l-8 8"/>',
    sound: '<path d="M2.5 6v4h2.5l3.5 3V3L5 6z"/><path d="M11 5.5a3.5 3.5 0 0 1 0 5M12.8 3.8a6 6 0 0 1 0 8.4"/>',
    mute: '<path d="M2.5 6v4h2.5l3.5 3V3L5 6z"/><path d="M11 6l4 4M15 6l-4 4"/>',
    pause: '<path d="M5 3.5v9M11 3.5v9" stroke-width="2.4"/>',
    trail: '<circle cx="12" cy="4" r="2" fill="currentColor"/><circle cx="8" cy="8" r="1.6" opacity=".6" fill="currentColor"/><circle cx="4.5" cy="11.5" r="1.3" opacity=".35" fill="currentColor"/>',
  };
  function icon(name) {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 16 16");
    s.setAttribute("class", "icon");
    s.setAttribute("aria-hidden", "true");
    s.innerHTML = ICONS[name];
    return s;
  }

  // A link that opens in a new tab says so, to the eye (the out arrow) and to a screen reader.
  const ext = (href, ...kids) => h("a", { href, target: "_blank", rel: "noopener noreferrer", class: "ext" }, ...kids, icon("out"), h("span", { class: "sr-only" }, " (opens in a new tab)"));

  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  // Dates. when(): "today", "yesterday" or "12 Oct" (with the year when it isn't this one), as a <time>.
  function when(sec, withTime) {
    const d = new Date(sec * 1000), now = new Date();
    const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const ago = Math.round((day(now) - day(d)) / 864e5);
    const date = ago === 0 ? "today" : ago === 1 ? "yesterday"
      : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
    const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    return h("time", { datetime: d.toISOString() }, withTime && ago < 2 ? `${date} at ${time}` : date);
  }
  // lastHere(): how long ago, for "Last here …": "just now", "today", "yesterday", "3 days ago", then "on 12 Nov".
  const DAY = 864e5;
  function lastHere(ms) {
    if (!ms) return "";
    const midnight = (t) => new Date(t).setHours(0, 0, 0, 0);
    const days = Math.round((midnight(Date.now()) - midnight(ms)) / DAY);
    if (Date.now() - ms < 60e3) return "just now";
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 7) return `${days} days ago`;
    return `on ${shortDate(ms)}`;
  }
  // shortDate(): "12 Nov".
  const shortDate = (ms) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

  root.LemmaUI = { h, icon, ext, safeUrl, plural, when, lastHere, shortDate };
})(typeof window !== "undefined" ? window : globalThis);
