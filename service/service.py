"""Service BentoML : prix median des logements d'un quartier californien.

Le modele (flavor MLflow) est embarque dans l'image par le job de build : l'API ne depend
pas de MLflow a l'execution. Si PGHOST est defini, chaque prediction est journalisee dans
PostgreSQL (variables libpq PGHOST, PGDATABASE, PGUSER, PGPASSWORD).
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import bentoml
import pandas as pd
import psycopg
from pydantic import BaseModel, Field

MODEL_NAME = "california-housing"

logger = logging.getLogger("bentoml.predict")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS predictions (
    id          bigserial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    model       text NOT NULL,
    features    jsonb NOT NULL,
    price       double precision NOT NULL
)
"""


class House(BaseModel):
    """Un quartier (block group) du recensement californien de 1990."""

    MedInc: float = Field(description="Revenu median (dizaines de milliers de $)", examples=[8.3])
    HouseAge: float = Field(description="Age median des logements (annees)", examples=[41.0])
    AveRooms: float = Field(description="Nombre moyen de pieces par logement", examples=[6.98])
    AveBedrms: float = Field(description="Nombre moyen de chambres par logement", examples=[1.02])
    Population: float = Field(description="Population du quartier", examples=[322.0])
    AveOccup: float = Field(description="Nombre moyen d'occupants par logement", examples=[2.56])
    Latitude: float = Field(examples=[37.88])
    Longitude: float = Field(examples=[-122.23])


class Prediction(BaseModel):
    price: float = Field(description="Prix median estime (centaines de milliers de $)")
    model: str = Field(description="Modele qui a produit la prediction")


class Logged(BaseModel):
    created_at: datetime
    model: str
    features: dict[str, float]
    price: float


@bentoml.service(traffic={"timeout": 10})
class Predict:
    # Resolu au build : le modele importe depuis MLflow est copie dans le Bento
    model_ref = bentoml.models.BentoModel(f"{MODEL_NAME}:latest")

    def __init__(self) -> None:
        # Dans le service, model_ref est deja resolu en bentoml.Model (store du Bento)
        self.model = bentoml.mlflow.load_model(self.model_ref)
        meta = self.model_ref.info.metadata
        # ex. "california-housing v2 (gbr)"
        self.model_label = f"{MODEL_NAME} v{meta.get('mlflow_version', '?')} ({meta.get('algo', '?')})"
        self.environment = os.environ.get("ENVIRONMENT", "local")
        self.db_enabled = bool(os.environ.get("PGHOST"))
        # Ecritures hors du chemin de la requete : une base lente ou coupee ne retarde pas
        # les predictions
        self.db_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db-log")
        logger.info("modele %s, environnement %s, journalisation %s",
                    self.model_label, self.environment, "PostgreSQL" if self.db_enabled else "desactivee")
        if self.db_enabled:
            with psycopg.connect(autocommit=True, connect_timeout=5) as conn:
                conn.execute(CREATE_TABLE)

    @bentoml.api
    def predict(self, houses: list[House]) -> list[Prediction]:
        features = [h.model_dump() for h in houses]
        prices = [float(p) for p in self.model.predict(pd.DataFrame(features))]
        if self.db_enabled:
            self.db_writer.submit(self._log, features, prices)
        return [Prediction(price=p, model=self.model_label) for p in prices]

    @bentoml.api
    def history(self, limit: int = 10) -> list[Logged]:
        """Dernieres predictions journalisees (vide si la journalisation est desactivee)."""
        if not self.db_enabled:
            return []
        with psycopg.connect(connect_timeout=5) as conn:
            rows = conn.execute(
                "SELECT created_at, model, features, price FROM predictions ORDER BY id DESC LIMIT %s",
                (min(limit, 100),),
            ).fetchall()
        return [Logged(created_at=r[0], model=r[1], features=r[2], price=r[3]) for r in rows]

    @bentoml.api
    def info(self) -> dict[str, str]:
        return {"model": self.model_label, "environment": self.environment}

    def _log(self, features: list[dict], prices: list[float]) -> None:
        """Journalisation au mieux : une erreur est loguee, la prediction est deja rendue."""
        try:
            with psycopg.connect(autocommit=True, connect_timeout=3) as conn:
                conn.cursor().executemany(
                    "INSERT INTO predictions (model, features, price) VALUES (%s, %s, %s)",
                    [(self.model_label, psycopg.types.json.Jsonb(f), p) for f, p in zip(features, prices)],
                )
        except psycopg.Error as e:
            logger.warning("journalisation impossible : %s", e)
