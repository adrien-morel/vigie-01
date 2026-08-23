"""Journalisation structurée du pipeline — format exploitable par Cloud Logging.

Une ligne de sortie = un objet JSON sur stdout. Cloud Run capte stdout et le parse en `jsonPayload`,
à deux conditions que ce module tient : la sévérité doit être portée par le champ `severity` (et non
`level`, que Cloud Logging ignore — tout remonterait alors en `DEFAULT`, et une erreur ne se
distinguerait plus d'une ligne d'information dans une alerte), et le JSON doit tenir sur une seule
ligne (un objet réparti sur plusieurs lignes est découpé en autant d'entrées illisibles).

Les mesures sont émises en **champs structurés**, jamais interpolées dans le message : un run tronqué
doit se filtrer par `jsonPayload.truncated=true`, pas par un grep sur du texte libre. C'est la
différence entre une journalisation et une trace décorative — et la raison d'être de l'item
« vérifier que le format est exploitable par Cloud Logging » du plan de mise en production.

Aucun état métier ne passe par ici : ce module écrit sur stdout, il ne persiste rien (cf. la règle
« tout état durable passe par backend/memory/persistence.py »).
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

# Nom de la racine commune à tous les journaux du projet. Un logger dédié plutôt que le logger
# racine : uvicorn configure le sien, et se greffer dessus mélangerait le format d'accès HTTP et
# celui du pipeline.
ROOT = "vigie"

# Champs de LogRecord que la bibliothèque standard pose elle-même : tout le reste de __dict__ est,
# par construction, un champ ajouté par l'appelant via `extra=`.
_STANDARD = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            # Cloud Logging promeut ces trois clés hors du jsonPayload ; les autres restent dedans
            # et sont filtrables par `jsonPayload.<clé>`.
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "logger": record.name,
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # default=str plutôt qu'un échec : une mesure non sérialisable doit dégrader la ligne, pas
        # faire échouer le run qu'elle est censée documenter.
        return json.dumps(payload, ensure_ascii=False, default=str)


class _TextFormatter(logging.Formatter):
    """Repli lisible à l'œil pour le développement local — jamais utilisé en production."""

    def format(self, record: logging.LogRecord) -> str:
        fields = {k: v for k, v in record.__dict__.items() if k not in _STANDARD}
        suffix = " " + " ".join(f"{k}={v}" for k, v in fields.items()) if fields else ""
        return f"{record.levelname:<8} {record.name:<16} {record.getMessage()}{suffix}"


def configure_logging() -> None:
    """Installe le handler sur le logger racine du projet. Idempotent : appelée par run_pipeline()
    et à l'import de l'API, qui peuvent s'exécuter dans le même processus."""
    logger = logging.getLogger(ROOT)
    if logger.handlers:
        return
    # Sous Windows, stdout retombe sur la page de code ANSI (cp1252) dès que la sortie est
    # redirigée : une dépêche en cyrillique ou en coréen dans un champ du journal fait alors échouer
    # l'écriture sur UnicodeEncodeError — c'est-à-dire que la journalisation ferait tomber le run
    # qu'elle est censée documenter. Même piège que l'`encoding="utf-8"` explicite exigé partout
    # ailleurs dans ce dépôt. `errors="replace"` dégrade le caractère, jamais la ligne.
    if (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    handler = logging.StreamHandler(sys.stdout)
    text_mode = os.getenv("VIGIE_LOG_FORMAT", "json").lower() == "text"
    handler.setFormatter(_TextFormatter() if text_mode else _JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(os.getenv("VIGIE_LOG_LEVEL", "INFO").upper())
    # Sans cela, chaque ligne sortirait deux fois dès qu'un appelant (uvicorn, pytest) a configuré
    # le logger racine de la stdlib.
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Logger d'un nœud ou d'un module, sous la racine commune. `name` sert de filtre côté
    Cloud Logging (`jsonPayload.logger`), donc il porte le nom du nœud, pas celui du fichier."""
    return logging.getLogger(f"{ROOT}.{name}")
