"""Prepare le contexte de build de l'image du service, sans Docker.

    1. importe models:/california-housing@<alias> du registre MLflow dans le store BentoML ;
    2. construit le Bento a partir de service/ ;
    3. ecrit dans --out le contexte de build complet (Bento + modele + Dockerfile genere),
       exactement comme `bentoml containerize`, et le tag de l'image dans <out>/IMAGE_TAG.

Le contexte est ensuite construit et pousse par BuildKit (job bento-build, branche infra) :
    buildctl build --frontend dockerfile.v0 --local context=<out> \
      --local dockerfile=<out>/env/docker --output type=image,name=<image>:$(cat <out>/IMAGE_TAG),push=true

Tag de l'image : v<version MLflow du modele>-<commit du code>, ex. v3-1a2b3c4.
"""

import argparse
import shutil
from pathlib import Path

import bentoml
import mlflow
from bentoml._internal.container import construct_containerfile  # utilise par `bentoml containerize`

MODEL_NAME = "california-housing"
SERVICE_DIR = Path(__file__).parent / "service"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--alias", default="dev", help="alias MLflow de la version a packager")
    parser.add_argument("--out", required=True, type=Path, help="dossier du contexte de build (vide)")
    parser.add_argument("--code-version", required=True, help="commit du code (suffixe du tag)")
    args = parser.parse_args()

    version = mlflow.MlflowClient().get_model_version_by_alias(MODEL_NAME, args.alias)
    print(f"modele : {MODEL_NAME} v{version.version} (@{args.alias}, algo {version.tags.get('algo', '?')})")

    # Metadonnees relues par le service (etiquette "california-housing v3 (gbr)")
    bentoml.mlflow.import_model(
        MODEL_NAME,
        f"models:/{MODEL_NAME}/{version.version}",
        metadata={
            "mlflow_version": version.version,
            "mlflow_run_id": version.run_id,
            "algo": version.tags.get("algo", "?"),
        },
    )
    tag = f"v{version.version}-{args.code_version}"
    bento = bentoml.bentos.build_bentofile(
        str(SERVICE_DIR / "bentofile.yaml"),
        build_ctx=str(SERVICE_DIR),
        labels={"model-version": version.version, "code-version": args.code_version},
    )
    print(f"bento : {bento.tag}")

    with construct_containerfile(bento) as (context, _dockerfile):
        shutil.copytree(context, args.out, dirs_exist_ok=True)
    (args.out / "IMAGE_TAG").write_text(tag)
    print(f"contexte de build : {args.out}, tag {tag}")


if __name__ == "__main__":
    main()
