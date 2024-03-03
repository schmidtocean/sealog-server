#!/bin/bash

# Get the current directory
current_dir=$(pwd)

# Function to handle errors
handle_error() {
    echo "Error occurred in script at line $1."
    # You can add additional error handling logic here
    cd $current_dir
    exit 1
}

# Set up error handling
trap 'handle_error $LINENO' ERR

# Get the directory of the script
script_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "Script directory is: $script_dir"

# Get the parent directory
install_dir="$(dirname "$script_dir")"
echo "Install directory is: $install_dir"

install_prereqs() {
    echo "Installing prerequists"
    sudo apt install gnupg wget apt-transport-https ca-certificates software-properties-common python3-venv
}

install_mongo() {
    which mongod > /dev/null
    if [ ! -z $? ]; then
        echo "Installing MongoDB"
        curl -fsSL https://pgp.mongodb.com/server-6.0.asc |  sudo gpg -o /usr/share/keyrings/mongodb-server-6.0.gpg --dearmor
        echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/6.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-6.0.list
        sudo apt-get update
        sudo apt-get install mongodb-org
        echo "Starting MongoDB"
        sudo systemctl start mongod
        echo "Configuring MongoDB to autostart at boot"
        sudo systemctl enable mongod
    fi
}

install_node() {

    which node > /dev/null
    if [ ! -z $? ]; then
        NODE_INSTALL_PWD=`pwd`.
        cd ~
        echo "Installing NodeJS"
        wget -qO- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
        
        export NVM_DIR="$HOME/.nvm"
        [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
        [ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
        
        nvm install --lts
        NODE_VERSION=`node -v`
        sudo ln -s $HOME/.nvm/versions/node/$NODE_VERSION/bin/npm /usr/local/bin/
        sudo ln -s $HOME/.nvm/versions/node/$NODE_VERSION/bin/node /usr/local/bin/

        cd $NODE_INSTALL_PWD
    fi
}

cd $install_dir

if [ ! -d venv ]; then
    echo "Creating python virtual environment"
    python3 -m venv venv
fi

echo "Activating python virtual environment"
source venv/bin/activate

echo "Choose an option:"
echo "1. Sealog-FKt"
echo "2. Sealog-Sub"

read -p "Enter your choice (1 or 2): " choice

case $choice in
    1)
        echo "You chose Sealog-FKt."

        echo "Setting up git pre-commit hook"
        cat <<EOF > .git/hooks/pre-commit
#!/bin/bash

# This is the pre-commit hook

# Update pip requirements file
$install_dir/venv/bin/pip freeze > $install_dir/requirements.txt
git add "$install_dir/requirements.txt"

# Copy production config files to their repo filenames
cp "$install_dir/config/db_constants.js" "$install_dir/config/db_constants_FKt.js"
cp "$install_dir/config/email_constants.js" "$install_dir/config/email_constants_FKt.js"
cp "$install_dir/config/manifest.js" "$install_dir/config/manifest_FKt.js"
cp "$install_dir/config/path_constants.js" "$install_dir/config/path_constants_FKt.js"
cp "$install_dir/config/secret.js" "$install_dir/config/secret_FKt.js"
cp "$install_dir/misc/influx_sealog/settings.py" "$install_dir/misc/influx_sealog/settings_FKt.py"
cp "$install_dir/misc/python_sealog/settings.py" "$install_dir/misc/python_sealog/settings_FKt.py"


# Stage the changes
git add "$install_dir/config"
git add "$install_dir/misc/influx_sealog/settings_FKt.py"
git add "$install_dir/misc/python_sealog/settings_FKt.py"

# Continue with the commit
exit 0
EOF

        chmod +x .git/hooks/pre-commit

        echo "Setting up git post-merge hook"
        cat <<EOF > .git/hooks/post-merge
#!/bin/bash

# This is the post-merge hook

$install_dir/venv/bin/pip install -r $install_dir/requirements.txt

npm install

# Copy repo config files to their production filenames
cp "$install_dir/config/db_constants_FKt.js" "$install_dir/config/db_constants.js"
cp "$install_dir/config/email_constants_FKt.js" "$install_dir/config/email_constants.js"
cp "$install_dir/config/manifest_FKt.js" "$install_dir/config/manifest.js"
cp "$install_dir/config/path_constants_FKt.js" "$install_dir/config/path_constants.js"
cp "$install_dir/config/secret_FKt.js" "$install_dir/config/secret.js"
cp "$install_dir/misc/influx_sealog/settings_FKt.py" "$install_dir/misc/influx_sealog/settings.py"
cp "$install_dir/misc/python_sealog/settings_FKt.py" "$install_dir/misc/python_sealog/settings.py"
cp "$install_dir/init_data/system_templates_FKt.json" "$install_dir/init_data/system_templates.json"


# Continue with the merge
exit 0
EOF

        chmod +x .git/hooks/post-merge

        echo "Building supervisor config file"
        cat <<EOF > $install_dir/sealog-server-FKt.conf
[program:sealog-server-FKt]
directory=$install_dir
command=node server.js
environment=NODE_ENV="production"
redirect_stderr=true
stdout_logfile=/var/log/sealog-server-FKt_STDOUT.log
user=mt
autostart=true
autorestart=true

[program:sealog-asnap-FKt]
directory=$install_dir
command=$install_dir/venv/bin/python ./misc/sealog_asnap.py --interval 300
redirect_stderr=true
stdout_logfile=/var/log/sealog-asnap-FKt_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-aux-data-influx-FKt]
directory=$install_dir
command=$install_dir/venv/bin/python ./misc/sealog_aux_data_inserter_influx.py -f ./misc/sealog_influx_embed_FKt.yml
redirect_stderr=true
stdout_logfile=/var/log/sealog-aux-data-influx-FKt_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-cruise-sync-FKt]
directory=$install_dir
command=$install_dir/venv/bin/python ./misc/sealog_cruise_sync_FKt.py
redirect_stderr=true
stdout_logfile=/var/log/sealog-cruise-sync-FKt_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-post-cruise-data-export-FKt]
directory=$install_dir
command=$install_dir/venv/bin/python ./misc/sealog_vessel_data_export.py
redirect_stderr=true
stdout_logfile=/var/log/sealog-data-export-FKt_STDOUT.log
user=mt
autostart=false
autorestart=false
stopsignal=QUIT

