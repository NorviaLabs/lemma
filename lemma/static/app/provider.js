/* The learner's AI provider: choosing one, adding a key or signing in with a subscription, and the models it offers. */
import { api, busy, cleanups, cred, credHeaders, errorBox, ext, h, icon, saveCred, setStatus, status } from "./shell.js";

const TAGLINES = {
  "opencode-go": "Many models through an OpenCode Go plan. Reads long sources: about 1M tokens, roughly 750,000 words.",
  openai: "OpenAI's models, billed to your OpenAI API account.",
  claude: "Anthropic's Claude models, billed to your Claude API account. Reads long sources: about 1M tokens, roughly 750,000 words.",
  chatgpt: "Your ChatGPT Plus or Pro plan, no key needed. Lessons count against the plan's usage.",
  "claude-subscription": "Your Claude Pro or Max plan, no key needed. Lessons count against the plan's usage. Reads long sources: about 1M tokens, roughly 750,000 words.",
};

// Said wherever the key comes up, so it reads the same each time.
const KEY_NOTE = "Your key stays in this browser and is never saved in OpenLemma's storage. The server uses it only while a request or build runs.";

/* Pick a provider, then paste a key or sign in; Lemma checks either by listing the provider's models.
   `compact` (the connect step) picks the provider's default model and keeps the model list folded away.
   `quiet` (the account page, which says where the key lives above the form) leaves out the key note. */
