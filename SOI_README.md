# Sealog Server — SOI Deployment Guide

This is the Schmidt Ocean Institute fork of [sealog-server](https://github.com/schimdtocean/sealog-server). It extends the upstream server with SOI-specific seed data and instance-type-aware database initialisation.

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

### Environment variables

Most settings read from environment variables automatically.

| Variable | Default | Description |
|---|---|---|
| `SEALOG_INSTANCE_TYPE` | — | **Required.** `FKt`, `Sub`, or `emp` — controls which seed data loads |
| `NODE_ENV` | `development` | `production`, `development`, `test`, `debug`, `demo-vehicle`, `demo-vessel` |
| `MONGO_URL` | `mongodb://localhost:27017/<db>` | Full MongoDB connection URL |
| `SEALOG_SERVER_FILEPATH_ROOT` | `/opt/sealog-files-fkt` | Root path for Sealog files/images |
| `SEALOG_SERVER_SECRET` | — | JWT signing secret (required in production) |
| `SEALOG_DEFAULT_PASSWD` | `password` | Default password used when setting up users for the first time |
| `SEALOG_SERVER_PORT` | `8000` | HTTP/HTTPS listen port |
| `SEALOG_SERVER_USE_ACCESS_CONTROL` | `false` | Enable per-cruise/per-lowering user access lists |
| `SEALOG_DISABLE_SELF_REGISTRATION` | `false` | Prevent new user self-registration |
| `SEALOG_SERVER_TLS_PRIVKEY` | — | Path to TLS private key (enables HTTPS) |
| `SEALOG_SERVER_TLS_FULLCHAIN` | — | Path to TLS certificate chain |

Gmail OAuth2 is enabled automatically when all three variables below are set. If any are missing, email remains disabled. Nodemailer obtains and refreshes access tokens internally, so an access token and OAuth redirect URL are not required.

| Variable | Provider |
|---|---|
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` | Gmail OAuth2 |

The appropriate env values are stored in the [shipboard-configuration](https://github.com/schmidtocean/shipboard-configuration) repo within the ./Systems/Sealog/sealog-[FKt|Sub|emp] directories.  Symlink the appropriate env file to the sealog-server root directory as `.env` to apply the values to the server.

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

The Docker setup runs all three server variants simultaneously against a shared MongoDB container, each on its own port and database.

| Instance | URL |
|---|---|
| FKt (R/V Falkor(too)) | `http://localhost:8000/sealog-server` |
| Sub (ROV Subastian) | `http://localhost:8100/sealog-server` |
| emp (AUV Empress) | `http://localhost:8200/sealog-server` |

### 1. Set up config files

`Dockerfile` and `docker-compose.yml` are gitignored. Copy the templates:

```bash
cp Dockerfile.dist Dockerfile
cp docker-compose.yml.dist docker-compose.yml
```

Copy the per-instance env files from shipboard-configurations:

```bash
cp ../shipboard-configuration/Systems/Sealog/server-FKt/.env .env.FKt
cp ../shipboard-configuration/Systems/Sealog/server-Sub/.env .env.Sub
cp ../shipboard-configuration/Systems/Sealog/server-emp/.env .env.emp
```

Copy the server config templates (defaults work without modification for Docker):

```bash
ln -s config/db_constants.js.dist    config/db_constants.js
ln -s config/email_settings.js.dist  config/email_settings.js
ln -s config/manifest.js.dist        config/manifest.js
ln -s config/server_settings.js.dist config/server_settings.js
ln -s config/secret.js.dist          config/secret.js
```

You can use the same secret in all three files for local development.

### 2. Start the stack

```bash
docker compose up --build
```

Because `NODE_ENV=development`, each instance drops and reseeds its database on every container start using SOI seed data for that instance type. To persist data between restarts, change `NODE_ENV=debug` in the relevant `.env.*` file.

---

## VM production environment

For a full walkthrough of installing MongoDB and Node.js on Ubuntu 24.04 LTS, see [INSTALL.md](INSTALL.md). The SOI-specific steps are below.

### 1. Clone and install

```bash
cd ~
git clone https://github.com/schmidtocean/sealog-server
mv sealog-server /opt/sealog-server-<type>
```

```bash
cd /opt/sealog-server-<type>
npm install
python3 -m venv venv
source ./venv/bin/activate
pip install -r requirements.txt
```

### 2. Set up config files

```bash
ln -s config/db_constants.js.dist    config/db_constants.js
ln -s config/email_settings.js.dist  config/email_settings.js
ln -s config/manifest.js.dist        config/manifest.js
ln -s config/server_settings.js.dist config/server_settings.js
ln -s config/secret.js.dist          config/secret.js
```

### 3. setup the services files:

For all instance types:
```bash
cd /opt/sealog-server-<type>/misc
ln -s sealog_asnap.py.dist sealog_asnap.py
ln -s sealog_aux_data_inserter_influx.py.dist sealog_aux_data_inserter_influx.py
```

For sealog-fkt:
```bash
cd /opt/sealog-server-fkt/misc
ln -s sealog_auto_actions_fkt.py sealog_auto_actions.py
ln -s sealog_create_cruise_from_openvdm.py.dist sealog_create_cruise_from_openvdm.py
ln -s sealog_cruise_sync.py.dist sealog_cruise_sync.py
ln -s sealog_vessel_data_export_fkt.py sealog_data_export.py
```

For sealog-sub:
```bash
cd /opt/sealog-server-sub/misc
ln -s sealog_auto_actions_sub.py sealog_auto_actions.py
ln -s sealog_vehicle_data_export_sub.py sealog_data_export.py
```

For sealog-emp:
```bash
cd /opt/sealog-server-emp/misc
ln -s sealog_auto_actions_emp.py sealog_auto_actions.py
ln -s sealog_vehicle_data_export_emp.py sealog_data_export.py
```

### 4. Set environment variables

Clone the [shipboard-configuration](https://github.com/schmidtocean/shipboard-configuration) repo and symlink the appropriate `.env` file to the server

```bash
cd ~
git clone https://github.com/schmidtocean/shipboard-configuration
ln -s ~/shipboard-configuration/Systems/Sealog/server-FKt/.env  /opt/sealog-server-fkt/
ln -s ~/shipboard-configuration/Systems/Sealog/server-Sub/.env  /opt/sealog-server-sub/
ln -s ~/shipboard-configuration/Systems/Sealog/server-emp/.env  /opt/sealog-server-emp/
```

### 5. Create the file storage directory

```bash
mkdir -p /data/sealog-files-fkt
mkdir -p /data/sealog-files-sub
mkdir -p /data/sealog-files-emp
```

Make sure the directories are owned by the `mt` user

### 6. Set up supervisor

Install supervisor if not already present:

```bash
sudo apt-get install supervisor
```

Symlink the supervisor config file for each instance:

```bash
sudo ln -s ~/shipboard-configuration/Systems/Sealog/server-FKt/etc/sealog-fkt.conf  /etc/supervisor/conf.d
sudo ln -s ~/shipboard-configuration/Systems/Sealog/server-Sub/etc/sealog-sub.conf  /etc/supervisor/conf.d
sudo ln -s ~/shipboard-configuration/Systems/Sealog/server-emp/etc/sealog-emp.conf  /etc/supervisor/conf.d
```

Load and start:

```bash
sudo supervisorctl
> reread
> update
```

Some of the processes will fail at this point because they depend on additional setup.

### 7. Additional setup

#### Sealog JWT

Obtain the JWT from the sealog-server API
```bash
curl -X 'POST' \
  'http://localhost:<server_port>/sealog-server/api/v1/auth/login' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "username": "admin",
  "password": "<password>"
}'
```

This will return:
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjU5ODFmMTY3MjEyYjM0OGFlZDdmYTlmNSIsInNjb3BlIjpbImFkbWluIl0sInJvbGVzIjpbImFkbWluIiwiY3J1aXNlX21hbmFnZXIiLCJldmVudF9sb2dnZXIiLCJldmVudF9tYW5hZ2VyIiwiZXZlbnRfd2F0Y2hlciIsInRlbXBsYXRlX21hbmFnZXIiXSwiaWF4IjoxNzg1NzYyNjU5fQ.L_pXOIg2TOK60LewZmd2CpkapX0_l94oT0AkhRgLtcE",
  "id": "5981f167412b348aed7fa9f5"
}
```

Create the settings file:
```bash
cd /opt/sealog-server-<type>/misc/python_sealog
cp settings.py.dist settings.py
```

Copy/paste the token value insto the TOKEN value
```python
TOKEN = ''  # noqa:E501
```

Also make sure the port number matches the the server's port number in the `API_SERVER_URL` and `WS_SERVER_URL` variables

#### Influx JWT

Create the settings file:
```bash
cd /opt/sealog-server-<type>/misc/influx_sealog
cp settings.py.dist settings.py
```

Update the values accordingly
```python
# InfluxDB settings
INFLUXDB_URL = 'http://localhost:8086'
INFLUXDB_ORG = 'openrvdas'
INFLUXDB_BUCKET = 'openrvdas'
INFLUXDB_AUTH_TOKEN = 'DEFAULT_INFLUXDB_AUTH_TOKEN'  # noqa:E501
INFLUXDB_VERIFY_SSL = False
```

#### Slack Integration

Create the settings file:
```bash
cd /opt/sealog-server-<type>/misc/slack_sealog
cp settings.py.dist settings.py
```

Set the Slack URL value
```python
SLACK_WEBHOOK_URL = None
```

Restart the supervisor processes so that these updates take affect.

```bash
sudo supervisorctl restart all
```
