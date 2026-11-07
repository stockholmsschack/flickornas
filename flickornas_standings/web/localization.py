"""Shared server and browser localization catalogues."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from importlib.resources import files
from typing import Any

from flask import Blueprint, current_app, g, request


SUPPORTED_LOCALES = ("sv", "en")
LOCALE_COOKIE = "flickornas_locale"


def load_catalogues() -> dict[str, dict[str, str]]:
    """Load every bundled catalogue and require identical translation keys."""
    locale_root = files(__package__).joinpath("locales")
    catalogues: dict[str, dict[str, str]] = {}
    for locale in SUPPORTED_LOCALES:
        catalogue = json.loads(
            locale_root.joinpath(f"{locale}.json").read_text(encoding="utf-8")
        )
        if not isinstance(catalogue, dict):
            raise ValueError(f"locale catalogue {locale!r} must be an object")
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in catalogue.items()
        ):
            raise ValueError(
                f"locale catalogue {locale!r} must contain string values"
            )
        catalogues[locale] = catalogue

    expected_keys = set(catalogues[SUPPORTED_LOCALES[0]])
    for locale, catalogue in catalogues.items():
        if set(catalogue) != expected_keys:
            raise ValueError(
                f"locale catalogue {locale!r} has mismatched translation keys"
            )
    return catalogues


def register_localization(blueprint: Blueprint) -> None:
    """Select the request locale and expose its catalogue to Jinja.

    Use the host's locale when supplied.
    """

    @blueprint.before_request
    def select_locale() -> None:
        host_locale = current_app.extensions["flickornas"]["settings"].get("LOCALE")
        g.locale = host_locale() if host_locale else resolve_locale()

    @blueprint.after_request
    def remember_explicit_locale(response: Any) -> Any:
        requested = request.args.get("lang")
        if requested in SUPPORTED_LOCALES and not current_app.extensions["flickornas"]["settings"].get("LOCALE"):
            response.set_cookie(
                LOCALE_COOKIE,
                requested,
                max_age=60 * 60 * 24 * 365,
                samesite="Lax",
            )
        return response

    @blueprint.context_processor
    def localization_context() -> dict[str, Any]:
        catalogue = catalogue_for(g.locale)
        return {
            "locale": g.locale,
            "locales": SUPPORTED_LOCALES,
            "catalogue": catalogue,
            "t": translator(catalogue),
        }


def resolve_locale() -> str:
    """Resolve query choice, saved preference, browser language, then default."""
    explicit = request.args.get("lang")
    if explicit in SUPPORTED_LOCALES:
        return explicit

    saved = request.cookies.get(LOCALE_COOKIE)
    if saved in SUPPORTED_LOCALES:
        return saved

    browser_match = request.accept_languages.best_match(SUPPORTED_LOCALES)
    if browser_match:
        return browser_match

    default = current_app.extensions["flickornas"]["settings"]["DEFAULT_LOCALE"]
    return default if default in SUPPORTED_LOCALES else "sv"


def catalogue_for(locale: str) -> Mapping[str, str]:
    catalogues = current_app.extensions["flickornas"]["catalogues"]
    return catalogues[locale]


def translator(
    catalogue: Mapping[str, str],
) -> Callable[..., str]:
    """Return a key translator with explicit named-parameter interpolation."""

    def translate(key: str, **parameters: object) -> str:
        message = catalogue.get(key, key)
        return message.format_map(parameters) if parameters else message

    return translate
