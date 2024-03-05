# Installation Instructions

These proceedures are reasonably tested but not 100%.

## Installing for the first time

### Create the mt user

```
sudo adduser mt
sudo passwd mt
sudo usermod -aG sudo mt
```

### Switch to the mt user and mt home dir
```
su mt
cd
```

### Clone the "soi" branch of the schmidtocean/sealog-server repository

```
git clone -b soi https://github.com/schmidtocean/sealog-server.git
```

### Move installation to final installation location and cd to that directory

##### For Sealog-Sub
```
sudo mv ~/sealog-server /opt/sealog-server-Sub
cd /opt/sealog-server-Sub`
```

##### For Sealog-FKt
```
sudo mv ~/sealog-server /opt/sealog-server-FKt
cd /opt/sealog-server-FKt`
```

### Run the installation script

```
bash ./utils/install.sh
```

You will be asked which type of install (Sealog-Sub vs Sealog-FKt) and the target invironment (development vs production).  This script will install MongoDB, NodeJS and the python virtual env if any of these are NOT already installed.

## Updating from repo

To update an existing instance from the repo:
```
su mt
cd /opt/sealog-server-Sub # or /opt/sealog-server-FKt
bash ./utils/install.sh
```

You will be asked the same questions as during the initial install.  BE SURE TO ANSWER THOSE QUESTIONS CORRECTLY.

**If there were code changes that affected running services like the sealog-server or the bots you will need to restart those services via supervisorctl.  i.e.:**

```
sudo supervisorctl restart sealog-Sub:sealog-server-Sub
```

You and restart all the services for an instance via:
```
sudo supervisorctl restart sealog-Sub:*
```
or
```
sudo supervisorctl restart sealog-FKt:*
```
