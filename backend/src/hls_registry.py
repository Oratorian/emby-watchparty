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
_MAX_RESOURCES_PER_PLAN = 10_000


class HLSResourceRegistry:
    """Own playback plans and the opaque IDs exposed to browsers."""

    def __init__(self) -> None:
        self._plans: dict[str, PlaybackPlan] = {}
        self._resource_ids: dict[str, dict[HLSResource, str]] = {}

    def install(self, plan: PlaybackPlan) -> None:
        self._plans[plan.stream_id] = plan
        self._resource_ids[plan.stream_id] = {
            resource: resource_id for resource_id, resource in plan.resources.items()
        }

    def revoke(self, stream_id: str) -> None:
        self._plans.pop(stream_id, None)
        self._resource_ids.pop(stream_id, None)

    def revoke_all(self) -> int:
        count = len(self._plans)
        self._plans.clear()
        self._resource_ids.clear()
        return count

    def get_plan(self, stream_id: str) -> PlaybackPlan | None:
        return self._plans.get(stream_id)

    def resolve(self, stream_id: str, resource_id: str) -> HLSResource | None:
        plan = self._plans.get(stream_id)
        return plan.resources.get(resource_id) if plan else None

    def _register(self, plan: PlaybackPlan, resource: HLSResource) -> str:
        resource_ids = self._resource_ids[plan.stream_id]
        if resource_id := resource_ids.get(resource):
            return resource_id
        if len(plan.resources) >= _MAX_RESOURCES_PER_PLAN:
            raise ValueError("playback plan resource limit exceeded")
        resource_id = secrets.token_urlsafe(18)
        plan.resources[resource_id] = resource
        resource_ids[resource] = resource_id
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
