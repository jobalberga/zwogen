#!/usr/bin/env bash
# Install Terraform from HashiCorp's signed APT repository in Google Cloud Shell.
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

if python3 -c 'import runpy; runpy.run_path("tools/deploy_gcp.py")["check_tools"]()' 2>/dev/null; then
    exit 0
fi

if ! command -v gcloud >/dev/null; then
    echo "Voer dit script uit in Google Cloud Shell."
    exit 1
fi

. /etc/os-release
terraform_codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
if [ -z "$terraform_codename" ]; then
    echo "Linux-versie niet herkend. Installeer Terraform via https://developer.hashicorp.com/terraform/install"
    exit 1
fi

echo "Terraform installeren via HashiCorp's ondertekende pakketbron..."
curl --fail --silent --show-error --location https://apt.releases.hashicorp.com/gpg \
    | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
printf 'deb [arch=%s signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com %s main\n' \
    "$(dpkg --print-architecture)" "$terraform_codename" \
    | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt-get update
sudo apt-get install -y terraform

# Google's placeholder can precede the installed executable in PATH. Keep a
# verified binary in the user's home directory for future Cloud Shell sessions.
/usr/bin/terraform version -json
mkdir -p "$HOME/.local/bin"
install -m 755 /usr/bin/terraform "$HOME/.local/bin/terraform"
echo 'Terraform is geïnstalleerd. Start de installatie met:'
echo 'PATH="$HOME/.local/bin:$PATH" python3 tools/deploy_gcp.py JOUW-PROJECT-ID --apply'
