"""Stable JSON errors for web API endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import HTTPException

from ..active_configuration import (
    ConfigurationValidationError,
    StaleConfigurationError,
)
from ..member_system_client import UpstreamError


def json_error(
    code: str,
    message_key: str,
    status: int,
    *,
    details: Mapping[str, Any] | None = None,
):
    """Create the versioned error envelope used by web API routes."""
    error: dict[str, Any] = {
        "code": code,
        "message_key": message_key,
        "details": dict(details or {}),
    }
    return jsonify({"error": error}), status


def register_error_handlers(blueprint: Blueprint) -> None:
    """Keep Flickornas' API failures structured while its HTML routes use Flask pages."""

    @blueprint.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        # Match by Flask rule so error handling works under any host mount prefix.
        if "/api/v1/" in request.url_rule.rule:
            return json_error(
                f"http_{error.code}",
                "errors.http",
                error.code or 500,
                details={"description": error.description},
            )
        return error

    @blueprint.errorhandler(UpstreamError)
    def handle_upstream_error(_error: UpstreamError):
        return json_error(
            "upstream_failure",
            "errors.member_system.unavailable",
            502,
        )

    @blueprint.errorhandler(ConfigurationValidationError)
    def handle_configuration_error(error: ConfigurationValidationError):
        return json_error(
            "invalid_configuration",
            "errors.configuration.invalid",
            422,
            details={"problems": list(error.problems)},
        )

    @blueprint.errorhandler(StaleConfigurationError)
    def handle_stale_configuration(error: StaleConfigurationError):
        details = (
            {"current_revision": error.current_revision}
            if error.current_revision is not None
            else None
        )
        return json_error(
            "stale_configuration",
            "errors.configuration.stale",
            409,
            details=details,
        )
