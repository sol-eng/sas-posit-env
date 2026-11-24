# License files

Copy your Posit license files into this directory with these exact names:

- `workbench-license.lic`
- `connect-license.lic`
- `package-manager-license.lic`

Docker Compose mounts each file into its container. Add the files before the first `docker compose up -d`. If a file is missing, Docker creates an empty directory with that name, and the service does not start. Delete that directory before you copy the file.

The `.gitignore` file excludes `*.lic` files in this directory. Do not commit or share them.
