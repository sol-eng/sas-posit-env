# Posit Team with SAS Viya in Docker Compose

This repository runs a local Posit Team environment with Docker Compose. It connects Posit Workbench and Posit Connect to SAS Viya through OAuth, so Positron sessions and published content can use SAS Viya with your own SAS identity.

| Service | URL | Sign in |
|---------|-----|---------|
| Workbench | <http://localhost:8787> | User `posit`, password `positsas2026` |
| Connect | <http://localhost:3939> | User `posit` (publisher), password `positsas2026`, or user `admin`, password from [Sign in to Connect](#sign-in-to-connect) |
| Posit Package Manager | <http://localhost:4242> | No sign-in |

The environment configures the following:

- Workbench uses a SAS Viya OAuth integration, so users sign in to SAS Viya once from the Workbench home page.
- Every Positron session gets the [Positron SAS extension](https://posit-dev.github.io/positron-sas-extension/) and a default SAS Viya connection profile.
- Connect has a SAS Viya OAuth integration named `SAS Viya (Viewer)` for published content.
- Workbench sessions and Connect install R and Python packages from the local Package Manager.
- Workbench sessions publish to the local Connect server by default.

The same files work on macOS, Linux, and Windows with Windows Subsystem for Linux (WSL).

## Requirements

All platforms need the following:

- Docker with Docker Compose version 2
- At least 8 GB of memory for Docker
- License files for Workbench, Connect, and Package Manager
- Internet access from the containers, to pull images and install extensions and packages
- For SAS Viya integration: SAS Logon OAuth clients, which a SAS Viya administrator registers

The container images exist only for the x86-64 (amd64) architecture.

### macOS

Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) and set its memory limit to 8 GB or more.

On Apple silicon, Docker emulates the amd64 images. The first start takes several minutes, and the services respond more slowly than on x86-64 hardware.

### Linux

