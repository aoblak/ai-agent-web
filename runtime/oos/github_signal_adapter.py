from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from oos.github_signal_ingester import (
    GitHubSignalError,
    GitHubSignalStore,
    RawGitHubEvent,
    StoredSignal,
)


class GitHubAdapterError(RuntimeError):
    """Raised when read-only GitHub signal collection cannot be verified."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, str, Mapping[str, str]], HttpResponse]


@dataclass(frozen=True)
class SyncSummary:
    kind: str
    observed: int
    emitted: int
    baseline: bool


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
) -> HttpResponse:
    if method != "GET":
        raise GitHubAdapterError("GitHub signal adapter is read-only")
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return HttpResponse(
                status=int(response.status),
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(
            status=int(exc.code),
            headers=dict(exc.headers.items()) if exc.headers is not None else {},
            body=exc.read(),
        )
    except urllib.error.URLError as exc:
        raise GitHubAdapterError(f"GitHub request failed: {exc.reason}") from exc


class GitHubRestClient:
    """Minimal read-only GitHub REST client for signal collection."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.github.com",
        api_version: str = "2026-03-10",
        transport: Transport | None = None,
        max_pages: int = 100,
        allow_custom_base_url: bool = False,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise GitHubAdapterError("GitHub token is required for authenticated sync")
        if not isinstance(allow_custom_base_url, bool):
            raise GitHubAdapterError("allow_custom_base_url must be boolean")
        if not isinstance(base_url, str) or not base_url.strip():
            raise GitHubAdapterError("GitHub base_url must be a non-empty string")
        normalized_base = base_url.strip().rstrip("/")
        parsed = urllib.parse.urlparse(normalized_base)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise GitHubAdapterError("GitHub base_url must be a clean absolute HTTPS URL")
        if normalized_base != "https://api.github.com" and not allow_custom_base_url:
            raise GitHubAdapterError("custom GitHub base_url requires explicit opt-in")
        if (
            not isinstance(max_pages, int)
            or isinstance(max_pages, bool)
            or max_pages <= 0
        ):
            raise GitHubAdapterError("max_pages must be a positive integer")
        if not isinstance(api_version, str) or not api_version.strip():
            raise GitHubAdapterError("api_version must be a non-empty string")
        self.token = token.strip()
        self.base_url = normalized_base
        self.api_version = api_version.strip()
        self.transport = transport or _default_transport
        self.max_pages = max_pages

    def _headers(self, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return {
            "Accept": accept,
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": self.api_version,
            "User-Agent": "oos-github-signal-ingester",
        }

    def _get_json(
        self,
        path: str,
        *,
        accept: str = "application/vnd.github+json",
        allow_404: bool = False,
    ) -> Any:
        if not path.startswith("/"):
            raise GitHubAdapterError("GitHub API path must start with /")
        response = self.transport(
            "GET",
            f"{self.base_url}{path}",
            self._headers(accept=accept),
        )
        if response.status == 404 and allow_404:
            return None
        if response.status != 200:
            raise GitHubAdapterError(
                f"GitHub GET {path} returned HTTP {response.status}"
            )
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubAdapterError("GitHub response is not valid UTF-8 JSON") from exc

    def _paginate(
        self,
        path: str,
        *,
        accept: str = "application/vnd.github+json",
    ) -> list[Any]:
        items: list[Any] = []
        separator = "&" if "?" in path else "?"
        for page in range(1, self.max_pages + 1):
            payload = self._get_json(
                f"{path}{separator}per_page=100&page={page}",
                accept=accept,
            )
            if not isinstance(payload, list):
                raise GitHubAdapterError("paginated GitHub response must be a list")
            items.extend(payload)
            if len(payload) < 100:
                return items
        raise GitHubAdapterError("GitHub pagination exceeded max_pages")

    def authenticated_login(self) -> str:
        payload = self._get_json("/user")
        login = payload.get("login") if isinstance(payload, Mapping) else None
        if not isinstance(login, str) or not login.strip():
            raise GitHubAdapterError("authenticated GitHub response lacks login")
        return login

    def list_starred(self) -> dict[str, dict[str, Any]]:
        records = self._paginate(
            "/user/starred?sort=created&direction=asc",
            accept="application/vnd.github.star+json",
        )
        result: dict[str, dict[str, Any]] = {}
        for item in records:
            if not isinstance(item, Mapping):
                raise GitHubAdapterError("star record must be an object")
            repo = item.get("repo")
            starred_at = item.get("starred_at")
            if not isinstance(repo, Mapping):
                raise GitHubAdapterError(
                    "star timestamp media type response must include repo"
                )
            full_name = repo.get("full_name")
            if not isinstance(full_name, str) or not full_name:
                raise GitHubAdapterError("star record repository lacks full_name")
            if starred_at is not None and not isinstance(starred_at, str):
                raise GitHubAdapterError("starred_at must be a string or null")
            result[full_name] = {
                "starred_at": starred_at,
                "item": dict(item),
            }
        return result

    def list_following(self) -> dict[str, dict[str, Any]]:
        records = self._paginate("/user/following")
        result: dict[str, dict[str, Any]] = {}
        for item in records:
            if not isinstance(item, Mapping):
                raise GitHubAdapterError("following record must be an object")
            login = item.get("login")
            if not isinstance(login, str) or not login:
                raise GitHubAdapterError("following record lacks login")
            result[login] = {"item": dict(item)}
        return result

    def get_repository(self, repository: str) -> dict[str, Any]:
        if (
            not isinstance(repository, str)
            or repository.count("/") != 1
            or any(not part for part in repository.split("/"))
        ):
            raise GitHubAdapterError("repository must be owner/name")
        payload = self._get_json(f"/repos/{repository}")
        if not isinstance(payload, Mapping):
            raise GitHubAdapterError("repository response must be an object")
        full_name = payload.get("full_name")
        if full_name != repository:
            raise GitHubAdapterError("repository response full_name mismatch")
        owner = payload.get("owner")
        owner_login = owner.get("login") if isinstance(owner, Mapping) else None
        license_value = payload.get("license")
        license_spdx = (
            license_value.get("spdx_id")
            if isinstance(license_value, Mapping)
            else None
        )
        topics = payload.get("topics")
        if topics is None:
            topics = []
        if not isinstance(topics, list) or any(
            not isinstance(topic, str) for topic in topics
        ):
            raise GitHubAdapterError("repository topics must be a string list")
        return {
            "full_name": repository,
            "owner": owner_login,
            "private": payload.get("private"),
            "fork": payload.get("fork"),
            "archived": payload.get("archived"),
            "disabled": payload.get("disabled"),
            "visibility": payload.get("visibility"),
            "language": payload.get("language"),
            "topics": list(topics),
            "license_spdx": license_spdx,
            "stargazers_count": payload.get("stargazers_count"),
            "forks_count": payload.get("forks_count"),
            "open_issues_count": payload.get("open_issues_count"),
            "pushed_at": payload.get("pushed_at"),
            "updated_at": payload.get("updated_at"),
            "source": f"GET /repos/{repository}",
        }

    def is_watching(self, repository: str) -> bool:
        if (
            not isinstance(repository, str)
            or repository.count("/") != 1
            or any(not part for part in repository.split("/"))
        ):
            raise GitHubAdapterError("repository must be owner/name")
        payload = self._get_json(
            f"/repos/{repository}/subscription",
            allow_404=True,
        )
        if payload is None:
            return False
        if not isinstance(payload, Mapping):
            raise GitHubAdapterError("subscription response must be an object")
        subscribed = payload.get("subscribed")
        if not isinstance(subscribed, bool):
            raise GitHubAdapterError("subscription response lacks boolean subscribed")
        return subscribed


def _poll_payload(source: str, item: Mapping[str, Any], observed_at: str) -> dict[str, Any]:
    return {
        "source": source,
        "observed_at": observed_at,
        "item": dict(item),
    }


class GitHubSignalSynchronizer:
    """Snapshot/diff synchronizer that emits only evidence-supported signals."""

    def __init__(
        self,
        client: GitHubRestClient,
        store: GitHubSignalStore,
        *,
        actor: str,
    ) -> None:
        if not isinstance(actor, str) or not actor.strip():
            raise GitHubAdapterError("actor must be a non-empty GitHub login")
        self.client = client
        self.store = store
        self.actor = actor.strip()

    def _ingest(
        self,
        *,
        event_type: str,
        action: str,
        object_type: str,
        object_id: str,
        occurred_at: str,
        payload: Mapping[str, Any],
    ) -> StoredSignal:
        return self.store.ingest(
            RawGitHubEvent(
                transport="poller",
                event_type=event_type,
                action=action,
                actor=self.actor,
                object_type=object_type,
                object_id=object_id,
                occurred_at=occurred_at,
                payload=payload,
            )
        )

    def sync_stars(self, *, observed_at: str) -> SyncSummary:
        current = self.client.list_starred()
        with self.store.transaction():
            initialized, previous = self.store.poll_snapshot("star")
            emitted = 0

            if not initialized:
                for repository, metadata in current.items():
                    starred_at = metadata.get("starred_at")
                    if not isinstance(starred_at, str) or not starred_at:
                        continue
                    self._ingest(
                        event_type="star",
                        action="added",
                        object_type="repository",
                        object_id=repository,
                        occurred_at=starred_at,
                        payload=_poll_payload(
                            "GET /user/starred",
                            metadata,
                            observed_at,
                        ),
                    )
                    emitted += 1
            else:
                for repository in sorted(current.keys() - previous.keys()):
                    metadata = current[repository]
                    starred_at = metadata.get("starred_at")
                    occurred_at = (
                        starred_at
                        if isinstance(starred_at, str) and starred_at
                        else observed_at
                    )
                    self._ingest(
                        event_type="star",
                        action="added",
                        object_type="repository",
                        object_id=repository,
                        occurred_at=occurred_at,
                        payload=_poll_payload(
                            "GET /user/starred",
                            metadata,
                            observed_at,
                        ),
                    )
                    emitted += 1
                for repository in sorted(previous.keys() - current.keys()):
                    self._ingest(
                        event_type="star",
                        action="removed",
                        object_type="repository",
                        object_id=repository,
                        occurred_at=observed_at,
                        payload={
                            "source": "snapshot_diff:/user/starred",
                            "observed_at": observed_at,
                            "previous": previous[repository],
                        },
                    )
                    emitted += 1

            self.store.replace_poll_snapshot("star", current, observed_at=observed_at)
            return SyncSummary("star", len(current), emitted, not initialized)

    def sync_following(self, *, observed_at: str) -> SyncSummary:
        current = self.client.list_following()
        with self.store.transaction():
            initialized, previous = self.store.poll_snapshot("follow")
            emitted = 0

            if initialized:
                for login in sorted(current.keys() - previous.keys()):
                    self._ingest(
                        event_type="follow",
                        action="added",
                        object_type="user",
                        object_id=login,
                        occurred_at=observed_at,
                        payload=_poll_payload(
                            "GET /user/following",
                            current[login],
                            observed_at,
                        ),
                    )
                    emitted += 1
                for login in sorted(previous.keys() - current.keys()):
                    self._ingest(
                        event_type="follow",
                        action="removed",
                        object_type="user",
                        object_id=login,
                        occurred_at=observed_at,
                        payload={
                            "source": "snapshot_diff:/user/following",
                            "observed_at": observed_at,
                            "previous": previous[login],
                        },
                    )
                    emitted += 1

            self.store.replace_poll_snapshot("follow", current, observed_at=observed_at)
            return SyncSummary("follow", len(current), emitted, not initialized)

    def sync_watch_targets(
        self,
        repositories: Sequence[str],
        *,
        observed_at: str,
    ) -> SyncSummary:
        current: dict[str, dict[str, Any]] = {}
        for repository in repositories:
            watched = self.client.is_watching(repository)
            current[repository] = {"watched": watched}

        with self.store.transaction():
            initialized, previous = self.store.poll_snapshot("watch")
            emitted = 0
            if initialized:
                for repository, metadata in current.items():
                    previous_metadata = previous.get(repository)
                    if previous_metadata is None:
                        continue
                    before = previous_metadata.get("watched")
                    after = metadata.get("watched")
                    if not isinstance(before, bool) or not isinstance(after, bool):
                        raise GitHubAdapterError("watch snapshot must contain booleans")
                    if before == after:
                        continue
                    self._ingest(
                        event_type="watch",
                        action="added" if after else "removed",
                        object_type="repository",
                        object_id=repository,
                        occurred_at=observed_at,
                        payload={
                            "source": f"GET /repos/{repository}/subscription",
                            "observed_at": observed_at,
                            "previous_watched": before,
                            "watched": after,
                        },
                    )
                    emitted += 1

            merged = dict(previous) if initialized else {}
            merged.update(current)
            self.store.replace_poll_snapshot("watch", merged, observed_at=observed_at)
            return SyncSummary("watch", len(current), emitted, not initialized)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GitHubSignalError(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GitHubSignalError(f"{name} must be a non-empty string")
    return value


def raw_event_from_webhook(
    event_name: str,
    payload: Mapping[str, Any],
    *,
    delivery_id: str,
    received_at: str,
) -> RawGitHubEvent:
    """Translate a supported GitHub webhook envelope into a raw OOS event."""

    event_name = _string(event_name, "event_name")
    delivery_id = _string(delivery_id, "delivery_id")
    received_at = _string(received_at, "received_at")
    payload = _mapping(payload, "payload")
    sender = _mapping(payload.get("sender"), "sender")
    actor = _string(sender.get("login"), "sender.login")
    repository = _mapping(payload.get("repository"), "repository")
    repository_name = _string(repository.get("full_name"), "repository.full_name")

    if event_name == "star":
        action = _string(payload.get("action"), "action")
        if action not in {"created", "deleted"}:
            raise GitHubSignalError(f"unsupported star action: {action}")
        starred_at = payload.get("starred_at")
        occurred_at = (
            starred_at
            if action == "created" and isinstance(starred_at, str) and starred_at
            else received_at
        )
        return RawGitHubEvent(
            transport="webhook",
            event_type="star",
            action=action,
            actor=actor,
            object_type="repository",
            object_id=repository_name,
            occurred_at=occurred_at,
            payload=payload,
            source_event_id=delivery_id,
        )

    if event_name == "watch":
        action = _string(payload.get("action"), "action")
        return RawGitHubEvent(
            transport="webhook",
            event_type="watch",
            action=action,
            actor=actor,
            object_type="repository",
            object_id=repository_name,
            occurred_at=received_at,
            payload=payload,
            source_event_id=delivery_id,
        )

    if event_name == "fork":
        _mapping(payload.get("forkee"), "forkee")
        return RawGitHubEvent(
            transport="webhook",
            event_type="fork",
            action="created",
            actor=actor,
            object_type="repository",
            object_id=repository_name,
            occurred_at=received_at,
            payload=payload,
            source_event_id=delivery_id,
        )

    if event_name == "pull_request_review":
        action = _string(payload.get("action"), "action")
        pull_request = _mapping(payload.get("pull_request"), "pull_request")
        number = pull_request.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
            raise GitHubSignalError("pull_request.number must be a positive integer")
        review = _mapping(payload.get("review"), "review")
        submitted_at = review.get("submitted_at")
        occurred_at = (
            submitted_at
            if isinstance(submitted_at, str) and submitted_at
            else received_at
        )
        return RawGitHubEvent(
            transport="webhook",
            event_type="pull_request_review",
            action=action,
            actor=actor,
            object_type="pull_request",
            object_id=f"{repository_name}#{number}",
            occurred_at=occurred_at,
            payload=payload,
            source_event_id=delivery_id,
        )

    raise GitHubSignalError(f"unsupported webhook event: {event_name}")


def ingest_webhook(
    store: GitHubSignalStore,
    event_name: str,
    payload: Mapping[str, Any],
    *,
    delivery_id: str,
    received_at: str,
) -> StoredSignal:
    event = raw_event_from_webhook(
        event_name,
        payload,
        delivery_id=delivery_id,
        received_at=received_at,
    )
    return store.ingest(event)
