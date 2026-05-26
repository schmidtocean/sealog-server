# Installation Instructions — SOI Fork

This is the Schmidt Ocean Institute fork of sealog-server. For a deployment overview, environment variable reference, and Docker development workflow see [SOI_README.md](SOI_README.md).

---

## Prerequisites

- [MongoDB](https://www.mongodb.com) ≥ 6.x
- [Node.js](https://nodejs.org) ≥ 21.x
- [npm](https://www.npmjs.com) ≥ 6.13.x
- [git](https://git-scm.com)
- Python 3 with `venv` (for ancillary services)
- `supervisor` (for production auto-start)

---

## Installing MongoDB 6.x on Ubuntu 22.04 LTS

Install dependencies:
```bash
sudo apt install gnupg wget apt-transport-https ca-certificates software-properties-common
```

Import the MongoDB GPG key:
```bash
curl -fsSL https://pgp.mongodb.com/server-6.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-6.0.gpg --dearmor
```

Add the MongoDB repository:
```bash
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] \
https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/6.0 multiverse" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-6.0.list
```

Install and start MongoDB:
```bash
sudo apt-get update
sudo apt-get install mongodb-org
sudo systemctl start mongod
sudo systemctl enable mongod
```

---

## Installing Node.js on Ubuntu 22.04 LTS

Install the LTS version of Node.js using [nvm](https://github.com/nvm-sh/nvm):
```bash
wget -qO- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"

nvm install --lts
NODE_VERSION=$(node -v)
sudo ln -s $HOME/.nvm/versions/node/${NODE_VERSION}/bin/npm /usr/local/bin/
sudo ln -s $HOME/.nvm/versions/node/${NODE_VERSION}/bin/node /usr/local/bin/
```

---

## VM Production Installation

### 1. Clone the repository

```bash
git clone https://github.com/schmidtocean/sealog-server.git /opt/sealog-server
cd /opt/sealog-server
```

Checkout the SOI branch:
```bash
git checkout soi_24
```

### 2. Run the install script

The install script handles prerequisites, git hooks, supervisor config, and the Python virtual environment in one step:

```bash
bash utils/install.sh
```

The script will prompt for instance type (`FKt`, `Sub`, or `emp`) and then:
- Install system prerequisites (MongoDB, Node.js, supervisor, Python venv)
- Set up git **pre-commit** and **post-merge** hooks for automatic config file rotation (see [Config file rotation](#config-file-rotation))
- Generate and install a `supervisord` config for the chosen instance
- Bootstrap `.env` from `.env.dist` if `.env` does not already exist
- Set up the Python virtual environment

### 3. Install Node.js dependencies

```bash
npm install
```

### 4. Set up config files

Config files are gitignored — only the `.dist` templates are committed. The `post-merge` git hook (installed by `install.sh`) rotates the per-instance files automatically after `git pull`. To set them up for the first time, run the hook directly:

```bash
.git/hooks/post-merge
```

If instance-named config files (`config/manifest_FKt.js`, etc.) do not yet exist, copy from the `.dist` templates and edit manually:

```bash
cp config/db_constants.js.dist    config/db_constants.js
cp config/email_settings.js.dist  config/email_settings.js
cp config/manifest.js.dist        config/manifest.js
cp config/server_settings.js.dist config/server_settings.js
cp config/secret.js.dist          config/secret.js
```

**`config/secret.js`** — Generate and paste a JWT signing secret:
```bash
node -e "console.log(require('crypto').randomBytes(256).toString('base64'));"
```
Paste the output between the single quotes: `module.exports = '<paste here>'`

**`config/email_settings.js`** — Set `senderAddress` and `notificationEmailAddresses`, then uncomment one provider block (Gmail OAuth2, Mailgun, or Mailjet).

### 5. Configure `.env`

```bash
nano /opt/sealog-server/.env
```

At minimum set:
```
SEALOG_INSTANCE_TYPE=FKt          # or Sub
NODE_ENV=production
MONGO_URL=mongodb://localhost:27017/sealogDB_FKt
SEALOG_SERVER_FILEPATH_ROOT=/opt/sealog-server/sealog-files
SEALOG_SERVER_SECRET=<generated secret>
```

See `.env.dist` for the full list of available variables.

### 6. Create the file storage directory

```bash
mkdir -p /opt/sealog-server/sealog-files
```

The server creates `images/`, `cruises/`, and `lowerings/` subdirectories automatically on first start.

### 7. Start the server

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start sealog-FKt:   # or sealog-Sub:, sealog-emp:
```

---

## Config file rotation

The install script sets up git hooks that keep per-instance config files in sync with the repository across `git pull` / `git push` operations.

**pre-commit hook** — Before each commit, copies the working config files to instance-named filenames and stages them:
```
config/manifest.js  →  config/manifest_FKt.js  (staged and committed)
```

**post-merge hook** — After each `git pull`, copies instance-named files back to the working filenames and runs `npm install` and `pip install`:
```
config/manifest_FKt.js  →  config/manifest.js
```

`config/secret.js` and `.env` are **not** part of this rotation — they are gitignored and managed separately on each deployment.

---

## Starting the server in development mode

```bash
cd /opt/sealog-server
SEALOG_INSTANCE_TYPE=FKt npm run start-devel
```

This starts the server in development mode: verbose logging, and the database is **dropped and reseeded** from SOI seed files on every start. See [SOI_README.md](SOI_README.md) for which seed files are loaded per instance type.

---

## Making the API available over port 80

On vessel networks that only allow access via standard ports, tunnel the API through port 80 using Apache.

### Prerequisites

- [Apache](https://httpd.apache.org) with `mod_proxy` and `mod_proxy_wstunnel` enabled

Enable the modules and restart Apache:
```bash
sudo a2enmod proxy proxy_http proxy_wstunnel
sudo service apache2 restart
```

### Apache site configuration

Add the following to `/etc/apache2/sites-available/000-default.conf`, replacing `<serverIP>` and `<port>` with your values:

```apache
ProxyPreserveHost On
ProxyRequests Off
ServerName <serverIP>
ProxyPass /sealog-server/ http://<serverIP>:<port>/sealog-server/
ProxyPassReverse /sealog-server/ http://<serverIP>:<port>/sealog-server/
ProxyPass /ws ws://<serverIP>:<port>/
ProxyPassReverse /ws ws://<serverIP>:<port>/
```

```bash
sudo service apache2 restart
```

---

## Enabling HTTPS

Set `SEALOG_SERVER_TLS_PRIVKEY` and `SEALOG_SERVER_TLS_FULLCHAIN` in `.env` to the paths of your certificate files:

```
SEALOG_SERVER_TLS_PRIVKEY=/etc/letsencrypt/live/example.com/privkey.pem
SEALOG_SERVER_TLS_FULLCHAIN=/etc/letsencrypt/live/example.com/fullchain.pem
```

Ensure the user running the server process has read access to the certificate files.

---

## Enabling Additional Functionality

The ancillary Python services are optional but greatly extend the platform. They require a Python virtual environment set up in the project root.

### Python virtual environment

```bash
sudo apt-get install python3 python3-dev python3-pip python3-venv
cd /opt/sealog-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Automatic Snapshot (ASNAP)

ASNAP submits an event to the server at a regular interval, ensuring minimum temporal resolution during a cruise or lowering.

```bash
cp /opt/sealog-server/misc/sealog_asnap.py.dist /opt/sealog-server/misc/sealog_asnap.py
```

The supervisor config installed by `utils/install.sh` includes an ASNAP entry. The default interval is 300 seconds for FKt and 10 seconds for Sub. To override, edit the `command` line in `/etc/supervisor/conf.d/sealog-server-<INSTANCE>.conf`:

```ini
command=/opt/sealog-server/venv/bin/python ./misc/sealog_asnap.py --interval 60
```

### Auto-Actions

Auto-Actions triggers additional logic (lowering milestone updates, ASNAP toggling, etc.) in response to submitted events. A Sub-specific script is included.

```bash
cp /opt/sealog-server/misc/sealog_auto_actions.py.dist /opt/sealog-server/misc/sealog_auto_actions.py
```

### Post-lowering and post-cruise data exports

```bash
# For vehicle (Sub) installations:
cp /opt/sealog-server/misc/sealog_vehicle_data_export.py.dist \
   /opt/sealog-server/misc/sealog_vehicle_data_export.py

# For vessel (FKt) installations:
cp /opt/sealog-server/misc/sealog_vessel_data_export.py.dist \
   /opt/sealog-server/misc/sealog_vessel_data_export.py
```

Edit the copied file and set `EXPORT_ROOT_DIR` and `VEHICLE_NAME` / `VESSEL_NAME` to match the deployment. Data exports are triggered via the web UI (through the `external_calls` API route) rather than through supervisor.
