#!/bin/bash
# Pre-start hook for the Posit Workbench container.
#
# Runs as root before the image's own entrypoint (/usr/local/bin/entrypoint.sh),
# then hands over to it unchanged. It does two things:
#
#   1. Keeps the Job Launcher keys stable across container recreation.
#      (secure-cookie-key and session-rpc-key already live in the persistent
#      /var/lib/rstudio-server volume; launcher.pem/.pub live in /etc/rstudio,
#      which is not persistent.)
#
#   2. Generates /etc/rstudio/oauth-clients.conf for the SAS Viya OAuth
#      integration from environment variables:
#
#        VIYA_HOSTNAME                 e.g. viya.example.com (https:// prefix is optional)
#        WORKBENCH_VIYA_CLIENT_ID      SAS Logon client ID, e.g. posit-workbench
#        WORKBENCH_VIYA_CLIENT_SECRET  SAS Logon client secret (written encrypted
#                                      with rstudio-server encrypt-password)
#        VIYA_SCOPES                   optional, default: openid,sas-compute.user_impersonation
#        VIYA_OAUTH_SECTION            optional, default: sas-viya
#        VIYA_OAUTH_NAME               optional, default: SAS Viya
#
#      If neither WORKBENCH_VIYA_CLIENT_ID nor WORKBENCH_VIYA_CLIENT_SECRET is
#      set, the integration is skipped. If only some values are set, the
#      container fails fast.
#
#   3. Adds a default Positron SAS extension connection profile
#      ("SAS.connectionProfiles") to /etc/rstudio/positron-user-settings.json
#      when VIYA_HOSTNAME is set:
#
#        POSITRON_SAS_CLIENT_ID      optional SAS Logon client ID for the
#                                    extension's own sign-in, e.g. vscode-positron
#        POSITRON_SAS_CLIENT_SECRET  optional, default empty
#        POSITRON_SAS_PROFILE_NAME   optional, default: viya
#
# Reference:
#   https://posit-dev.github.io/positron-sas-extension/Workbench/Code/viyaOauth

set -euo pipefail

log() { echo "[pwb-init] $*" >&2; }

STATE_DIR=/var/lib/rstudio-server
OAUTH_CONF=/etc/rstudio/oauth-clients.conf
POSITRON_SETTINGS=/etc/rstudio/positron-user-settings.json

# --- 0. Optional custom CA certificates (./certs) ---------------------------
bash /usr/local/bin/install-ca-certs.sh

# --- 1. Persistent launcher keys --------------------------------------------
key_dir="${STATE_DIR}/launcher-keys"
install -d -m 0700 -o root -g root "$key_dir"
if [ ! -s "${key_dir}/launcher.pem" ]; then
  log "Generating launcher key pair in ${key_dir}"
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
    -out "${key_dir}/launcher.pem" 2>/dev/null
  openssl rsa -in "${key_dir}/launcher.pem" -pubout \
    -out "${key_dir}/launcher.pub" 2>/dev/null
fi
install -m 0600 -o root -g root "${key_dir}/launcher.pem" /etc/rstudio/launcher.pem
install -m 0644 -o root -g root "${key_dir}/launcher.pub" /etc/rstudio/launcher.pub

# --- 2. SAS Viya OAuth client -----------------------------------------------
viya_host="${VIYA_HOSTNAME:-}"
viya_host="${viya_host#https://}"
viya_host="${viya_host#http://}"
viya_host="${viya_host%%/*}"
client_id="${WORKBENCH_VIYA_CLIENT_ID:-}"
client_secret="${WORKBENCH_VIYA_CLIENT_SECRET:-}"

# VIYA_HOSTNAME is shared with Connect, so only Workbench's own client
# settings decide whether the integration is wanted.
if [ -z "$client_id" ] && [ -z "$client_secret" ]; then
  log "WORKBENCH_VIYA_CLIENT_ID/SECRET not set; skipping SAS Viya OAuth configuration"
  rm -f "$OAUTH_CONF"
