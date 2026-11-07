"""Entraine un modele California housing et l'enregistre dans le registre MLflow.

Le modele est enregistre sous le nom "california-housing" ; l'option --alias pose un alias
sur la nouvelle version (par defaut "dev" : c'est la version que le job de build package).

    MLFLOW_TRACKING_URI=http://<IP>:30500 uv run train.py --algo linear
    MLFLOW_TRACKING_URI=http://<IP>:30500 uv run train.py --algo gbr
"""

import argparse

import mlflow
from mlflow.models import infer_signature
from sklearn.datasets import fetch_california_housing
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

MODEL_NAME = "california-housing"

ALGOS = {
    "linear": lambda: make_pipeline(StandardScaler(), LinearRegression()),
    "gbr": lambda: GradientBoostingRegressor(n_estimators=300, max_depth=4, random_state=42),
}

# MLflow 3 serialise les modeles sklearn avec skops, qui refuse au chargement les types non
# declares sains. Les arbres (Tree) en font partie : on les accepte, le fichier vient de nous.
TRUSTED_TYPES = {
    "linear": None,
    "gbr": ["sklearn.tree._tree.Tree"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--algo", choices=ALGOS, required=True)
    parser.add_argument("--alias", default="dev", help="alias pose sur la nouvelle version ('' : aucun)")
    args = parser.parse_args()

    # Prix median en centaines de milliers de dollars, 8 variables numeriques par quartier
    X, y = fetch_california_housing(as_frame=True, return_X_y=True)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    mlflow.set_experiment(MODEL_NAME)
    with mlflow.start_run(run_name=args.algo):
        model = ALGOS[args.algo]().fit(X_train, y_train)
        y_pred = model.predict(X_test)
        mlflow.log_param("algo", args.algo)
        mlflow.log_metrics({
            "rmse": mean_squared_error(y_test, y_pred) ** 0.5,
            "r2": r2_score(y_test, y_pred),
        })
        info = mlflow.sklearn.log_model(
            model,
            name="model",
            signature=infer_signature(X_train, model.predict(X_train)),
            input_example=X_train.head(3),
            registered_model_name=MODEL_NAME,
            skops_trusted_types=TRUSTED_TYPES[args.algo],
        )

    client = mlflow.MlflowClient()
    version = info.registered_model_version
    client.set_model_version_tag(MODEL_NAME, version, "algo", args.algo)
    if args.alias:
        client.set_registered_model_alias(MODEL_NAME, args.alias, version)
    print(f"{MODEL_NAME} version {version} ({args.algo})" + (f" -> @{args.alias}" if args.alias else ""))


if __name__ == "__main__":
    main()
