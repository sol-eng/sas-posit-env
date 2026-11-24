#!/usr/bin/env python3
"""One-shot provisioning for Posit Connect (run by the connect-init service).

Connect stores OAuth integrations in its database, not in a config file, so
they have to be created through the Connect Server API. This script:

  1. Gets an administrator API key:
       - CONNECT_INIT_API_KEY, if set (use this if Connect already has users), else
       - the key saved by a previous run in /var/lib/connect-bootstrap/api-key, else
       - a new key from Connect's bootstrap endpoint (only works while Connect
         has no users; it creates the service user __bootstrap_admin__).
  2. When bootstrapping, also creates a password-login administrator
     (CONNECT_ADMIN_USER, default "admin"). With password authentication only
     the first registered account becomes an admin, and the bootstrap user
     takes that slot. If CONNECT_ADMIN_PASSWORD is unset, a random password is
     generated and saved to /var/lib/connect-bootstrap/admin-password.
  3. Creates the publisher CONNECT_PUBLISHER_USER/CONNECT_PUBLISHER_PASSWORD
     (compose: posit / POSIT_USER_PASSWORD, same login as Workbench), or changes an
     existing viewer with that name to publisher. Skipped if the user is unset.
  4. Creates the "SAS Viya (Viewer)" OAuth integration, or updates its config
     if it already exists, from:
       VIYA_HOSTNAME               e.g. viya.example.com
       CONNECT_VIYA_CLIENT_ID      SAS Logon client for Connect, e.g. posit-connect
       CONNECT_VIYA_CLIENT_SECRET
       VIYA_SCOPES                 optional, comma-separated,
                                   default: openid,sas-compute.user_impersonation
     If neither CONNECT_VIYA_CLIENT_ID nor CONNECT_VIYA_CLIENT_SECRET is set,
     this step is skipped.

Safe to re-run. Reference:
  https://posit-dev.github.io/positron-sas-extension/Workbench/Code/viyaOauth
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONNECT_URL = os.environ.get("CONNECT_URL", "http://connect:3939").rstrip("/")
STATE_DIR = Path("/var/lib/connect-bootstrap")
BOOTSTRAP_KEY_FILE = STATE_DIR / "bootstrap.key"
API_KEY_FILE = STATE_DIR / "api-key"
ADMIN_PASSWORD_FILE = STATE_DIR / "admin-password"
INTEGRATION_NAME = "SAS Viya (Viewer)"


def log(msg):
    print(f"[connect-init] {msg}", file=sys.stderr, flush=True)


def fail(msg):
    log(f"ERROR: {msg}")
    sys.exit(1)


def api(method, path, api_key=None, body=None, authorization=None):
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Key {api_key}"
    if authorization:
        headers["Authorization"] = authorization
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        CONNECT_URL + path, data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw)
        except ValueError:
            return err.code, raw.decode(errors="replace")


def write_secret(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value + "\n")


def wait_for_connect():
    for _ in range(60):
        try:
            with urllib.request.urlopen(CONNECT_URL + "/__ping__", timeout=5):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(2)
    fail(f"Connect did not become reachable at {CONNECT_URL}")


def bootstrap_jwt():
    """HS256 JWT in the format rsconnect-python uses for `rsconnect bootstrap`."""
    key = base64.b64decode(BOOTSTRAP_KEY_FILE.read_text().strip())

    def b64(data):
        return base64.urlsafe_b64encode(data).rstrip(b"=")

    now = int(time.time())
    claims = {
        "iss": "rsconnect-python",
        "aud": "rsconnect",
        "iat": now,
        "exp": now + 900,
        "scope": "bootstrap",
    }
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps(claims).encode())
    signature = b64(hmac.new(key, header + b"." + payload, hashlib.sha256).digest())
    return (header + b"." + payload + b"." + signature).decode()


def key_is_valid(api_key):
    status, _ = api("GET", "/__api__/v1/user", api_key)
    return status == 200


def get_api_key():
    """Returns (api_key, came_from_bootstrap)."""
    explicit = os.environ.get("CONNECT_INIT_API_KEY", "").strip()
    if explicit:
        if not key_is_valid(explicit):
            fail("CONNECT_INIT_API_KEY was rejected by Connect")
        log("Using CONNECT_INIT_API_KEY")
        return explicit, False

    if API_KEY_FILE.exists():
        saved = API_KEY_FILE.read_text().strip()
        if key_is_valid(saved):
            log("Using API key saved by a previous run")
            return saved, True
        log("Saved API key is no longer valid; trying to bootstrap again")

    if not BOOTSTRAP_KEY_FILE.exists():
        fail(f"{BOOTSTRAP_KEY_FILE} not found; is Connect's [Bootstrap] section configured?")

    status, payload = api(
        "POST",
        "/__api__/v1/bootstrap",
        authorization=f"Connect-Bootstrap {bootstrap_jwt()}",
    )
    if status == 200 and isinstance(payload, dict) and payload.get("api_key"):
        write_secret(API_KEY_FILE, payload["api_key"])
        log("Bootstrapped Connect and saved the admin API key")
        return payload["api_key"], True
    if status == 403:
        fail(
            "Connect already has users, so it can't be bootstrapped. Create an "
            "API key for an administrator and set CONNECT_INIT_API_KEY in .env."
        )
    fail(f"Bootstrap failed: HTTP {status}: {payload}")


def ensure_admin_user(api_key):
    username = os.environ.get("CONNECT_ADMIN_USER", "").strip() or "admin"
    status, payload = api("GET", f"/__api__/v1/users?prefix={username}", api_key)
    if status != 200:
        fail(f"Listing users failed: HTTP {status}: {payload}")
    if any(u.get("username") == username for u in payload.get("results", [])):
        log(f"Admin user '{username}' already exists")
        return

    password = os.environ.get("CONNECT_ADMIN_PASSWORD", "")
    generated = not password
    if generated:
        password = secrets.token_urlsafe(18)

    status, payload = api(
        "POST",
        "/__api__/v1/users",
        api_key,
        {
            "username": username,
            "password": password,
            "email": f"{username}@localhost",
            "first_name": "Connect",
            "last_name": "Admin",
            "user_role": "administrator",
            "user_must_set_password": False,
        },
    )
    if status != 200:
        fail(f"Creating admin user '{username}' failed: HTTP {status}: {payload}")
    if generated:
        write_secret(ADMIN_PASSWORD_FILE, password)
        log(
            f"Created admin user '{username}' with a generated password; read it with: "
            f"docker compose exec connect cat {ADMIN_PASSWORD_FILE}"
        )
    else:
        log(f"Created admin user '{username}'")


def ensure_publisher_user(api_key):
    """Creates the publisher (posit, same login as Workbench), or
    promotes an existing viewer to publisher. Never resets a password."""
    username = os.environ.get("CONNECT_PUBLISHER_USER", "").strip()
    if not username:
        log("CONNECT_PUBLISHER_USER not set; skipping the publisher user")
        return
    status, payload = api("GET", f"/__api__/v1/users?prefix={username}", api_key)
    if status != 200:
        fail(f"Listing users failed: HTTP {status}: {payload}")
    user = next((u for u in payload.get("results", []) if u.get("username") == username), None)

    if user is None:
        password = os.environ.get("CONNECT_PUBLISHER_PASSWORD", "")
        if not password:
            fail("CONNECT_PUBLISHER_PASSWORD is empty")
        status, payload = api(
            "POST",
            "/__api__/v1/users",
            api_key,
            {
                "username": username,
                "password": password,
                "email": f"{username}@localhost",
                "first_name": username.capitalize(),
                "last_name": "User",
                "user_role": "publisher",
                "user_must_set_password": False,
            },
        )
        if status != 200:
            fail(f"Creating publisher user '{username}' failed: HTTP {status}: {payload}")
        log(f"Created publisher user '{username}'")
    elif user.get("user_role") == "viewer":
        status, payload = api(
            "PATCH", f"/__api__/v1/users/{user['guid']}", api_key, {"user_role": "publisher"}
        )
        if status != 200:
            fail(f"Making '{username}' a publisher failed: HTTP {status}: {payload}")
        log(f"Changed user '{username}' from viewer to publisher")
    else:
        log(f"User '{username}' already exists ({user.get('user_role')})")


def ensure_viya_integration(api_key):
    host = os.environ.get("VIYA_HOSTNAME", "").strip()
    host = host.removeprefix("https://").removeprefix("http://").split("/")[0]
    client_id = os.environ.get("CONNECT_VIYA_CLIENT_ID", "").strip()
    client_secret = os.environ.get("CONNECT_VIYA_CLIENT_SECRET", "")

    values = {
        "VIYA_HOSTNAME": host,
        "CONNECT_VIYA_CLIENT_ID": client_id,
        "CONNECT_VIYA_CLIENT_SECRET": client_secret,
    }
    # VIYA_HOSTNAME is shared with Workbench, so only this product's own
    # client settings decide whether the integration is wanted.
    if not client_id and not client_secret:
        log("CONNECT_VIYA_CLIENT_ID/SECRET not set; skipping the SAS Viya integration")
        return
    missing = [name for name, value in values.items() if not value]
    if missing:
        fail(f"SAS Viya integration is partially configured; missing: {' '.join(missing)}")

    scopes = os.environ.get("VIYA_SCOPES", "").strip() or "openid,sas-compute.user_impersonation"
    config = {
        "auth_type": "Viewer",
        "auth_mode": "Confidential",
        "use_pkce": True,
        "authorization_uri": f"https://{host}/SASLogon/oauth/authorize",
        "token_uri": f"https://{host}/SASLogon/oauth/token",
        "client_id": client_id,
        "client_secret": client_secret,
        # Connect wants space-separated scopes (Workbench uses commas).
        "scopes": " ".join(s.strip() for s in scopes.split(",") if s.strip()),
        "token_endpoint_auth_method": "client_secret_post",
    }

    status, payload = api("GET", "/__api__/v1/oauth/integrations", api_key)
    if status != 200:
        fail(f"Listing OAuth integrations failed: HTTP {status}: {payload}")
    existing = [i for i in payload if i.get("name") == INTEGRATION_NAME]

    if existing:
        guid = existing[0]["guid"]
        status, payload = api(
            "PATCH", f"/__api__/v1/oauth/integrations/{guid}", api_key, {"config": config}
        )
        action = "Updated"
    else:
        status, payload = api(
            "POST",
            "/__api__/v1/oauth/integrations",
            api_key,
            {"name": INTEGRATION_NAME, "template": "custom", "config": config},
        )
        action = "Created"
    if status != 200:
        fail(f"Saving the '{INTEGRATION_NAME}' integration failed: HTTP {status}: {payload}")
    log(f"{action} OAuth integration '{INTEGRATION_NAME}' (guid {payload['guid']}) -> https://{host}/SASLogon")


def main():
    wait_for_connect()
    api_key, from_bootstrap = get_api_key()
    if from_bootstrap:
        ensure_admin_user(api_key)
    ensure_publisher_user(api_key)
    ensure_viya_integration(api_key)
    log("Done")


if __name__ == "__main__":
    main()
