"""Opaque server-side registry and format-preserving HLS playlist scanner."""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from collections.abc import Callable

    from backend.src.providers.models import HLSResource, PlaybackPlan

_URI_ATTRIBUTE = re.compile(r'(?P<prefix>\bURI\s*=\s*)"(?P<uri>[^"]*)"', re.IGNORECASE)


class HLSResourceRegistry:
    """Own playback plans and the opaque IDs exposed to browsers."""

    def __init__(self) -> None:
        self._plans: dict[str, PlaybackPlan] = {}

    def install(self, plan: PlaybackPlan) -> None:
        self._plans[plan.stream_id] = plan

    def revoke(self, stream_id: str) -> None:
        self._plans.pop(stream_id, None)

    def get_plan(self, stream_id: str) -> PlaybackPlan | None:
        return self._plans.get(stream_id)

    def resolve(self, stream_id: str, resource_id: str) -> HLSResource | None:
        plan = self._plans.get(stream_id)
        return plan.resources.get(resource_id) if plan else None

    @staticmethod
    def _register(plan: PlaybackPlan, resource: HLSResource) -> str:
        for resource_id, existing in plan.resources.items():
            if existing == resource:
                return resource_id
        resource_id = secrets.token_urlsafe(18)
        plan.resources[resource_id] = resource
        return resource_id

    def rewrite_playlist(
        self,
        plan: PlaybackPlan,
        parent: HLSResource,
        content: str,
        *,
        resolve: Callable[[HLSResource, str], HLSResource],
        app_prefix: str,
        token: str,
    ) -> str:
        if self._plans.get(plan.stream_id) is not plan:
            raise KeyError("playback plan is not active")

        def opaque_url(uri: str) -> str:
            resource = resolve(parent, uri)
            resource_id = self._register(plan, resource)
            return (
                f"{app_prefix}/hls/{quote(plan.stream_id, safe='')}/resources/"
                f"{quote(resource_id, safe='')}?token={quote(token, safe='')}"
            )

        rewritten: list[str] = []
        for line in content.splitlines(keepends=True):
            body = line.rstrip("\r\n")
            terminator = line[len(body) :]
            stripped = body.strip()
            if not stripped:
                rewritten.append(line)
                continue
            if stripped.startswith("#"):
                body = _URI_ATTRIBUTE.sub(
                    lambda match: f'{match.group("prefix")}"{opaque_url(match.group("uri"))}"',
                    body,
                )
            else:
                start = len(body) - len(body.lstrip())
                end = len(body.rstrip())
                body = f"{body[:start]}{opaque_url(body[start:end])}{body[end:]}"
            rewritten.append(body + terminator)
        return "".join(rewritten)
