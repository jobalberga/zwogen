#!/usr/bin/env python3
"""Run in your own Cloud Shell. Default is instructions only; --apply provisions."""

import argparse
import datetime
import getpass
import json
import re
import secrets
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra" / "gcp"


def run(args, *, capture=False, input_text=None):
    result = subprocess.run(args, cwd=ROOT, text=True, input=input_text, check=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if input_text is not None else None)
    return result.stdout.strip() if capture else ""


def seed_secrets(project):
    for name in ("web", "vw"):
        resource = "passat-" + name
        versions = run(["gcloud", "secrets", "versions", "list", resource, "--project", project,
                        "--filter=state=ENABLED", "--format=value(name)", "--limit=1"], capture=True)
        if versions:
            print(resource + ": bestaande configuratie behouden.")
            continue
        if name == "web":
            password = getpass.getpass("Nieuw app-wachtwoord (minimaal 12 tekens): ")
            if len(password) < 12 or password != getpass.getpass("Herhaal app-wachtwoord: "):
                raise ValueError("App-wachtwoord te kort of niet gelijk. Er is niets opgeslagen.")
            value = {"password": password, "session_secret": secrets.token_urlsafe(48)}
        else:
            username = input("VW-e-mailadres: ").strip()
            password = getpass.getpass("VW-wachtwoord (verborgen invoer): ")
            vin = input("Chassisnummer Passat (VIN): ").strip().upper()
            if not username or not password or not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
                raise ValueError("Onvolledige VW-configuratie of ongeldig chassisnummer.")
            value = {"username": username, "password": password, "vin": vin}
        # Values go through stdin, never CLI arguments, files, Terraform state or logs.
        run(["gcloud", "secrets", "versions", "add", resource, "--project", project, "--data-file=-"],
            capture=True, input_text=json.dumps(value))
        print(resource + ": veilig opgeslagen in Secret Manager.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id")
    parser.add_argument("--region", default="europe-west1")
    parser.add_argument("--apply", action="store_true", help="Maak resources aan; gebruikskosten zijn mogelijk.")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.project_id):
        parser.error("Gebruik de project-ID, niet de projectnaam of het projectnummer.")
    if not args.apply:
        print("Dit is een voorbereiding; er is niets aangemaakt.")
        print("Met --apply: maak opslag, geheimen en accounts aan; bouw een image; start website en private laadwerker.")
        print("Er komen ook een takenwachtrij en één herstelcontrole per drie minuten. Gebruikskosten zijn mogelijk.")
        print("Lees GCP.md, controleer tarieven en stel een budgetmelding in vóór je --apply gebruikt.")
        return
    for tool in ("gcloud", "terraform"):
        if not shutil.which(tool):
            raise ValueError(tool + " ontbreekt. Gebruik Google Cloud Shell of installeer het eerst.")
    billing = run(["gcloud", "billing", "projects", "describe", args.project_id,
                   "--format=value(billingEnabled)"], capture=True)
    if billing.lower() != "true":
        raise ValueError("Schakel eerst facturering in voor dit project.")
    run(["gcloud", "services", "enable", "serviceusage.googleapis.com", "cloudresourcemanager.googleapis.com",
         "iam.googleapis.com", "--project", args.project_id])
    config_path = INFRA / "deployment.auto.tfvars.json"
    config = {"project_id": args.project_id, "region": args.region, "deploy_services": False}
    if config_path.exists():
        existing = json.loads(config_path.read_text())
        if existing.get("project_id") != args.project_id or existing.get("region") != args.region:
            raise ValueError("Deze checkout heeft al een andere installatie. Bewaar de bestaande Terraform-state.")
        config.update(existing)  # Keep existing services running during an update.
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    tf = ["terraform", "-chdir=" + str(INFRA)]
    run(tf + ["init", "-input=false"])
    def apply():
        plan = INFRA / "deployment.tfplan"
        run(tf + ["plan", "-input=false", "-out=" + str(plan)])
        run(tf + ["apply", "-input=false", str(plan)])
        plan.unlink(missing_ok=True)
    apply()
    seed_secrets(args.project_id)
    outputs = json.loads(run(tf + ["output", "-json"], capture=True))
    repo = outputs["image_repository"]["value"]
    bucket = outputs["build_bucket"]["value"]
    builder = outputs["builder_account"]["value"]
    tag = repo + ":deploy-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    run(["gcloud", "builds", "submit", str(ROOT), "--project", args.project_id, "--tag", tag,
         "--service-account=projects/" + args.project_id + "/serviceAccounts/" + builder,
         "--gcs-source-staging-dir=gs://" + bucket + "/source", "--gcs-log-dir=gs://" + bucket + "/logs"])
    metadata = json.loads(run(["gcloud", "artifacts", "docker", "images", "describe", tag,
                               "--project", args.project_id, "--format=json"], capture=True))
    digest = metadata.get("image_summary", {}).get("digest", "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Geen geldig image-digest ontvangen; services worden niet bijgewerkt.")
    config.update(image=repo + "@" + digest, deploy_services=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    apply()
    print("Website:", run(tf + ["output", "-raw", "website_url"], capture=True))
    print("Controleer echte VW-status, pauzeren en de eerste geplande start vóór je hierop vertrouwt.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        raise SystemExit("Cloud-opdracht mislukt. Controleer rechten, facturering en de laatste opdracht; voer daarna opnieuw uit. Geheime invoer wordt niet getoond.") from None
    except ValueError as error:
        raise SystemExit(str(error)) from None
