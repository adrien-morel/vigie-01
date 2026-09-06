"""Persistence layer: the same state, served by local files in dev or by Firestore in production
(see docs/scoping.md §10, README §deployment).

Why this layer exists. On Cloud Run the file system is ephemeral and specific to each instance: the
three states of the pipeline (LLM budget, seen links, analysed history) would start again from zero
on every cold start, redeployment or scale-out. That is not merely a loss of history — the
`MAX_LLM_CALLS_PER_DAY` guardrail (docs/scoping.md §6, non-negotiable) would become circumventable by
a simple restart again, and deduplication would pay for LLM calls on items already analysed. The
limitation was documented in guardrails.py and store.py; it is lifted here.

The local backend stays the default: nothing reaches GCP without an explicit
`VIGIE_STORAGE=firestore`.

The interface is deliberately narrow and semantic (`reserve_llm_call` rather than a generic
`read`/`write`): the atomicity of the budget counter is a property of the storage, not of the caller.
With a local file it is trivial (a single process); with Firestore it requires a transaction. A
`read_modify_write` exposed to business code would be correct locally and wrong in production.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from backend.config import FIRESTORE_DATABASE, FIRESTORE_PROJECT, STORAGE_BACKEND

# Firestore root: a single prefix for all of the service's state, so that a GCP project shared with
# other workloads stays readable.
_BUDGET_DOC = "vigie_state/llm_budget"
_SEEN_COLLECTION = "vigie_seen_items"
_ANALYZED_COLLECTION = "vigie_analyzed_items"


class Persistence(Protocol):
    """Shared pipeline state. All dates are ISO strings (`YYYY-MM-DD`) that compare
    lexicographically — that is what lets the `>= since` filters work identically in memory (local
    backend) and inside a Firestore query."""

    def reserve_llm_call(self, day: str, limit: int) -> bool:
        """Reserves one LLM call for `day`. Returns False if the cap has already been reached.

        Must be atomic: two instances reserving at the same time must not be able to exceed `limit`
        between them.
        """

    def calls_used(self, day: str) -> int: ...

    def seen_links(self, since: str) -> dict[str, str]:
        """Links already collected since `since`, mapped to their first-seen date."""

    def mark_seen(self, links: dict[str, str]) -> None: ...

    def analyzed_since(self, since: str) -> list[dict]:
        """Items analysed since `since`. The single source of the digest served by the API and of
        the verifier's cross-check search (see backend/memory/store.py)."""

    def put_analyzed(self, records: list[dict]) -> None:
        """Inserts or updates by `link`: a re-analysed item replaces its previous version rather
        than creating a duplicate."""

    def purge_before(self, seen_cutoff: str, analyzed_cutoff: str) -> None:
        """Permanently deletes whatever has left the retention windows."""


def _doc_id(link: str) -> str:
    """A link cannot be used as-is as a Firestore document id (`/` forbidden, bounded length): we
    hash it. The link itself stays stored in clear inside the document."""
    return hashlib.sha1(link.encode("utf-8")).hexdigest()


