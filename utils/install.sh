#!/bin/bash

# Get the current directory
current_dir=$(pwd)

handle_error() {
    echo "Error occurred in script at line $1."
    cd "$current_dir"
    exit 1
}

trap 'handle_error $LINENO' ERR

script_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
install_dir="$(dirname "$script_dir")"

echo "Install directory: $install_dir"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

install_prereqs() {
    echo "Installing prerequisites..."
    sudo apt install -y gnupg wget apt-transport-https ca-certificates \
        software-properties-common python3-venv supervisor
}

install_mongo() {
    if ! which mongod > /dev/null 2>&1; then
        echo "Installing MongoDB 6.x..."
        curl -fsSL https://pgp.mongodb.com/server-6.0.asc | \
            sudo gpg -o /usr/share/keyrings/mongodb-server-6.0.gpg --dearmor
        echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] \
https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/6.0 multiverse" | \
            sudo tee /etc/apt/sources.list.d/mongodb-org-6.0.list
        sudo apt-get update
        sudo apt-get install -y mongodb-org
        sudo systemctl start mongod
        sudo systemctl enable mongod
    else
        echo "MongoDB already installed, skipping."
    fi
}

install_node() {
    if [ ! -f /usr/local/bin/node ]; then
        echo "Installing Node.js (LTS) via nvm..."
        local node_install_pwd
        node_install_pwd=$(pwd)
        cd ~
        wget -qO- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
        export NVM_DIR="$HOME/.nvm"
        # shellcheck source=/dev/null
        [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
        [ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"
        nvm install --lts
        NODE_VERSION=$(node -v)
        sudo ln -sf "$HOME/.nvm/versions/node/${NODE_VERSION}/bin/npm" /usr/local/bin/
        sudo ln -sf "$HOME/.nvm/versions/node/${NODE_VERSION}/bin/node" /usr/local/bin/
        cd "$node_install_pwd"
    else
        echo "Node.js already installed, skipping."
    fi
}

# ---------------------------------------------------------------------------
# Choose instance type
# ---------------------------------------------------------------------------

cd "$install_dir"

if [ ! -d venv ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

echo "Activating Python virtual environment..."
source venv/bin/activate

echo ""
echo "Choose an instance type:"
echo "  1. Sealog-FKt  (R/V Falkor(too) vessel server)"
echo "  2. Sealog-Sub  (ROV Subastian vehicle server)"
echo "  3. Sealog-emp  (AUV Empress vehicle server)"
echo ""
read -rp "Enter your choice (1, 2, or 3): " instance_choice

case $instance_choice in
    1)
        INSTANCE="FKt"
        ;;
    2)
        INSTANCE="Sub"
        ;;
    3)
        INSTANCE="emp"
        ;;
    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac

echo "Configuring for instance: $INSTANCE"

# ---------------------------------------------------------------------------
# Git hooks
# ---------------------------------------------------------------------------

echo "Setting up git pre-commit hook..."
cat > .git/hooks/pre-commit << HOOK
#!/bin/bash

# Update pip requirements file
$install_dir/venv/bin/pip freeze > $install_dir/requirements.txt
git add "$install_dir/requirements.txt"

# Copy working config files to their instance-named repo filenames
cp "$install_dir/config/db_constants.js"    "$install_dir/config/db_constants_${INSTANCE}.js"
cp "$install_dir/config/email_settings.js"  "$install_dir/config/email_settings_${INSTANCE}.js"
cp "$install_dir/config/manifest.js"        "$install_dir/config/manifest_${INSTANCE}.js"
cp "$install_dir/config/server_settings.js" "$install_dir/config/server_settings_${INSTANCE}.js"

# Stage the changes
git add "$install_dir/config/db_constants_${INSTANCE}.js"
git add "$install_dir/config/email_settings_${INSTANCE}.js"
git add "$install_dir/config/manifest_${INSTANCE}.js"
git add "$install_dir/config/server_settings_${INSTANCE}.js"

[ -f "$install_dir/misc/influx_sealog/settings.py" ] && \
  cp "$install_dir/misc/influx_sealog/settings.py" "$install_dir/misc/influx_sealog/settings_${INSTANCE}.py" && \
  git add "$install_dir/misc/influx_sealog/settings_${INSTANCE}.py"

[ -f "$install_dir/misc/python_sealog/settings.py" ] && \
  cp "$install_dir/misc/python_sealog/settings.py" "$install_dir/misc/python_sealog/settings_${INSTANCE}.py" && \
  git add "$install_dir/misc/python_sealog/settings_${INSTANCE}.py"

[ -f "$install_dir/misc/slack_sealog/settings.py" ] && \
  cp "$install_dir/misc/slack_sealog/settings.py" "$install_dir/misc/slack_sealog/settings_${INSTANCE}.py" && \
  git add "$install_dir/misc/slack_sealog/settings_${INSTANCE}.py"

