# Sealog Server — SOI Deployment Guide

This is the Schmidt Ocean Institute fork of [sealog-server](https://github.com/OceanDataTools/sealog-server). It extends the upstream server with SOI-specific seed data and instance-type-aware database initialisation.

Three named instance types are supported, controlled by the `SEALOG_INSTANCE_TYPE` environment variable:

| Instance | `SEALOG_INSTANCE_TYPE` | Purpose |
|---|---|---|
| R/V Falkor(too) vessel server | `FKt` | Vessel-level cruise logging |
| ROV Subastian vehicle server | `Sub` | Vehicle-level dive logging |
| AUV Empress | `emp` | Blank instance, minimal seed data |

---

## Prerequisites

- **Node.js** ≥ 21.x
- **npm** ≥ 6.13.x
- **MongoDB** ≥ 6.x
- **git**
- **Docker + Docker Compose** (development workflow only)
- **Python 3** with `venv` and **supervisor** (VM production workflow only)

See [INSTALL.md](INSTALL.md) for step-by-step instructions to install MongoDB and Node.js on Ubuntu 22.04 LTS.

---

## Configuration

### Config files

Config files live in `config/` and are gitignored — only the `.dist` versions are committed. Copy each `.dist` file before starting the server:

```bash
cp config/db_constants.js.dist    config/db_constants.js
cp config/email_settings.js.dist  config/email_settings.js
cp config/manifest.js.dist        config/manifest.js
cp config/server_settings.js.dist config/server_settings.js
cp config/secret.js.dist          config/secret.js
```

Most settings read from environment variables automatically. The files that typically require manual editing are:

**`config/secret.js`** — JWT signing secret. Generate and paste a key:
```bash
node -e "console.log(require('crypto').randomBytes(256).toString('base64'));"
```

**`config/email_settings.js`** — Set `senderAddress` and `notificationEmailAddresses`, then uncomment one provider block (Gmail OAuth2, Mailgun, or Mailjet) and supply the corresponding environment variables. Leave all blocks commented to disable email.

**`config/db_constants.js`** — Override `sealogDB` and `sealogDB_devel` collection names here, or use `SEALOG_DB_NAME` / `SEALOG_DB_DEVEL_NAME` env vars.

**`config/server_settings.js`** — Override `reCaptchaSecret`, `disableRegisteringUsers`, and `registeringUserRoles` if the env-var defaults are not sufficient.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `SEALOG_INSTANCE_TYPE` | — | **Required.** `FKt`, `Sub`, or `emp` — controls which seed data loads |
| `NODE_ENV` | `development` | `production`, `development`, `test`, `debug`, `demo-vehicle`, `demo-vessel` |
| `MONGO_URL` | `mongodb://localhost:27017/<db>` | Full MongoDB connection URL |
| `SEALOG_SERVER_PORT` | `8000` | HTTP/HTTPS listen port |
| `SEALOG_SERVER_FILEPATH_ROOT` | `/opt/sealog-server/sealog-files` | Root path for file storage |
| `SEALOG_SERVER_SECRET` | — | JWT signing secret (required in production) |
| `SEALOG_DB_NAME` | `sealogDB` | Production MongoDB database name |
| `SEALOG_DB_DEVEL_NAME` | `sealogDB_devel` | Dev/test database name |
| `SEALOG_SERVER_USE_ACCESS_CONTROL` | `false` | Enable per-cruise/per-lowering user access lists |
| `SEALOG_DISABLE_SELF_REGISTRATION` | `false` | Prevent new user self-registration |
| `SEALOG_SERVER_TLS_PRIVKEY` | — | Path to TLS private key (enables HTTPS) |
| `SEALOG_SERVER_TLS_FULLCHAIN` | — | Path to TLS certificate chain |

Email provider variables (set whichever matches the provider block uncommented in `config/email_settings.js`):

| Variable | Provider |
|---|---|
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_SERVER_URL`, `GMAIL_REFRESH_TOKEN` | Gmail OAuth2 |
| `MG_APIKEY`, `MG_DOMAIN` | Mailgun |
| `MJ_APIKEY_PUBLIC`, `MJ_APIKEY_PRIVATE` | Mailjet |

### NODE_ENV behaviour

| `NODE_ENV` | Database | On startup |
|---|---|---|
| `production` | `sealogDB` | Runs migrations only; never drops collections |
| `debug` | `sealogDB` | Same as production but with full request logging |
| `development` | `sealogDB_devel` | Drops and reseeds all collections on every start |
| `test` | `sealogDB_devel` | Same as development; used by the test suite |
| `demo-vehicle` | `sealogDB_devel` | Loads vehicle-focused demo data |
| `demo-vessel` | `sealogDB_devel` | Loads vessel-focused demo data |

### SOI seed data (`SEALOG_INSTANCE_TYPE`)

In `development` and `test` modes the database is populated from SOI-specific seed files. `SEALOG_INSTANCE_TYPE` selects which files are loaded:

| Collection | `FKt` | `Sub` | `emp` |
|---|---|---|---|
| `event_templates` | `init_data/system_templates_FKt.json` | `init_data/system_templates_Sub.json` | `init_data/system_templates_emp.json` |
| `events` | `demo/FKt230303_eventOnlyExport.json` | `demo/FKt230303_S0492_eventOnlyExport.json` | `demo/FKt230303_S0492_eventOnlyExport.json` |
| `event_aux_data` | `demo/FKt230303_auxDataExport.json` | `demo/FKt230303_S0492_auxDataExport.json` | `demo/FKt230303_S0492_auxDataExport.json` |
| `cruises` | `demo/FKt230303_cruiseRecord.json` | `demo/FKt230303_cruiseRecord.json` | `demo/FKt230303_cruiseRecord.json` |
| `lowerings` | `demo/FKt230303_S0492_loweringRecord.json` | `demo/FKt230303_S0492_loweringRecord.json` | `demo/FKt230303_S0492_loweringRecord.json` |
| `users` | `init_data/system_users_soi.json` | `init_data/system_users_soi.json` | `init_data/system_users_soi.json` |

---

## Docker development environment

The Docker setup runs a single instance against a MongoDB container. Copy and edit the dist files, then build and start.

### 1. Set up config files

```bash
cp config/db_constants.js.dist    config/db_constants.js
cp config/email_settings.js.dist  config/email_settings.js
cp config/manifest.js.dist        config/manifest.js
cp config/server_settings.js.dist config/server_settings.js
cp config/secret.js.dist          config/secret.js
```

The defaults work without modification for a Docker dev environment.

### 2. Create the Dockerfile

`Dockerfile` is gitignored. Copy the provided template:

```bash
cp Dockerfile.dist Dockerfile
```

### 3. Configure the compose file

Copy and edit the compose file:

```bash
cp docker-compose.yml.dist docker-compose.yml
```

Set `SEALOG_INSTANCE_TYPE` and `SEALOG_SERVER_SECRET` in the `environment` section. For development also set `NODE_ENV=development`. Example:

```yaml
environment:
  - SEALOG_INSTANCE_TYPE=FKt
  - SEALOG_SERVER_SECRET=<generated secret>
  - NODE_ENV=development
  - MONGO_URL=mongodb://mongo:27017/sealogDB_devel
```

### 4. Start the stack

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000/sealog-server` and Swagger UI at `http://localhost:8000/sealog-server/documentation`.

Because `NODE_ENV=development`, the database is dropped and reseeded on every container start. To persist data between restarts, set `NODE_ENV=debug`.

---

## VM production environment

For a full walkthrough of installing MongoDB and Node.js on Ubuntu 22.04 LTS, see [INSTALL.md](INSTALL.md). The SOI-specific steps are below.

### 1. Clone and install

```bash
git clone <repo-url> /opt/sealog-server
cd /opt/sealog-server
npm install
```

### 2. Set up config files

```bash
cp config/db_constants.js.dist    config/db_constants.js
cp config/email_settings.js.dist  config/email_settings.js
cp config/manifest.js.dist        config/manifest.js
cp config/server_settings.js.dist config/server_settings.js
cp config/secret.js.dist          config/secret.js
```

Edit each file as described in the [Config files](#config-files) section above. At minimum, edit `config/secret.js` to set the JWT secret and `config/manifest.js` to set the port if not using the default.

### 3. Set environment variables

The server reads environment variables from a `.env` file in the project root when started with `node --env-file=.env server.js`. Create the file:

```bash
cp .env.dist .env   # if .env.dist is present, otherwise create from scratch
nano .env
```

At minimum set:

```
SEALOG_INSTANCE_TYPE=FKt
NODE_ENV=production
MONGO_URL=mongodb://localhost:27017/sealogDB_FKt
SEALOG_SERVER_FILEPATH_ROOT=/opt/sealog-server/sealog-files
SEALOG_SERVER_SECRET=<generated secret>
```

### 4. Create the file storage directory

```bash
mkdir -p /opt/sealog-server/sealog-files
```

The server creates `images/`, `cruises/`, and `lowerings/` subdirectories automatically on first start.

### 5. Set up supervisor

Install supervisor if not already present:

```bash
sudo apt-get install supervisor
```

Create a supervisor config file for the instance. Example for `FKt`:

```bash
sudo tee /etc/supervisor/conf.d/sealog-server-FKt.conf << 'EOF'
[program:sealog-server-FKt]
directory=/opt/sealog-server
command=node --env-file=.env server.js
redirect_stderr=true
stdout_logfile=/var/log/sealog-server-FKt_STDOUT.log
user=mt
autostart=true
autorestart=true
EOF
```

Load and start:

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start sealog-server-FKt
```

### Ongoing maintenance

| Task | Command |
|---|---|
| Pull updates | `git pull && npm install` |
| Restart server | `sudo supervisorctl restart sealog-server-FKt` |
| View logs | `sudo tail -f /var/log/sealog-server-FKt_STDOUT.log` |
| Check status | `sudo supervisorctl status` |

---

## Development workflow

```bash
# Start in development mode (drops and reseeds DB on every start)
SEALOG_INSTANCE_TYPE=FKt npm run start-devel

# Start in debug mode (persists DB, full request logging)
npm run start-debug

# Run tests (drops and reseeds DB)
npm run start-test

# Run a single test file
NODE_ENV=test node_modules/.bin/lab test/events.test.js

# Lint
npm run lint
npm run lint-fix
```

---

## Making the API available over port 80

See [INSTALL.md](INSTALL.md#making-the-api-available-over-port-80) for Apache reverse proxy configuration.

## Enabling HTTPS

Set `SEALOG_SERVER_TLS_PRIVKEY` and `SEALOG_SERVER_TLS_FULLCHAIN` to the paths of your certificate files. See [INSTALL.md](INSTALL.md#enabling-https) for details.

## Python ancillary services

See [INSTALL.md](INSTALL.md#enabling-additional-functionality) for setup instructions for ASNAP, Auto-Actions, and data export scripts.
