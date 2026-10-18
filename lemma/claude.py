"""Building lessons with Claude, through the Anthropic API and the learner's own API key."""

from __future__ import annotations

import anthropic

from .llm import Conversation, Provider, ProviderError, Reply, REQUEST_TIMEOUT

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 64000  # streamed, so a long concept has room without hitting request timeouts
# Models that take server-side fallbacks: a request their safety classifiers decline is re-run
# on the model Anthropic recommends for that kind of refusal, instead of failing the concept.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
BASE_URL = None  # the SDK's default; tests point it at a stand-in


class ClaudeProvider(Provider):
    id = "claude"
    name = "Claude"

    def __init__(self, key: str, model: str = ""):
        self.key = key.strip()
        self.model = model or DEFAULT_MODEL
        self._client: anthropic.Anthropic | None = None
        self._effort: bool | None = None

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model})"

    def available(self) -> tuple[bool, str]:
        if not self.key:
            return False, "Add your Claude key in Settings to build lessons."
        return True, ""

    def client(self) -> anthropic.Anthropic:
        ok, msg = self.available()
        if not ok:
            raise ProviderError(msg)
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.key, base_url=BASE_URL, timeout=REQUEST_TIMEOUT, max_retries=0)
        return self._client

    def models(self) -> list[dict]:
        with errors(self):
            listed = list(self.client().models.list())
        # Lemma asks for adaptive thinking, so older models without it are left out.
        return [{"id": m.id, "name": m.display_name or m.id, "context": m.max_input_tokens or 0}
                for m in listed if supports(m, "thinking", "types", "adaptive")]

    def takes_effort(self) -> bool:
        if self._effort is None:
            with errors(self):
                self._effort = supports(self.client().models.retrieve(self.model), "effort", "high")
        return self._effort

    def conversation(self, system, document):
        return ClaudeConversation(self, system, document)

    def request(self, system: str, messages: list, max_tokens: int = MAX_TOKENS) -> dict:
        """The parameters of every request, so a warm-up renders the same prefix as the real requests it serves."""
        params = dict(model=self.model, max_tokens=max_tokens, system=system, messages=messages, thinking={"type": "adaptive"})
        if self.takes_effort():
            params["output_config"] = {"effort": "high"}  # lessons are judged on quality; Opus 5.5 defaults to medium
        if self.model in FALLBACK_MODELS:
            params.update(betas=[FALLBACK_BETA], fallbacks="default")
        return params

    def warm(self, system, document):
        """Writes the system prompt and paper to the cache with one prefill-only request (max_tokens 0, so no output
        is billed), so concepts drafted in parallel read one copy instead of each writing its own. Returns the usage."""
        params = self.request(system, opening(document), max_tokens=0)  # not streamed: max_tokens 0 rejects streaming
        client = self.client()
        with errors(self):
            create = client.beta.messages.create if "betas" in params else client.messages.create
            return create(**params).usage


def supports(model, *path: str) -> bool:
    """Whether a model's capabilities say yes at the end of `path`, e.g. ("effort", "high")."""
    node = model.capabilities
    try:
        for name in path:
            node = getattr(node, name)
        return bool(node.supported)
    except AttributeError:  # not listed: assume not
        return False


def opening(document: str) -> list:
    """The first message of every conversation: the paper, with a cache breakpoint at its end. Every concept shares
    the system prompt and paper but ends in its own task, so without this marker each request would cache only its
    own whole prompt and none would read another's."""
    return [{"role": "user", "content": [{"type": "text", "text": document, "cache_control": {"type": "ephemeral"}}]}]


class ClaudeConversation(Conversation):
    """The API keeps nothing, so each turn re-sends the paper and the conversation so far.
    The cache makes the repeated paper cheap, and replies go back exactly as Claude sent them."""

    def __init__(self, provider: ClaudeProvider, system: str, document: str):
        self.p = provider
        self.system = system
        self.messages: list = opening(document)

    def send(self, text, cancelled=None, on_progress=None):
        messages = self.messages + [{"role": "user", "content": text}]
        # The paper's breakpoint is shared by every concept; the automatic one caches this conversation's own turns for its repairs.
        params = self.p.request(self.system, messages) | {"cache_control": {"type": "ephemeral"}}
        client = self.p.client()
        with errors(self.p):
            stream_fn = client.beta.messages.stream if "betas" in params else client.messages.stream
            written = 0
            with stream_fn(**params) as stream:
                for event in stream:
                    if cancelled is not None and cancelled.is_set():
                        raise ProviderError("Cancelled.")  # leaving the block closes the stream
                    if on_progress and event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            written += len(event.delta.text)
                            on_progress("writing", written)
                        elif event.delta.type == "thinking_delta":
                            on_progress("thinking", written)
                final = stream.get_final_message()
        if final.stop_reason == "refusal":
            raise ProviderError("Claude declined to write this part of the lesson. Try another model in Settings.")
        reply = "".join(b.text for b in final.content if b.type == "text")
        self.messages = messages + [{"role": "assistant", "content": final.content}]
        return Reply(text=reply, stop_reason="max_tokens" if final.stop_reason == "max_tokens" else "end_turn")


class errors:
    """Turns the SDK's errors into messages for the learner."""

    def __init__(self, provider: ClaudeProvider):
        self.p = provider

    def __enter__(self):
        return self

    def __exit__(self, kind, e, tb):
        if e is None or isinstance(e, ProviderError):
            return False
        if isinstance(e, anthropic.APIStatusError):
            body = e.body if isinstance(e.body, dict) else {}
            e.message = (body.get("error") or {}).get("message") or e.message  # just the API's own words
        if isinstance(e, anthropic.AuthenticationError):
            raise ProviderError(f"Claude rejected the key. Check it in Settings. ({e.message})") from None
        if isinstance(e, anthropic.PermissionDeniedError):
            raise ProviderError(f"This Claude key can't use {self.p.model}. ({e.message})") from None
        if isinstance(e, anthropic.NotFoundError):
            raise ProviderError(f"Claude doesn't offer {self.p.model}. Choose another model in Settings.") from None
        if isinstance(e, anthropic.RateLimitError):
            raise ProviderError(f"Claude says you've hit a rate or usage limit: {e.message}") from None
        if isinstance(e, anthropic.BadRequestError):
            if "too long" in e.message.lower() or "context" in e.message.lower():
                raise ProviderError(f"This paper is too long for {self.p.model}. Choose a model with a larger context in Settings.") from None
            raise ProviderError(f"Claude couldn't take this request: {e.message}") from None
        if isinstance(e, anthropic.APIStatusError):
            raise ProviderError(f"Claude returned an error ({e.status_code}): {e.message}") from None
        if isinstance(e, anthropic.APITimeoutError):
            raise ProviderError("Claude took too long to reply.") from None
        if isinstance(e, anthropic.APIConnectionError):
            raise ProviderError("Couldn't reach Claude. Check your internet connection.") from None
        return False
