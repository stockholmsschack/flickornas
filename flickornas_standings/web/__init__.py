"""Local web adapter for the Flickornas standings tool."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import os
from pathlib import Path
import secrets
from typing import Any

from flask import Flask, Response, abort

from ..artifact_publication import read_public_snapshot
from ..member_system_client import MemberSystemClient

from .generation_operations import GenerationOperationManager
from .localization import load_catalogues
from .mercure import DisabledOperationPublisher, MercurePublisher
from .routes import local_host_request, pages


MANIFEST = {"id": "flickornas", "name": "Flickornas standings", "url_prefix": "/tools/flickornas"}


def register(app: Flask, settings: Mapping[str, Any], *, url_prefix: str = MANIFEST["url_prefix"]) -> None:
    """Register Flickornas services and routes in `app` using the supplied settings."""
    settings = {
        "DEFAULT_LOCALE": "sv", "BASE_TEMPLATE": "flickornas/flickornas_shell.jinja2",
        "MERCURE_PUBLIC_URL": "/.well-known/mercure", "CLOCK": lambda: datetime.now(UTC), **settings,
    }
    member_system_client = settings["MEMBER_SYSTEM_CLIENT"]
    publisher = settings.get("MERCURE_PUBLISHER") or DisabledOperationPublisher()
    app.extensions["flickornas"] = {
        "settings": settings,
        "catalogues": load_catalogues(),
        "member_system_client": member_system_client,
        "mercure_publisher": publisher,
        "generation_operations": GenerationOperationManager(
            Path(settings["STATE_DIRECTORY"]),
            Path(settings["OUTPUT_DIRECTORY"]),
            executor=settings.get("GENERATION_EXECUTOR"),
            runner=settings.get("GENERATION_RUNNER"),
            renderer=settings.get("GENERATION_RENDERER"),
            publisher=publisher,
            public_file_origin=settings["FILES_PUBLIC_ORIGIN"],
            url_prefix=url_prefix,
        ),
    }
    app.register_blueprint(pages, url_prefix=url_prefix)


def create_app(configuration: dict[str, Any] | None = None) -> Flask:
    """Create the standalone Flask application with configurable runtime paths."""
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        STATE_DIRECTORY=Path("state"),
        OUTPUT_DIRECTORY=Path("output"),
        SECRET_KEY=secrets.token_hex(32),
        MERCURE_HUB_URL=os.getenv(
            "MERCURE_HUB_URL",
            "http://127.0.0.1:5000/.well-known/mercure",
        ),
        MERCURE_PUBLIC_URL=os.getenv(
            "MERCURE_PUBLIC_URL",
            "/.well-known/mercure",
        ),
        MERCURE_JWT_SECRET=os.getenv("MERCURE_JWT_SECRET"),
        MERCURE_JWT_ALG=os.getenv("MERCURE_JWT_ALG", "HS256"),
        FILES_PUBLIC_ORIGIN=os.getenv(
            "FLICKORNAS_FILES_PUBLIC_ORIGIN",
            "http://flickornas.localhost:5000",
        ),
        GENERATION_TOURNAMENT_SELECTION_AUTHORIZER=local_host_request,
    )
    if configuration:
        app.config.update(configuration)
    app.config["MEMBER_SYSTEM_CLIENT"] = app.config.get("MEMBER_SYSTEM_CLIENT") or MemberSystemClient()
    if app.config.get("MERCURE_PUBLISHER") is None and app.config["MERCURE_JWT_SECRET"]:
        app.config["MERCURE_PUBLISHER"] = MercurePublisher(
            app.config["MERCURE_HUB_URL"],
            app.config["MERCURE_JWT_SECRET"],
            algorithm=app.config["MERCURE_JWT_ALG"],
            executor=app.config.get("MERCURE_EXECUTOR"),
            session=app.config.get("MERCURE_SESSION"),
        )
    register(app, app.config, url_prefix="")

    @app.get("/api/v1/standings/flickornas")
    def public_standings() -> Response:
        snapshot = read_public_snapshot(Path(app.config["OUTPUT_DIRECTORY"]))
        if snapshot is None:
            abort(404)
        return Response(snapshot, mimetype="application/json", headers={"Cache-Control": "no-cache"})

    return app


__all__ = ["MANIFEST", "create_app", "register"]