exit 0
HOOK

chmod +x .git/hooks/pre-commit

echo "Setting up git post-merge hook..."
cat > .git/hooks/post-merge << HOOK
#!/bin/bash

$install_dir/venv/bin/pip install -r $install_dir/requirements.txt
npm install

# Copy instance-named repo files back to working config filenames
cp "$install_dir/config/db_constants_${INSTANCE}.js"    "$install_dir/config/db_constants.js"
cp "$install_dir/config/email_settings_${INSTANCE}.js"  "$install_dir/config/email_settings.js"
cp "$install_dir/config/manifest_${INSTANCE}.js"        "$install_dir/config/manifest.js"
cp "$install_dir/config/server_settings_${INSTANCE}.js" "$install_dir/config/server_settings.js"

[ -f "$install_dir/misc/influx_sealog/settings_${INSTANCE}.py" ] && \
  cp "$install_dir/misc/influx_sealog/settings_${INSTANCE}.py" "$install_dir/misc/influx_sealog/settings.py"

[ -f "$install_dir/misc/python_sealog/settings_${INSTANCE}.py" ] && \
  cp "$install_dir/misc/python_sealog/settings_${INSTANCE}.py" "$install_dir/misc/python_sealog/settings.py"

[ -f "$install_dir/misc/slack_sealog/settings_${INSTANCE}.py" ] && \
  cp "$install_dir/misc/slack_sealog/settings_${INSTANCE}.py" "$install_dir/misc/slack_sealog/settings.py"

exit 0
HOOK

chmod +x .git/hooks/post-merge

# ---------------------------------------------------------------------------
# Supervisor config
# ---------------------------------------------------------------------------

echo "Building supervisor config file..."

if [ "$INSTANCE" = "FKt" ]; then
    cat > "$install_dir/sealog-server-FKt.conf" << 'EOF'
[program:sealog-server-FKt]
directory=/opt/sealog-server
command=node --env-file=.env server.js
redirect_stderr=true
stdout_logfile=/var/log/sealog-server-FKt_STDOUT.log
user=mt
autostart=true
autorestart=true

[program:sealog-asnap-FKt]
directory=/opt/sealog-server
command=/opt/sealog-server/venv/bin/python ./misc/sealog_asnap.py --interval 300
redirect_stderr=true
stdout_logfile=/var/log/sealog-asnap-FKt_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-aux-data-influx-FKt]
directory=/opt/sealog-server
command=/opt/sealog-server/venv/bin/python ./misc/sealog_aux_data_inserter_influx.py -f ./misc/sealog_influx_embed_FKt.yml
redirect_stderr=true
stdout_logfile=/var/log/sealog-aux-data-influx-FKt_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-aux-data-framegrab-vnc-FKt]
directory=/opt/sealog-server
command=/opt/sealog-server/venv/bin/python ./misc/sealog_aux_data_inserter_framegrab_vnc.py
environment=VNC_VIEWONLY="*****"
redirect_stderr=true
stdout_logfile=/var/log/sealog-aux-data-framegrab-vnc-FKt_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-cruise-sync-FKt]
directory=/opt/sealog-server
command=/opt/sealog-server/venv/bin/python ./misc/sealog_cruise_sync_FKt.py
redirect_stderr=true
stdout_logfile=/var/log/sealog-cruise-sync-FKt_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[group:sealog-FKt]
programs=sealog-server-FKt,sealog-asnap-FKt,sealog-aux-data-influx-FKt,sealog-aux-data-framegrab-vnc-FKt,sealog-cruise-sync-FKt
EOF

    sudo mv "$install_dir/sealog-server-FKt.conf" /etc/supervisor/conf.d/

else  # Sub
    cat > "$install_dir/sealog-server-Sub.conf" << 'EOF'
[program:sealog-server-Sub]
directory=/opt/sealog-server
command=node --env-file=.env server.js
redirect_stderr=true
stdout_logfile=/var/log/sealog-server-Sub_STDOUT.log
user=mt
autostart=true
autorestart=true

[program:sealog-asnap-Sub]
directory=/opt/sealog-server
command=/opt/sealog-server/venv/bin/python ./misc/sealog_asnap.py -i 10
redirect_stderr=true
stdout_logfile=/var/log/sealog-asnap-Sub_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-asnap-Sub-1Hz]
directory=/opt/sealog-server
command=/opt/sealog-server/venv/bin/python ./misc/sealog_asnap.py -i 1 -t 60
redirect_stderr=true
stdout_logfile=/var/log/sealog-asnap-Sub-1Hz_STDOUT.log
user=mt
autostart=false
autorestart=true
stopsignal=QUIT

