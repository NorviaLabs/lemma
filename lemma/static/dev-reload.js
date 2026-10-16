/* Live reload for `lemma --dev`. Only included in development; never in downloaded lessons. */
(function () {
  "use strict";
  let boot = null;
  const es = new EventSource("api/dev/events");
  es.addEventListener("hello", (e) => {
    // A new boot id means the server restarted after a Python change: reload to pick it up.
    if (boot && boot !== e.data) location.reload();
    boot = e.data;
  });
  es.addEventListener("change", (e) => {
    const files = JSON.parse(e.data);
    if (files.length && files.every((f) => f.endsWith(".css"))) {
      // Swap stylesheets in place so the lesson keeps its state.
      document.querySelectorAll('link[rel="stylesheet"]').forEach((link) => {
        const url = new URL(link.href);
        url.searchParams.set("v", Date.now());
        link.href = url.toString();
      });
      console.info("[lemma dev] styles updated:", files.join(", "));
    } else {
      console.info("[lemma dev] reloading:", files.join(", "));
      location.reload();
    }
  });
})();
