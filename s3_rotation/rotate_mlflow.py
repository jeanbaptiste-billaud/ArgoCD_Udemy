#!/usr/bin/env python3
"""Rotation des cles S3 de MLflow (identite "mlflow" de SeaweedFS).

Ressources : workloads/mlflow/s3/ (generateurs, PushSecrets, ExternalSecrets).
  uv run s3_rotation/rotate_mlflow.py --check   # verifications seules, ne modifie rien
  uv run s3_rotation/rotate_mlflow.py           # rotation complete

Hors cluster, surcharger les URLs internes (NodePorts) :
  S3_ENDPOINT=http://<IP>:30333 MLFLOW_URL=http://<IP>:30500 uv run s3_rotation/rotate_mlflow.py --check
"""
import os

from pyESO.probe import status
from rotation import S3KeyRotation, main
from seaweedfs import SeaweedFS

MLFLOW_URL = os.environ.get("MLFLOW_URL", "http://mlflow.mlflow.svc:80")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", SeaweedFS.endpoint)


def mlflow_artifacts() -> str:
    """L'API d'artefacts de MLflow passe par S3 : 200 = MLflow lit le bucket avec sa paire."""
    return status(f"{MLFLOW_URL}/api/2.0/mlflow-artifacts/artifacts")


ROTATION = S3KeyRotation(
    namespace="mlflow",
    bucket="mlflow",
    official_secret="mlflow-s3-credentials",
    official_pushsecret="mlflow-s3-credentials-push",
    temp_pushsecrets=("mlflow-s3-temp-access-push", "mlflow-s3-temp-secret-push"),
    temp_externalsecret="mlflow-s3-temp",
    temp_secret="mlflow-s3-temp",
    deployment="mlflow",
    container="mlflow",
    backend=SeaweedFS(endpoint=S3_ENDPOINT),
    app_checks=(("MLflow API artefacts", mlflow_artifacts),),
)

if __name__ == "__main__":
    main(ROTATION)
