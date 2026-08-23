# Python 3.13 : même version que la CI (.github/workflows/ci.yml), pour que « les tests passent »
# et « l'image tourne » portent sur le même interpréteur.
FROM python:3.13-slim

# PYTHONUNBUFFERED est un prérequis de la journalisation, pas une préférence : hors terminal, stdout
# est mis en tampon par blocs, donc les lignes d'un run de dix minutes arriveraient groupées à la
# fin — et seraient perdues si le processus meurt avant de vider le tampon, c'est-à-dire exactement
# quand on a besoin de les lire.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Les dépendances avant le code : une modification de backend/ ne réinstalle pas la pile grpc.
# requirements-gcp.txt inclut requirements.txt et ajoute Firestore — l'image porte toujours le
# backend de persistance exigé en production, VIGIE_STORAGE choisit lequel s'active.
COPY backend/requirements.txt backend/requirements-gcp.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements-gcp.txt

COPY backend/ ./backend/

# Non root. Le chown couvre /app parce qu'en VIGIE_STORAGE=local la persistance écrit sous
# backend/ (backend/memory/persistence.py, _LOCAL_ROOT) : sans lui, l'exécution locale du conteneur
# — l'étape qui valide l'image avant d'y ajouter l'inconnue Firestore — échouerait sur les droits.
RUN useradd --create-home --uid 1000 veille && chown -R veille:veille /app
USER veille

EXPOSE 8080

# Par défaut, le service qui sert le digest. Le Job quotidien réutilise la même image en
# surchargeant la commande par : python -m backend.job
CMD ["sh", "-c", "uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
