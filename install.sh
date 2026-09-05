#!/bin/sh
# Install where-are-we on Debian or Ubuntu, with upgrades.
#
#   curl -fsSL https://ngavrish.github.io/where-are-we/install.sh | sh
#
# Adds the signed repository and installs the package: after this, the tool is
# upgraded by apt like anything else. Nothing here needs to be memorised, which
# is the whole reason the script exists.
set -eu

REPO_URL="https://ngavrish.github.io/where-are-we"

# Fedora, RHEL and their relatives take the same repository through dnf.
if command -v dnf >/dev/null 2>&1 || command -v yum >/dev/null 2>&1; then
  PM=$(command -v dnf || command -v yum)
  if [ "$(id -u)" = 0 ]; then SUDO=""; else SUDO="sudo"; fi
  $SUDO curl -fsSL "$REPO_URL/where-are-we.repo" -o /etc/yum.repos.d/where-are-we.repo
  $SUDO rpm --import "$REPO_URL/apt-key.asc"
  $SUDO "$PM" install -y where-are-we
  where-are-we --help | head -3
  exit 0
fi
KEYRING="/usr/share/keyrings/where-are-we.gpg"
LIST="/etc/apt/sources.list.d/where-are-we.list"

as_root() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi; }

command -v curl >/dev/null || { echo "curl is required"; exit 1; }
command -v gpg  >/dev/null || as_root apt-get install -y -qq gnupg

curl -fsSL "$REPO_URL/apt-key.asc" | as_root gpg --dearmor -o "$KEYRING"
echo "deb [signed-by=$KEYRING] $REPO_URL stable main" | as_root tee "$LIST" >/dev/null
as_root apt-get update -qq
as_root apt-get install -y where-are-we

echo
where-are-we --help | head -3