[program:sealog-auto-actions-Sub]
directory=/opt/sealog-server
command=/opt/sealog-server/venv/bin/python ./misc/sealog_auto_actions_Sub.py
redirect_stderr=true
stdout_logfile=/var/log/sealog-auto-actions-Sub_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-aux-data-influx-Sub]
directory=/opt/sealog-server
command=/opt/sealog-server/venv/bin/python ./misc/sealog_aux_data_inserter_influx.py -f ./misc/sealog_influx_embed_Sub.yml
redirect_stderr=true
stdout_logfile=/var/log/sealog-aux-data-inserter-influx-Sub_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-aux-data-framegrab-Sub]
directory=/opt/sealog-server
command=/opt/sealog-server/venv/bin/python ./misc/sealog_aux_data_inserter_framegrab.py
redirect_stderr=true
stdout_logfile=/var/log/sealog-aux-data-inserter-framegrab-Sub_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[group:sealog-Sub]
programs=sealog-server-Sub,sealog-asnap-Sub,sealog-auto-actions-Sub,sealog-aux-data-influx-Sub,sealog-aux-data-framegrab-Sub
EOF

    sudo mv "$install_dir/sealog-server-Sub.conf" /etc/supervisor/conf.d/

else  # emp
    cat > "$install_dir/sealog-server-emp.conf" << 'EOF'
[program:sealog-server-emp]
directory=/opt/sealog-server
command=node --env-file=.env server.js
redirect_stderr=true
stdout_logfile=/var/log/sealog-server-emp_STDOUT.log
user=mt
autostart=true
autorestart=true

[program:sealog-asnap-emp]
directory=/opt/sealog-server
command=/opt/sealog-server/venv/bin/python ./misc/sealog_asnap.py -i 10
redirect_stderr=true
stdout_logfile=/var/log/sealog-asnap-emp_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-auto-actions-emp]
directory=/opt/sealog-server
command=/opt/sealog-server/venv/bin/python ./misc/sealog_auto_actions_emp.py
redirect_stderr=true
stdout_logfile=/var/log/sealog-auto-actions-emp_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[group:sealog-emp]
programs=sealog-server-emp,sealog-asnap-emp,sealog-auto-actions-emp
EOF

    sudo mv "$install_dir/sealog-server-emp.conf" /etc/supervisor/conf.d/
fi

# ---------------------------------------------------------------------------
# System prerequisites, Node.js
# ---------------------------------------------------------------------------

install_prereqs
install_mongo
install_node

# ---------------------------------------------------------------------------
# Config files and .env
# ---------------------------------------------------------------------------

echo "Setting up config files..."
.git/hooks/post-merge

if [ ! -f "$install_dir/.env" ]; then
    if [ -f "$install_dir/.env.dist" ]; then
        cp "$install_dir/.env.dist" "$install_dir/.env"
    else
        touch "$install_dir/.env"
    fi
    echo ""
    echo "=========================================================="
    echo "ACTION REQUIRED: Edit $install_dir/.env before starting"
    echo "the server. At minimum set:"
    echo "  SEALOG_INSTANCE_TYPE=${INSTANCE}"
    echo "  NODE_ENV=production"
    echo "  MONGO_URL=mongodb://localhost:27017/sealogDB_${INSTANCE}"
    echo "  SEALOG_SERVER_SECRET=<generated — see INSTALL.md>"
    echo "  SEALOG_SERVER_FILEPATH_ROOT=/opt/sealog-server/sealog-files"
    echo "=========================================================="
    echo ""
fi

# ---------------------------------------------------------------------------
# Python ancillary scripts
# ---------------------------------------------------------------------------

if [ ! -f "$install_dir/misc/sealog_asnap.py" ]; then
    echo "Setting up ASNAP script..."
    cp "$install_dir/misc/sealog_asnap.py.dist" "$install_dir/misc/sealog_asnap.py"
fi

# The external_calls API route always invokes misc/sealog_data_export.py.
# Create a symlink pointing to the instance-specific script so the route works.
echo "Setting up sealog_data_export.py symlink..."
if [ "$INSTANCE" = "Sub" ]; then
    ln -sf sealog_vehicle_data_export_Sub.py "$install_dir/misc/sealog_data_export.py"
elif [ "$INSTANCE" = "FKt" ]; then
    ln -sf sealog_vessel_data_export_FKt.py "$install_dir/misc/sealog_data_export.py"
elif [ "$INSTANCE" = "emp" ]; then
    ln -sf sealog_vehicle_data_export_emp.py "$install_dir/misc/sealog_data_export.py"
fi

# ---------------------------------------------------------------------------
# Activate supervisor
# ---------------------------------------------------------------------------

echo "Reloading supervisor..."
sudo supervisorctl reread
sudo supervisorctl update

echo ""
echo "Done. Next steps:"
echo "  1. Edit $install_dir/.env"
echo "  2. Edit config files (see INSTALL.md)"
echo "  3. sudo supervisorctl start sealog-${INSTANCE}:"
echo ""

cd "$current_dir"