[group:sealog-FKt]
programs=sealog-server-FKt,sealog-asnap-FKt,sealog-aux-data-influx-FKt,sealog-cruise-sync-FKt

EOF
        sudo mv "$install_dir/sealog-server-FKt.conf" /etc/supervisor/conf.d
        ;;
    2)
        echo "You chose Sealog-Sub."

        echo "Setting up git pre-commit hook"
        cat <<EOF > .git/hooks/pre-commit
#!/bin/bash

# This is the pre-commit hook

# Update pip requirements file
$install_dir/venv/bin/pip freeze > $install_dir/requirements.txt
git add "$install_dir/requirements.txt"

# Copy production config files to their repo filenames
cp "$install_dir/config/db_constants.js" "$install_dir/config/db_constants_Sub.js"
cp "$install_dir/config/email_constants.js" "$install_dir/config/email_constants_Sub.js"
cp "$install_dir/config/manifest.js" "$install_dir/config/manifest_Sub.js"
cp "$install_dir/config/path_constants.js" "$install_dir/config/path_constants_Sub.js"
cp "$install_dir/config/secret.js" "$install_dir/config/secret_Sub.js"
cp "$install_dir/misc/influx_sealog/settings.py" "$install_dir/misc/influx_sealog/settings_Sub.py"
cp "$install_dir/misc/python_sealog/settings.py" "$install_dir/misc/python_sealog/settings_Sub.py"

# Stage the changes
git add "$install_dir/config"
git add "$install_dir/misc/influx_sealog/settings_Sub.py"
git add "$install_dir/misc/python_sealog/settings_Sub.py"

# Continue with the commit
exit 0
EOF

        chmod +x .git/hooks/pre-commit

        echo "Setting up git post-merge hook"
        cat <<EOF > .git/hooks/post-merge
#!/bin/bash

# This is the post-merge hook

$install_dir/venv/bin/pip install -r $install_dir/requirements.txt

npm install

# Copy repo config files to their production filenames
cp "$install_dir/config/db_constants_Sub.js" "$install_dir/config/db_constants.js"
cp "$install_dir/config/email_constants_Sub.js" "$install_dir/config/email_constants.js"
cp "$install_dir/config/manifest_Sub.js" "$install_dir/config/manifest.js"
cp "$install_dir/config/path_constants_Sub.js" "$install_dir/config/path_constants.js"
cp "$install_dir/config/secret_Sub.js" "$install_dir/config/secret.js"
cp "$install_dir/misc/influx_sealog/settings_Sub.py" "$install_dir/misc/influx_sealog/settings.py"
cp "$install_dir/misc/python_sealog/settings_Sub.py" "$install_dir/misc/python_sealog/settings.py"
cp "$install_dir/init_data/system_templates_Sub.json" "$install_dir/init_data/system_templates.json"

