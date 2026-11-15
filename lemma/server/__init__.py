"""Lemma's web server, for signed-in accounts, the same on your own computer as hosted. It keeps no logs.

The package, by what each part does:

* ``core``: what every handler shares: Request, ApiError, the routes (``@route``, ``find_route``), the learner's
  provider, the shipped example and gallery, and the quality checks a lesson passes before anyone reads it;
* ``http``: the HTTP server itself (``make_server``): static files, sign-in and sign-out, limits, dispatch;
* one module per part of the API: ``account``, ``searches``, ``builds``, ``library``, ``gallery``, ``sharing``
  and ``admin``. Each handler is declared where it is written, with ``@route(method, pattern)``.

Importing the package registers every route. What the rest of Lemma and the tests use is named here; settings
and internals are set or patched on the module that owns them (``server.http.DEV``, ``server.builds.MAX_RUNNING``,
``server.core.require_valid``), since that is where they are read.
"""

from __future__ import annotations

from . import core, http, account, admin, builds, gallery, library, searches, sharing  # each registers its routes
from .account import (api_event, api_feedback_create, api_models, api_sign_in, api_sign_in_login, api_sign_in_logout,
                      api_status)
from .admin import (api_admin_listing, api_admin_listing_lesson, api_admin_listings, api_feedback_delete, api_feedback_list,
                    api_feedback_status, api_stats)
from .builds import (api_papers, api_request, api_request_add, api_request_cancel, api_request_create, api_request_delete,
                     api_request_outline, api_request_retry, api_requests)
from .core import (EXAMPLES, GALLERY, NO_SOURCE, ROUTES, STATIC, ApiError, Request, Route, ensure_checked, find_route,
                   gallery_index, load_example, load_gallery, provider_from_request, route, source_for)
from .gallery import (api_example, api_gallery, api_gallery_lesson, card_quote, gallery_cover, quote_author,
                      short_authors)
from .http import Handler, Server, make_server, trusted_proxy
from .library import api_export, api_lesson, api_lesson_delete, api_lessons, api_save
from .searches import api_search, api_search_status
from .sharing import (api_gallery_community, api_share_get, api_share_set, api_share_stop, api_shared_about,
                      api_shared_hide, api_shared_list, api_shared_open, api_shared_progress)

__all__ = [  # the modules, then what the rest of Lemma and the tests use
    "account", "admin", "builds", "core", "gallery", "http", "library", "searches", "sharing", "ApiError", "EXAMPLES",
    "GALLERY", "Handler", "NO_SOURCE", "ROUTES", "Request", "Route", "STATIC", "Server", "api_admin_listing",
    "api_admin_listing_lesson", "api_admin_listings", "api_event", "api_example", "api_export", "api_feedback_create",
    "api_feedback_delete", "api_feedback_list", "api_feedback_status", "api_gallery", "api_gallery_community",
    "api_gallery_lesson", "api_lesson", "api_lesson_delete", "api_lessons", "api_models", "api_papers", "api_request",
    "api_request_add", "api_request_cancel", "api_request_create", "api_request_delete", "api_request_outline",
    "api_request_retry", "api_requests", "api_save", "api_search", "api_search_status", "api_share_get",
    "api_share_set", "api_share_stop", "api_shared_about", "api_shared_hide", "api_shared_list", "api_shared_open",
    "api_shared_progress", "api_sign_in", "api_sign_in_login", "api_sign_in_logout", "api_stats", "api_status",
    "card_quote", "ensure_checked", "find_route", "gallery_cover", "gallery_index", "load_example", "load_gallery",
    "make_server", "provider_from_request", "quote_author", "route", "short_authors", "source_for", "trusted_proxy",
]
