"""Couche de persistance : le même état, servi par des fichiers locaux en dev ou par Firestore en
production (cf. docs/cadrage.md §10, README §déploiement).

Pourquoi cette couche existe. Sur Cloud Run le système de fichiers est éphémère et propre à chaque
instance : les trois états du pipeline (budget LLM, liens vus, historique analysé) repartiraient de
zéro à chaque cold start, redéploiement ou scale-out. Ce n'est pas seulement une perte d'historique
— le garde-fou `MAX_LLM_CALLS_PER_DAY` (docs/cadrage.md §6, non négociable) redeviendrait
contournable par un simple redémarrage, et le dédoublonnage repaierait des appels LLM sur des items
déjà analysés. La limite était documentée dans guardrails.py et store.py ; elle est ici levée.

Le backend local reste le défaut : rien ne part vers GCP sans `VIGIE_STORAGE=firestore` explicite.

L'interface est volontairement étroite et sémantique (`reserve_llm_call` plutôt qu'un `read`/`write`
générique) : l'atomicité du compteur de budget est une propriété du stockage, pas de l'appelant.
Avec un fichier local elle est triviale (un seul processus) ; avec Firestore elle demande une
transaction. Un `read_modify_write` exposé au code métier serait correct en local et faux en prod.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from backend.config import FIRESTORE_DATABASE, FIRESTORE_PROJECT, STORAGE_BACKEND

# Racine Firestore : un seul préfixe pour tout l'état du service, pour qu'un projet GCP partagé
# avec d'autres charges reste lisible.
_BUDGET_DOC = "vigie_state/llm_budget"
_SEEN_COLLECTION = "vigie_seen_items"
_ANALYZED_COLLECTION = "vigie_analyzed_items"


class Persistence(Protocol):
    """État partagé du pipeline. Toutes les dates sont des chaînes ISO (`YYYY-MM-DD`) comparables
    lexicographiquement — c'est ce qui permet aux filtres `>= since` de fonctionner à l'identique
    en mémoire (backend local) et dans une requête Firestore."""

    def reserve_llm_call(self, day: str, limit: int) -> bool:
        """Réserve un appel LLM pour `day`. Renvoie False si le plafond est déjà atteint.

        Doit être atomique : deux instances qui réservent en même temps ne doivent pas pouvoir
        dépasser `limit` à elles deux.
        """

    def calls_used(self, day: str) -> int: ...

    def seen_links(self, since: str) -> dict[str, str]:
        """Liens déjà collectés depuis `since`, associés à la date de première vue."""

    def mark_seen(self, links: dict[str, str]) -> None: ...

    def analyzed_since(self, since: str) -> list[dict]:
        """Items analysés depuis `since`. Source unique du digest servi par l'API et de la
        recherche de recoupement du vérificateur (cf. backend/memory/store.py)."""

    def put_analyzed(self, records: list[dict]) -> None:
        """Insère ou met à jour par `link` : un item ré-analysé remplace sa version précédente
        plutôt que d'en créer un doublon."""

    def purge_before(self, seen_cutoff: str, analyzed_cutoff: str) -> None:
        """Supprime définitivement ce qui est sorti des fenêtres de rétention."""


def _doc_id(link: str) -> str:
    """Un lien n'est pas utilisable tel quel comme identifiant de document Firestore (`/` interdit,
    longueur bornée) : on le hache. Le lien reste stocké en clair dans le document."""
    return hashlib.sha1(link.encode("utf-8")).hexdigest()


class LocalFilePersistence:
    """Backend de développement : trois fichiers JSON, un par état.

    Suffisant tant qu'un seul processus écrit (dev local, ou un job planifié unique). Ne convient
    pas à Cloud Run — c'est précisément ce que FirestorePersistence corrige.
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

    # -- dédoublonnage -----------------------------------------------------------------------
    def seen_links(self, since: str) -> dict[str, str]:
        seen = self._read(self._seen_file, {})
        return {link: day for link, day in seen.items() if day >= since}

    def mark_seen(self, links: dict[str, str]) -> None:
        seen = self._read(self._seen_file, {})
        seen.update(links)
        self._write(self._seen_file, seen)

    # -- historique analysé ------------------------------------------------------------------
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
    """Backend de production. `google-cloud-firestore` est importé paresseusement : le dev local
    (backend par défaut) n'a pas à installer la dépendance GCP (backend/requirements-gcp.txt).

    Modèle de données : le budget est un document unique (compteur, incrémenté en transaction),
    les liens vus et l'historique analysé sont des collections indexées sur `date` — un document
    Firestore est plafonné à 1 Mo, ce qui exclut de stocker plusieurs jours d'items dans un seul
    blob comme le fait le backend fichier.
    """

    # Firestore plafonne un batch d'écriture à 500 opérations.
    _BATCH_LIMIT = 500

    def __init__(self, project: str, database: str = "(default)") -> None:
        from google.cloud import firestore  # import paresseux : dépendance optionnelle

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

    # -- dédoublonnage -----------------------------------------------------------------------
    def seen_links(self, since: str) -> dict[str, str]:
        query = self._client.collection(_SEEN_COLLECTION).where(filter=self._firestore.FieldFilter("date", ">=", since))
        return {doc.get("link"): doc.get("date") for doc in query.stream()}

    def mark_seen(self, links: dict[str, str]) -> None:
        self._commit_in_batches(
            (self._client.collection(_SEEN_COLLECTION).document(_doc_id(link)), {"link": link, "date": day})
            for link, day in links.items()
        )

    # -- historique analysé ------------------------------------------------------------------
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
            raise RuntimeError("VIGIE_STORAGE=firestore exige FIRESTORE_PROJECT (cf. .env.example).")
        return FirestorePersistence(FIRESTORE_PROJECT, FIRESTORE_DATABASE)
    if STORAGE_BACKEND != "local":
        raise RuntimeError(f"VIGIE_STORAGE inconnu : {STORAGE_BACKEND!r} (attendu 'local' ou 'firestore').")
    return LocalFilePersistence(
        budget_file=_LOCAL_ROOT / ".llm_budget.json",
        seen_file=_LOCAL_ROOT / "memory" / ".seen_items.json",
        analyzed_file=_LOCAL_ROOT / "memory" / ".analyzed_history.json",
    )


def get_persistence() -> Persistence:
    """Construit le backend à la première utilisation, pas à l'import : un import de
    backend.config ne doit pas ouvrir de connexion Firestore (les tests importent le module)."""
    global _instance
    if _instance is None:
        _instance = build_default()
    return _instance


def set_persistence(persistence: Persistence | None) -> None:
    """Injection pour les tests (et pour un script de migration). `None` rétablit le défaut."""
    global _instance
    _instance = persistence