# Continue with the merge
exit 0
EOF

        chmod +x .git/hooks/post-merge

        echo "Building supervisor config file"
        sudo cat <<EOF > $install_dir/sealog-server-Sub.conf
[program:sealog-server-Sub]
directory=$install_dir
command=node server.js
environment=NODE_ENV="production"
redirect_stderr=true
stdout_logfile=/var/log/sealog-server-Sub_STDOUT.log
user=mt
autostart=true
autorestart=true

[program:sealog-asnap-Sub]
directory=$install_dir
command=$install_dir/venv/bin/python ./misc/sealog_asnap.py -i 10
redirect_stderr=true
stdout_logfile=/var/log/sealog-asnap-Sub_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-asnap-Sub-1Hz]
directory=$install_dir
command=$install_dir/venv/bin/python ./misc/sealog_asnap.py -i 1 -t 60
redirect_stderr=true
stdout_logfile=/var/log/sealog-asnap-Sub_STDOUT.log
user=mt
autostart=false
autorestart=true
stopsignal=QUIT

[program:sealog-auto-actions-Sub]
directory=$install_dir
command=$install_dir/venv/bin/python ./misc/sealog_auto_actions_Sub.py
redirect_stderr=true
stdout_logfile=/var/log/sealog-auto-actions-Sub_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-aux-data-influx-Sub]
directory=$install_dir
command=$install_dir/venv/bin/python ./misc/sealog_aux_data_inserter_influx.py -f ./misc/sealog_influx_embed_Sub.yml
redirect_stderr=true
stdout_logfile=/var/log/sealog-aux-data-inserter-influx-Sub_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-aux-data-framegrab-Sub]
directory=$install_dir
command=$install_dir/venv/bin/python ./misc/sealog_aux_data_inserter_framegrab.py
redirect_stderr=true
stdout_logfile=/var/log/sealog-aux-data-inserter-framegrab-Sub_STDOUT.log
user=mt
autostart=true
autorestart=true
stopsignal=QUIT

[program:sealog-post-dive-data-export-Sub]
directory=$install_dir
command=$install_dir/venv/bin/python ./misc/sealog_vehicle_data_export.py
redirect_stderr=true
stdout_logfile=/var/log/sealog-data-export_STDOUT.log
user=mt
autostart=false
autorestart=false
stopsignal=QUIT

[program:sealog-post-cruise-data-export-Sub]
directory=$install_dir
command=$install_dir/venv/bin/python ./misc/sealog_vehicle_data_export.py -c
redirect_stderr=true
stdout_logfile=/var/log/sealog-data-export_STDOUT.log
user=mt
autostart=false
autorestart=false
stopsignal=QUIT

[group:sealog-Sub]
programs=sealog-server-Sub,sealog-asnap-Sub,sealog-auto-actions-Sub,sealog-aux-data-influx-Sub,sealog-aux-data-framegrab-Sub

EOF
        sudo mv "$install_dir/sealog-server-Sub.conf" /etc/supervisor/conf.d
        ;;
    *)
        echo "Invalid choice. Please enter 1 or 2."
        ;;
esac


echo "Development or production environment:"
echo "1. Development"
echo "2. Production"

read -p "Enter your choice (1 or 2): " choice

case $choice in
    1)
    sed -i "s/settings_FKt/settings_devel_FKt/g" "$install_dir/.git/hooks/pre-commit"
    sed -i "s/settings_FKt/settings_devel_FKt/g" "$install_dir/.git/hooks/post-merge"
    sed -i "s/settings_Sub/settings_devel_Sub/g" "$install_dir/.git/hooks/pre-commit"
    sed -i "s/settings_Sub/settings_devel_Sub/g" "$install_dir/.git/hooks/post-merge"
    ;;

    # 2)

    # ;;
esac

install_prereqs
install_node

echo "Setup Sealog config files"
.git/hooks/post-merge

if [ ! -f "$install_dir/misc/sealog_asnap.py" ]; then
    echo "Setup asnap bot"
    cp "$install_dir/misc/sealog_asnap.py.dist" "$install_dir/misc/sealog_asnap.py"
fi

echo "Refreshing supervisor processes"
sudo supervisorctl reread
sudo supervisorctl update

echo "Done"
cd $current_dir
