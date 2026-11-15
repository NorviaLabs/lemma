"""The signed-in account: the status the app starts from, the provider's models, subscription sign-ins, anonymous
browser events and sending feedback."""

from __future__ import annotations

from .. import __version__, auth, categorize, chatgpt, claude, feedback, jev, levels, metrics, shares, store
from ..llm import DEFAULT_PROVIDER, PROVIDERS, ProviderError
from . import core
from .core import ApiError, provider_from_request, route


@route("GET", r"/api/status")
def api_status(req):
    try:
        p = provider_from_request(req)
    except ApiError:  # a saved provider this server doesn't offer: report the default, unconnected, so the account page can offer the rest
        p = core.make_provider(DEFAULT_PROVIDER)
    ok, msg = p.available()
    status = {
        "version": __version__,
        "provider": {"id": p.id, "name": p.name, "model": p.model, "label": p.label, "ok": ok, "message": msg},
        "providers": [{"id": i.id, "name": i.name, "default_model": i.default_model, "key_url": i.key_url, "sign_in": not i.key_url} for i in PROVIDERS.values()],
        "library_count": len(store.list_lessons(req.owner())) if req.user else 0,
        "user": req.user,
        "level": store.settings(req.owner()).get("level", levels.DEFAULT) if req.user else levels.DEFAULT,
        "levels": [{"id": k, "name": name} for k, (name, _) in levels.LEVELS.items()],
        "fields": [{"id": k, "name": name} for k, (name, _) in categorize.CATEGORIES.items() if k != "other"],
        "sign_in": auth.providers(),
        "typesafe": jev.available(),  # search results and source text also go to TypeSafe, which the privacy notes must say
    }
    if req.is_admin():
        status["feedback_new"] = feedback.count_new()
        status["site_today"] = metrics.site_today()
        status["gallery_waiting"] = shares.count_waiting()
    return status


@route("GET", r"/api/models")
def api_models(req):
    """Models offered by the provider in the request headers, read live with the learner's key. Also checks the key."""
    p = provider_from_request(req)
    ok, msg = p.available()
    if not ok:  # no key, or no sign-in: the learner's to fix, not the provider's
        raise ApiError(400, msg)
    try:
        models = p.models()
    except ProviderError as e:
        raise ApiError(502, str(e)) from None
    return {"provider": p.id, "models": models, "current": p.model}


SIGN_INS = {"chatgpt": chatgpt, "claude-subscription": claude}  # providers signed in to with a subscription, per account


@route("GET", r"/api/signin/(chatgpt|claude-subscription)")
def api_sign_in(req, pid):
    return SIGN_INS[pid].status(req.owner())


@route("POST", r"/api/signin/(chatgpt|claude-subscription)/login")
def api_sign_in_login(req, pid):
    """Starts a subscription sign-in, or finishes one. ChatGPT: the browser opens the returned page, where the learner
    enters the returned code, and OpenLemma notices. Claude: the browser opens the returned page, which shows the
    learner a code once they approve, and they send it back here as ``code``."""
    owner = req.owner()
    try:
        if pid == "claude-subscription" and req.body.get("code"):
            return claude.finish_sign_in(owner, str(req.body["code"]))
        return SIGN_INS[pid].start_sign_in(owner)
    except ProviderError as e:
        raise ApiError(409, str(e)) from None


@route("POST", r"/api/signin/(chatgpt|claude-subscription)/logout")
def api_sign_in_logout(req, pid):
    SIGN_INS[pid].sign_out(req.owner())
    return SIGN_INS[pid].status(req.owner())


@route("POST", r"/api/event")
def api_event(req):
    """An anonymous count from the browser, such as a goal reached; only the event's name is kept."""
    body = req.body
    if body.get("name") in metrics.BROWSER_EVENTS:
        metrics.count(body["name"])
    return {}


@route("POST", r"/api/feedback")
def api_feedback_create(req):
    body = req.body
    owner = req.owner()
    try:
        fields = feedback.clean(body)
    except ValueError as e:
        raise ApiError(400, str(e)) from None
    if not metrics.take(owner, "feedback"):
        raise ApiError(429, f"You've sent today's {metrics.limit('feedback')} feedback messages. They reset at midnight UTC.")
    user = req.user
    return {"id": feedback.add(user, fields), "reply_to": user.get("email") or ""}