Install [Docker Engine](https://docs.docker.com/engine/install/) and the [Docker Compose plugin](https://docs.docker.com/compose/install/linux/). Confirm that `docker compose version` reports version 2.

### Windows with WSL

Use WSL 2 with a Linux distribution such as Ubuntu. Choose one of the following Docker setups:

- Use Docker Desktop for Windows with the WSL 2 backend, and turn on integration for your distribution in **Settings > Resources > WSL Integration**.
- Install Docker Engine and the Docker Compose plugin inside the WSL distribution, as on Linux.

Run every command in this README inside the WSL distribution, not in PowerShell or the Command Prompt. Open the service URLs in your Windows browser. WSL forwards `localhost` to the containers.

WSL uses half of the Windows memory by default. If that is less than 8 GB, raise the limit in `%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=8GB
```

Run `wsl --shutdown` in PowerShell to apply the change, then open the distribution again.

> [!IMPORTANT]
> Keep the repository in the WSL file system, for example `~/sas-posit-env`, not under `/mnt/c`. Docker mounts files from the Windows drive slowly and without Linux file permissions.

## Set up the environment

### Get the repository

Clone the repository. On Windows, run this inside WSL:

```bash
git clone https://github.com/sol-eng/sas-posit-env.git ~/sas-posit-env
cd ~/sas-posit-env
```

The `.gitattributes` file keeps Linux line endings in every checkout, including Git for Windows checkouts. The containers fail to start if a script has Windows line endings. See [Troubleshooting](#troubleshooting).

### Add the license files

Copy your license files into the `licenses` directory with these exact names:

- `licenses/workbench-license.lic`
- `licenses/connect-license.lic`
- `licenses/package-manager-license.lic`

On Windows, copy them from the Windows drive into WSL, for example:

```bash
cp /mnt/c/Users/<windows-user>/Downloads/*.lic licenses/
```

> [!IMPORTANT]
> Add the license files before the first start. If a file is missing, Docker creates an empty directory with that name, and the service does not start. Delete that directory before you copy the file.

The `.gitignore` file excludes license files and `.env` from Git. Do not commit or share them.

### Configure SAS Viya

Copy the template:

```bash
cp .env.example .env
```

Edit `.env` and set the following values:

**`VIYA_HOSTNAME`**: The host name of your SAS Viya server, for example `viya.example.com`. Workbench and Connect share this value. Leave it empty to run without SAS Viya.

**`WORKBENCH_VIYA_CLIENT_ID`** and **`WORKBENCH_VIYA_CLIENT_SECRET`**: The SAS Logon client for the Workbench OAuth integration. Leave both empty to turn off the integration.

**`CONNECT_VIYA_CLIENT_ID`** and **`CONNECT_VIYA_CLIENT_SECRET`**: The SAS Logon client for the Connect OAuth integration. Use a different client from the Workbench client. Leave both empty to turn off the integration.

**`POSITRON_SAS_CLIENT_ID`**: The SAS Logon client that the Positron SAS extension uses when it signs in to SAS Logon itself, for example `vscode-positron`.

**`POSIT_USER_PASSWORD`**: Optional. The password of the user `posit` in Workbench and Connect. The default is `positsas2026`. Connect rejects weak passwords such as `posit`. Workbench applies a change when Docker re-creates the container. Connect uses the value only when it creates the user.

**`VIYA_SCOPES`**: Optional. Comma-separated OAuth scopes. The default is `openid,sas-compute.user_impersonation`.

If you set only some of the values for one product, the setup of that product stops with a message that names the missing values.

### Register the OAuth clients in SAS Viya

Ask your SAS Viya administrator to register a SAS Logon client for each product with these redirect Uniform Resource Identifiers (URIs):

| Client | Redirect URI |
|--------|--------------|
| Workbench | `http://localhost:8787/oauth_redirect_callback` |
| Connect | `http://localhost:3939/__oauth__/integrations/callback` |

The [SAS Viya with OAuth tokens](https://posit-dev.github.io/positron-sas-extension/Workbench/Code/viyaOauth) guide describes the client registration.

### Start the services

```bash
docker compose up -d
```

Docker pulls the images on the first start, which takes several minutes. Check the status:

```bash
docker compose ps
```

The environment is ready when `connect`, `package-manager`, and `workbench` report `(healthy)`. The one-time `connect-init` service creates the Connect administrator and the SAS Viya integration, then exits.

## Sign in

### Sign in to Workbench

Open <http://localhost:8787> and sign in as `posit` with the password `positsas2026`.

### Sign in to Connect

Open <http://localhost:3939> and sign in as `posit` with the password `positsas2026`. This user has the publisher role.

To administer Connect, sign in as `admin`. If you did not set `CONNECT_ADMIN_PASSWORD` in `.env`, read the generated password:

```bash
docker compose exec connect cat /var/lib/connect-bootstrap/admin-password
```

## Use SAS Viya from Positron

1. In Workbench, sign in to SAS Viya from the Workbench home page. Workbench stores the token for your sessions.
1. Start a Positron Pro session. Workbench installs the Positron SAS extension when the session starts.
1. Open a `.sas` file and run it. The extension connects with the default `viya` profile, which points to `https://VIYA_HOSTNAME`.

The extension uses the Workbench OAuth integration when its token URL matches the profile endpoint. Otherwise, the extension signs in to SAS Logon in the browser with `POSITRON_SAS_CLIENT_ID`.

Workbench adds the default profile to your Positron settings once. Later changes to `VIYA_HOSTNAME` or `POSITRON_SAS_CLIENT_ID` do not change the profile of a user who already has it. To get the updated profile, remove `SAS.connectionProfiles` from your Positron user settings and start another session.

## Trust a private certificate authority

If SAS Viya uses a certificate from a private certificate authority, copy the certificate authority certificate into the `certs` directory as a `.crt` or `.pem` file. Then restart Workbench and Connect:

```bash
docker compose restart workbench connect
```

Workbench sessions and Connect content trust the certificate. This includes Python code that uses the requests package, and Node.js code.

## Common tasks

| Task | Command |
|------|---------|
| Start, or apply changes to `.env` and `docker-compose.yml` | `docker compose up -d` |
| Show status | `docker compose ps` |
| Follow the logs of a service | `docker compose logs -f workbench` |
| Apply changes to a file in `config` | `docker compose up -d --force-recreate <service>` |
| Re-create the Connect SAS Viya integration | `docker compose run --rm connect-init` |
| Stop the services and keep the data | `docker compose down` |

## Troubleshooting

**A service restarts and its log shows `$'\r': command not found`**: A script has Windows line endings, usually after an editor on Windows changed it. Convert the files and start again:

```bash
find config -type f -exec sed -i 's/\r$//' {} +
sed -i 's/\r$//' .env
docker compose up -d --force-recreate
```

On macOS, use `sed -i ''` in place of `sed -i`.

**A service fails with an error about a mount or a directory**: A license file or configuration file was missing when the service started. Delete the empty directory that Docker created in its place, add the file, and run `docker compose up -d`.

**Workbench or Connect stays `(health: starting)` for several minutes**: The first start on Apple silicon takes several minutes. Follow the progress with `docker compose logs -f <service>`.

**`connect-init` fails**: Read its log with `docker compose logs connect-init`. Fix the setting that the log names, then run `docker compose run --rm connect-init`.

**SAS Viya sign-in fails with a certificate error**: Add the certificate authority certificate as described in [Trust a private certificate authority](#trust-a-private-certificate-authority).

**A port is already in use**: Stop the program that uses port 3939, 4242, or 8787, then run `docker compose up -d`.

## Remove the environment

> [!WARNING]
> The following command permanently deletes all data, including Connect content, Workbench home directories, and Package Manager data.

```bash
docker compose down -v
```

## Repository layout

| Path | Contents |
|------|----------|
| `docker-compose.yml` | Service definitions |
| `.env.example` | Template for SAS Viya settings and secrets |
| `config/workbench` | Workbench configuration and the `pwb-init.sh` startup script |
| `config/connect` | Connect configuration and the `connect-init.py` setup script |
| `config/ppm` | Package Manager configuration |
| `config/shared` | Script that installs the certificates from `certs` |
| `certs` | Optional certificate authority certificates |
| `licenses` | Your license files, not included in the repository |
