# Custom CA certificates (optional)

Put CA certificates here (`*.crt` or `*.pem`, PEM or DER; a PEM file may hold
a whole chain) when SAS Viya — or anything else Workbench or Connect talks to
over HTTPS — uses a certificate signed by a CA that isn't publicly trusted.

They are added to the system trust store of the Workbench and Connect
containers at startup. After adding or removing files, restart both:

    docker compose restart workbench connect

Leave this folder without certificates to skip the step. Other files, such as
this README, are ignored.