else
  missing=()
  [ -n "$viya_host" ]     || missing+=(VIYA_HOSTNAME)
  [ -n "$client_id" ]     || missing+=(WORKBENCH_VIYA_CLIENT_ID)
  [ -n "$client_secret" ] || missing+=(WORKBENCH_VIYA_CLIENT_SECRET)
  if [ ${#missing[@]} -gt 0 ]; then
    log "ERROR: SAS Viya OAuth is partially configured; missing: ${missing[*]}"
    exit 1
  fi

  # Encrypt the client secret with secure-cookie-key (persistent volume).
  # On a fresh volume the key doesn't exist yet, so create it first;
  # otherwise rserver would generate a different one and fail to decrypt.
  cookie_key="${STATE_DIR}/secure-cookie-key"
  if [ ! -s "$cookie_key" ]; then
    log "Generating ${cookie_key}"
    install -m 0600 -o root -g rstudio-server /dev/null "$cookie_key"
    openssl rand -hex 32 > "$cookie_key"
  fi
  enc_secret="$(printf '%s\n' "$client_secret" \
    | rstudio-server encrypt-password 2>/dev/null | tail -n 1)"
  if [ -z "$enc_secret" ]; then
    log "ERROR: rstudio-server encrypt-password failed"
    exit 1
  fi

  section="${VIYA_OAUTH_SECTION:-sas-viya}"
  name="${VIYA_OAUTH_NAME:-SAS Viya}"
  scopes="${VIYA_SCOPES:-openid,sas-compute.user_impersonation}"

  tmp="$(mktemp /etc/rstudio/.oauth-clients.XXXXXX)"
  {
    printf '[%s]\n' "$section"
    printf 'name=%s\n' "$name"
    printf 'client-id=%s\n' "$client_id"
    printf 'client-secret=%s\n' "$enc_secret"
    printf 'authorize-url=https://%s/SASLogon/oauth/authorize\n' "$viya_host"
    printf 'token-url=https://%s/SASLogon/oauth/token\n' "$viya_host"
    printf 'scopes=%s\n' "$scopes"
  } > "$tmp"
  chown rstudio-server:rstudio-server "$tmp"
  chmod 0600 "$tmp"
  mv -f "$tmp" "$OAUTH_CONF"
  log "Wrote ${OAUTH_CONF} ([${section}] -> https://${viya_host}/SASLogon)"
fi

# --- 3. Default Positron SAS connection profile -----------------------------
# Workbench merges this template into each user's ~/.positron-server settings
# at session start without overriding keys the user already has, so the
# profile is a default that users can edit (later template changes don't
# reach users who already got it). Re-running this is idempotent: the key is
# replaced, or removed when VIYA_HOSTNAME is unset.
VIYA_HOST="$viya_host" \
SAS_PROFILE_NAME="${POSITRON_SAS_PROFILE_NAME:-viya}" \
SAS_CLIENT_ID="${POSITRON_SAS_CLIENT_ID:-}" \
SAS_CLIENT_SECRET="${POSITRON_SAS_CLIENT_SECRET:-}" \
/usr/bin/python3 -I - "$POSITRON_SETTINGS" <<'PY'
import json, os, sys, tempfile

path = sys.argv[1]
with open(path) as f:
    settings = json.load(f)

host = os.environ["VIYA_HOST"]
key = "SAS.connectionProfiles"
if host:
    profile = {"connectionType": "rest", "endpoint": f"https://{host}"}
    if os.environ["SAS_CLIENT_ID"]:
        profile["clientId"] = os.environ["SAS_CLIENT_ID"]
        profile["clientSecret"] = os.environ["SAS_CLIENT_SECRET"]
    name = os.environ["SAS_PROFILE_NAME"]
    settings[key] = {"activeProfile": name, "profiles": {name: profile}}
    msg = f"Positron SAS profile '{name}' -> https://{host}"
else:
    settings.pop(key, None)
    msg = "VIYA_HOSTNAME not set; no default Positron SAS profile"

fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".positron-user-settings.")
with os.fdopen(fd, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o644)
os.replace(tmp, path)
print(f"[pwb-init] {msg}", file=sys.stderr)
PY

# Keep the secrets out of supervisord, rserver and user sessions.
unset WORKBENCH_VIYA_CLIENT_SECRET POSITRON_SAS_CLIENT_SECRET

exec /usr/local/bin/entrypoint.sh "$@"