class LocalFilePersistence:
    """Development backend: three JSON files, one per state.

    Sufficient as long as a single process writes (local dev, or a single scheduled job). Not suitable
    for Cloud Run — which is precisely what FirestorePersistence fixes.
    """

    def __init__(self, budget_file: Path, seen_file: Path, analyzed_file: Path) -> None:
        self._budget_file = budget_file
        self._seen_file = seen_file
        self._analyzed_file = analyzed_file

    @staticmethod
    def _read(path: Path, default):
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write(path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- budget ------------------------------------------------------------------------------
    def reserve_llm_call(self, day: str, limit: int) -> bool:
        data = self._read(self._budget_file, {"date": "", "calls": 0})
        if data.get("date") != day:
            data = {"date": day, "calls": 0}
        if data["calls"] >= limit:
            return False
        data["calls"] += 1
        self._write(self._budget_file, data)
        return True

    def calls_used(self, day: str) -> int:
        data = self._read(self._budget_file, {"date": "", "calls": 0})
        return data["calls"] if data.get("date") == day else 0

    # -- deduplication -----------------------------------------------------------------------
    def seen_links(self, since: str) -> dict[str, str]:
        seen = self._read(self._seen_file, {})
        return {link: day for link, day in seen.items() if day >= since}

    def mark_seen(self, links: dict[str, str]) -> None:
        seen = self._read(self._seen_file, {})
        seen.update(links)
        self._write(self._seen_file, seen)

    # -- analysed history --------------------------------------------------------------------
    def analyzed_since(self, since: str) -> list[dict]:
        records = self._read(self._analyzed_file, [])
        return [r for r in records if r.get("date", "") >= since]

    def put_analyzed(self, records: list[dict]) -> None:
        existing = self._read(self._analyzed_file, [])
        by_link = {r["link"]: r for r in existing}
        for record in records:
            by_link[record["link"]] = record
        self._write(self._analyzed_file, list(by_link.values()))

    def purge_before(self, seen_cutoff: str, analyzed_cutoff: str) -> None:
        seen = self._read(self._seen_file, {})
        self._write(self._seen_file, {link: day for link, day in seen.items() if day >= seen_cutoff})
        records = self._read(self._analyzed_file, [])
        self._write(self._analyzed_file, [r for r in records if r.get("date", "") >= analyzed_cutoff])


class FirestorePersistence:
    """Production backend. `google-cloud-firestore` is imported lazily: local dev (the default
    backend) does not have to install the GCP dependency (backend/requirements-gcp.txt).

    Data model: the budget is a single document (a counter, incremented inside a transaction), seen
    links and the analysed history are collections indexed on `date` — a Firestore document is capped
    at 1 MB, which rules out storing several days of items in a single blob as the file backend does.
    """

    # Firestore caps a write batch at 500 operations.
    _BATCH_LIMIT = 500

    def __init__(self, project: str, database: str = "(default)") -> None:
        from google.cloud import firestore  # lazy import: optional dependency

        self._client = firestore.Client(project=project, database=database)
        self._firestore = firestore

    # -- budget ------------------------------------------------------------------------------
    def reserve_llm_call(self, day: str, limit: int) -> bool:
        doc_ref = self._client.document(_BUDGET_DOC)

        @self._firestore.transactional
        def _reserve(transaction) -> bool:
            snapshot = doc_ref.get(transaction=transaction)
            data = snapshot.to_dict() if snapshot.exists else None
            if not data or data.get("date") != day:
                data = {"date": day, "calls": 0}
            if data["calls"] >= limit:
                return False
            transaction.set(doc_ref, {"date": day, "calls": data["calls"] + 1})
            return True

        return _reserve(self._client.transaction())

    def calls_used(self, day: str) -> int:
        snapshot = self._client.document(_BUDGET_DOC).get()
        data = snapshot.to_dict() if snapshot.exists else None
        if not data or data.get("date") != day:
            return 0
        return int(data.get("calls", 0))

    # -- deduplication -----------------------------------------------------------------------
    def seen_links(self, since: str) -> dict[str, str]:
        query = self._client.collection(_SEEN_COLLECTION).where(filter=self._firestore.FieldFilter("date", ">=", since))
        return {doc.get("link"): doc.get("date") for doc in query.stream()}

    def mark_seen(self, links: dict[str, str]) -> None:
        self._commit_in_batches(
            (self._client.collection(_SEEN_COLLECTION).document(_doc_id(link)), {"link": link, "date": day})
            for link, day in links.items()
        )

    # -- analysed history --------------------------------------------------------------------
    def analyzed_since(self, since: str) -> list[dict]:
        query = self._client.collection(_ANALYZED_COLLECTION).where(
            filter=self._firestore.FieldFilter("date", ">=", since)
        )
        return [doc.to_dict() for doc in query.stream()]

    def put_analyzed(self, records: list[dict]) -> None:
        self._commit_in_batches(
            (self._client.collection(_ANALYZED_COLLECTION).document(_doc_id(record["link"])), record)
            for record in records
        )

    def purge_before(self, seen_cutoff: str, analyzed_cutoff: str) -> None:
        for collection, cutoff in ((_SEEN_COLLECTION, seen_cutoff), (_ANALYZED_COLLECTION, analyzed_cutoff)):
            query = self._client.collection(collection).where(filter=self._firestore.FieldFilter("date", "<", cutoff))
            self._delete_in_batches(doc.reference for doc in query.stream())

    def _commit_in_batches(self, writes) -> None:
        batch = self._client.batch()
        pending = 0
        for ref, data in writes:
            batch.set(ref, data)
            pending += 1
            if pending == self._BATCH_LIMIT:
                batch.commit()
                batch, pending = self._client.batch(), 0
        if pending:
            batch.commit()

    def _delete_in_batches(self, refs) -> None:
        batch = self._client.batch()
        pending = 0
        for ref in refs:
            batch.delete(ref)
            pending += 1
            if pending == self._BATCH_LIMIT:
                batch.commit()
                batch, pending = self._client.batch(), 0
        if pending:
            batch.commit()


_LOCAL_ROOT = Path(__file__).resolve().parent.parent
_instance: Persistence | None = None


def build_default() -> Persistence:
    if STORAGE_BACKEND == "firestore":
        if not FIRESTORE_PROJECT:
            raise RuntimeError("VIGIE_STORAGE=firestore requires FIRESTORE_PROJECT (see .env.example).")
        return FirestorePersistence(FIRESTORE_PROJECT, FIRESTORE_DATABASE)
    if STORAGE_BACKEND != "local":
        raise RuntimeError(f"Unknown VIGIE_STORAGE: {STORAGE_BACKEND!r} (expected 'local' or 'firestore').")
    return LocalFilePersistence(
        budget_file=_LOCAL_ROOT / ".llm_budget.json",
        seen_file=_LOCAL_ROOT / "memory" / ".seen_items.json",
        analyzed_file=_LOCAL_ROOT / "memory" / ".analyzed_history.json",
    )


def get_persistence() -> Persistence:
    """Builds the backend on first use, not at import time: importing backend.config must not open a
    Firestore connection (the tests import the module)."""
    global _instance
    if _instance is None:
        _instance = build_default()
    return _instance


def set_persistence(persistence: Persistence | None) -> None:
    """Injection point for the tests (and for a migration script). `None` restores the default."""
    global _instance
    _instance = persistence