export function keyForm(onSaved, { compact = false, quiet = false, onCheck = null } = {}) {
  const providers = status.providers || [];
  let selected = providers.some((x) => x.id === cred.provider) ? cred.provider : (providers[0] || {}).id;
  const signins = {};  // sign-in provider id -> its status, e.g. { signed_in, email }
  let poll = null;
  const body = h("div");
  const msg = h("div", { role: "status" });
  const stopPoll = () => { clearTimeout(poll); poll = null; };
  cleanups.push(stopPoll);
  const ready = (x) => (x.sign_in ? !!(signins[x.id] || {}).signed_in : !!cred.keys[x.id]);
  function draw() {
    const p = providers.find((x) => x.id === selected) || {};
    const key = h("input", { id: "ai-key", type: "password", autocomplete: "off", spellcheck: "false", placeholder: `Paste your ${p.name} key` });
    key.value = cred.keys[p.id] || "";
    const model = h("select", { id: "model", disabled: true }, h("option", { value: cred.models[p.id] || p.default_model }, cred.models[p.id] || p.default_model));
    const note = h("p", { class: "muted small" }, p.sign_in ? "Sign in to choose from your plan's models." : "Add a key to choose from the models it can use.");
    const modelName = h("span", {}, cred.models[p.id] || p.default_model);
    const choice = h("div", { class: "provider-choice", role: "radiogroup", "aria-label": "AI provider" }, providers.map((x) =>
      h("label", { class: "provider-option" },
        h("input", { type: "radio", name: "provider", value: x.id, checked: x.id === selected, onchange: () => { selected = x.id; msg.replaceChildren(); draw(); } }),
        h("span", { class: "po-body" },
          h("span", { class: "po-name" }, x.name),
          h("span", { class: "po-tagline" }, TAGLINES[x.id] || "")),
        ready(x) ? h("span", { class: "po-status ok" }, icon("check"), x.sign_in ? "Signed in" : "Key added") : null)));
    async function loadModels(c) {
      const r = await api("/api/models", undefined, undefined, credHeaders(c));
      model.replaceChildren(...r.models.map((m) => h("option", { value: m.id, selected: m.id === r.current }, `${m.name}${m.context ? ` · ${Math.round(m.context / 1000)}k context` : ""}`)));
      if (!r.models.some((m) => m.id === r.current)) model.prepend(h("option", { value: r.current, selected: true }, `${r.current} (not offered right now)`));
      model.disabled = false;
      note.textContent = `${r.models.length} model${r.models.length === 1 ? "" : "s"} offered by ${p.name}.`;
      modelName.textContent = model.selectedOptions[0] ? model.value : r.current;
    }
    // `onCheck` hears whether the saved provider's key still lists models, so the account page can say so.
    const checked = (ok) => { if (onCheck && p.id === cred.provider) onCheck(ok); };
    if (ready(p)) loadModels(Object.assign({}, cred, { provider: p.id })).then(() => checked(true), (err) => { note.replaceChildren(errorBox(err.message)); checked(false); });
    const save = h("button", { class: "primary", disabled: p.sign_in && !ready(p), onclick: async () => {
      const next = { provider: p.id, keys: Object.assign({}, cred.keys), models: Object.assign({}, cred.models) };
      if (!p.sign_in) next.keys[p.id] = key.value.trim();
      if (!model.disabled && model.value) next.models[p.id] = model.value;
      if (!p.sign_in && !next.keys[p.id]) return msg.replaceChildren(errorBox(`Paste your ${p.name} key first.`));
      busy(save, true);
      msg.replaceChildren(h("p", { class: "muted" }, p.sign_in ? "Checking your sign-in…" : "Checking the key…"));
      try {
        await loadModels(next);  // a key that can't list models won't build lessons either
        if (!model.disabled && model.value) next.models[p.id] = model.value;
        saveCred(next);
        setStatus(await api("/api/status"));
        msg.replaceChildren(h("p", { class: "ok" }, icon("check"), ` Saved. Lessons will be built with ${status.provider.label}.`));
        if (onSaved) onSaved();
      } catch (err) { msg.replaceChildren(errorBox(err.message)); }
      busy(save, false);
    } }, compact ? "Connect and continue" : p.sign_in ? "Check and save" : "Check and save key");
    model.addEventListener("change", () => { modelName.textContent = model.value; });
    const modelPart = compact
      ? h("details", { class: "model-pick" }, h("summary", {}, "Model: ", modelName, h("span", { class: "mp-change" }, "Change")),
          h("label", { for: "model", class: "sr-only" }, `${p.name} model`), model, note)
      : h("div", {}, h("label", { for: "model" }, `${p.name} model`), model, note);
    body.replaceChildren(choice, ...(p.sign_in ? signInPart(p) : [
      h("label", { for: "ai-key" }, `${p.name} key`), key,
      h("p", { class: "muted small" }, ext(p.key_url, `Get ${/^[aeiou]/i.test(p.name) ? "an" : "a"} ${p.name} key`),
        quiet ? "." : [". ", KEY_NOTE])]),
      modelPart, msg,
      h("div", { class: "actions" }, save));
  }
  // The subscriptions, signed in to instead of given a key. ChatGPT shows a code here to enter on OpenAI's page, and
  // OpenLemma notices when it's done; Claude shows a code on its page to paste back here. Each account signs in on its own.
  const brand = (p) => (p.id === "chatgpt" ? "ChatGPT" : "Claude");
  function signInPart(p) {
    const st = signins[p.id] || {};
    if (st.signed_in) {
      return [h("p", {}, icon("check"), ` Signed in${st.email ? ` as ${st.email}` : ""}. `,
        h("button", { class: "ghost small", onclick: async () => { signins[p.id] = await api(`/api/signin/${p.id}/logout`, {}); draw(); } }, "Sign out"))];
    }
    if (st.waiting && p.id === "chatgpt") {  // the learner types this code on OpenAI's page; nothing on this computer listens for them
      const open = h("button", { class: "primary", onclick: () => {
        navigator.clipboard?.writeText(st.code).catch(() => {});
        window.open(st.url, "_blank", "noopener");
      } }, "Copy code and open OpenAI");
      return [h("div", { class: "device-step" },
        h("p", {}, "Enter this code on OpenAI's sign-in page:"),
        h("p", { class: "device-code" }, st.code),
        open,
        h("p", { class: "muted small" }, "OpenAI's page calls this the Codex CLI and says the code is in your terminal. It means this code. "
          + "OpenLemma notices when you're done, and the code lasts 15 minutes."))];
    }
    if (st.waiting) {  // Claude: approve on its page, then paste the code it shows back here
      const code = h("input", { type: "text", id: "claude-code", autocomplete: "off", spellcheck: "false", placeholder: "Paste the code here" });
      const finish = h("button", { class: "primary", onclick: async () => {
        if (!code.value.trim()) return msg.replaceChildren(errorBox("Paste the code Claude showed you first."));
        busy(finish, true);
        try {
          signins[p.id] = await api(`/api/signin/${p.id}/login`, { code: code.value.trim() });
          msg.replaceChildren();
        } catch (err) { signins[p.id] = await api(`/api/signin/${p.id}`).catch(() => ({})); msg.replaceChildren(errorBox(err.message)); }
        draw();
      } }, "Finish sign-in");
      return [h("div", { class: "device-step" },
        h("p", {}, "Approve OpenLemma on Claude's page, then paste the code it shows you:"),
        h("p", {}, h("button", { onclick: () => window.open(st.url, "_blank", "noopener") }, "Open Claude")),
        h("label", { for: "claude-code", class: "sr-only" }, "Code from Claude"), code, finish,
        h("p", { class: "muted small" }, "Claude's page calls this Claude Code. It means OpenLemma. The sign-in lasts 15 minutes."))];
    }
    const start = h("button", { class: "primary", onclick: async () => {
      try {
        signins[p.id] = await api(`/api/signin/${p.id}/login`, {});
        draw();
        body.querySelector(".device-step")?.scrollIntoView({ block: "center", behavior: "smooth" });
        if (p.id === "chatgpt") waitForSignIn(p);
        else window.open(signins[p.id].url, "_blank", "noopener");
      } catch (err) { msg.replaceChildren(errorBox(err.message)); }
    } }, `Sign in with ${brand(p)}`);
    return [start, h("p", { class: "muted small" }, `Lessons count against your plan's usage. OpenLemma keeps your ${brand(p)} sign-in with your account, on its server, and you can sign out at any time.`)];
  }
  function waitForSignIn(p) {
    stopPoll();
    poll = setTimeout(async () => {
      if (!body.isConnected) return;  // the learner left the account page
      let st;
      try { st = signins[p.id] = await api(`/api/signin/${p.id}`); } catch (e) { return waitForSignIn(p); }
      if (st.signed_in) { msg.replaceChildren(); return draw(); }
      if (st.error) { draw(); return msg.replaceChildren(errorBox(st.error)); }  // the code is gone: back to the button
      if (st.waiting) waitForSignIn(p);
    }, 1500);
  }
  draw();
  for (const x of providers.filter((x) => x.sign_in)) {
    api(`/api/signin/${x.id}`).then((r) => {
      signins[x.id] = r; draw();
      if (r.waiting && x.id === "chatgpt") waitForSignIn(x);  // a sign-in started before this page was opened
    }).catch(() => {});
  }
  return body;
}
