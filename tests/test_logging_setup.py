"""Contrat de format du journal — c'est lui que Cloud Logging lit, pas un humain.

Ces tests ne verifient pas « qu'on journalise » mais que la sortie reste parsable et filtrable :
un journal qui degrade en texte libre ne se voit qu'au premier incident en production, quand on
cherche pourquoi un run nocturne a rendu trois items.
"""

import json
import logging

from backend.logging_setup import ROOT, configure_logging, get_logger


def _emit(level: str, message: str, **fields) -> dict:
    """Formate une ligne avec le formateur JSON reel et rend l'objet parse."""
    from backend.logging_setup import _JsonFormatter

    record = logging.LogRecord(f"{ROOT}.test", getattr(logging, level), "f.py", 1, message, None, None)
    record.__dict__.update(fields)
    return json.loads(_JsonFormatter().format(record))


def test_severity_is_the_field_cloud_logging_reads():
    """`level` est ignore par Cloud Logging : sans `severity`, tout remonte en DEFAULT et une
    erreur cesse de se distinguer d'une ligne d'information dans une alerte."""
    payload = _emit("WARNING", "plafond atteint")

    assert payload["severity"] == "WARNING"
    assert payload["message"] == "plafond atteint"
    assert "level" not in payload


def test_measurements_are_structured_fields_not_interpolated_text():
    """Un run tronque doit se filtrer par `jsonPayload.truncated=true`, pas par un grep."""
    payload = _emit("INFO", "run termine", truncated=True, items=31, llm_calls_by_node={"analyze": 72})

    assert payload["truncated"] is True
    assert payload["items"] == 31
    assert payload["llm_calls_by_node"] == {"analyze": 72}


def test_one_record_is_one_line():
    """Un objet JSON reparti sur plusieurs lignes est decoupe en autant d'entrees illisibles."""
    from backend.logging_setup import _JsonFormatter

    record = logging.LogRecord(f"{ROOT}.test", logging.INFO, "f.py", 1, "message\nsur deux lignes", None, None)

    assert "\n" not in _JsonFormatter().format(record)


def test_an_unserializable_field_degrades_the_line_instead_of_failing_the_run():
    """Une mesure non serialisable doit couter une ligne moins precise, pas le run qu'elle documente."""
    payload = _emit("INFO", "mesure", objet=object())

    assert payload["message"] == "mesure"
    assert isinstance(payload["objet"], str)


def test_configure_logging_is_idempotent():
    """Appelee par run_pipeline() et a l'import de l'API, qui vivent dans le meme processus :
    un second handler doublerait chaque ligne.

    Les handlers sont vides puis restaures parce que pytest greffe les siens sur ce logger — il le
    fait justement parce que `propagate = False`, et leur presence ferait passer le test sans rien
    prouver (configure_logging sortirait des la premiere ligne)."""
    logger = logging.getLogger(ROOT)
    saved = logger.handlers[:]
    logger.handlers.clear()
    try:
        configure_logging()
        configure_logging()
        assert len(logger.handlers) == 1
    finally:
        logger.handlers[:] = saved

    assert get_logger("collect").name == f"{ROOT}.collect"
