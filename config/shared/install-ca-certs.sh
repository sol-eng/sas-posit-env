#!/bin/bash
# Adds custom CA certificates (e.g. an internal CA that signed SAS Viya's TLS
# certificate) to the container's system trust store. Run as root at startup,
# before the product starts, by pwb-init.sh (Workbench) and the connect
# service's entrypoint (Connect).
#
# Source: /etc/posit-team/ca-certs, a read-only bind mount of ./certs.
# Every *.crt and *.pem file there is used; PEM files may hold several
# certificates, and DER-encoded single certificates are converted. If the
# folder is empty, this is a no-op.
#
# Covers anything that uses the system store (/etc/ssl/certs/ca-certificates.crt):
# Workbench's and Connect's token exchange with SAS Logon, curl, R, Python's
# ssl module. Python requests and Node.js are pointed at the same bundle via
# REQUESTS_CA_BUNDLE and NODE_EXTRA_CA_CERTS (see docker-compose.yml and
# config/workbench/launcher-env).

set -euo pipefail

log() { echo "[ca-certs] $*" >&2; }

src=/etc/posit-team/ca-certs
dest=/usr/local/share/ca-certificates/posit-team

shopt -s nullglob
files=("$src"/*.crt "$src"/*.pem)

if [ ${#files[@]} -eq 0 ]; then
  # Undo certificates from an earlier start (container restarted, not recreated).
  if [ -d "$dest" ]; then
    rm -rf "$dest"
    update-ca-certificates --fresh >/dev/null
    log "Removed previously installed custom CA certificates"
  fi
  exit 0
fi

rm -rf "$dest"
install -d -m 0755 "$dest"
count=0
for f in "${files[@]}"; do
  base="$(basename "${f%.*}")"
  if grep -q -- '-----BEGIN CERTIFICATE-----' "$f"; then
    # Split into one certificate per file; update-ca-certificates expects that.
    n=0
    while IFS= read -r line; do
      case "$line" in
        *'-----BEGIN CERTIFICATE-----'*) n=$((n + 1)); out="${dest}/${base}-${n}.crt"; : > "$out" ;;
      esac
      [ "$n" -gt 0 ] && printf '%s\n' "$line" >> "$out"
    done < <(tr -d '\r' < "$f")
  else
    n=1
    out="${dest}/${base}-1.crt"
    if ! openssl x509 -inform DER -in "$f" -out "$out" 2>/dev/null; then
      log "ERROR: ${f} is neither a PEM nor a DER certificate"
      exit 1
    fi
  fi
  for ((i = 1; i <= n; i++)); do
    if ! subject="$(openssl x509 -noout -subject -in "${dest}/${base}-${i}.crt" 2>/dev/null)"; then
      log "ERROR: certificate ${i} in ${f} is not valid"
      exit 1
    fi
    log "Adding ${subject} (from $(basename "$f"))"
  done
  count=$((count + n))
done

update-ca-certificates --fresh >/dev/null
log "Installed ${count} custom CA certificate(s) into the system trust store"
