# Deploy on a VM with persistent SQLite (keeps all current data + logins)

If your #1 requirement is that **all current data and login credentials remain available** on the hosted site, then **Cloud Run + SQLite is not the right fit** (Cloud Run filesystem is ephemeral).

This guide deploys the same app on a single **Compute Engine VM** using Docker + a persistent SQLite file on disk.

## What you get
- Same UI + same Django code
- SQLite stored at `./data/db.sqlite3` on the VM (persistent)
- Your existing users/passwords remain valid (because you copy your current `db.sqlite3`)

## 0) Create a VM
Pick a zone (example uses `asia-south1-c`).

- `gcloud config set project bloodbridge-prod`
- `gcloud compute instances create bloodbridge-vm \
    --zone=asia-south1-c \
    --machine-type=e2-medium \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --tags=http-server`

Open port 80:
- `gcloud compute firewall-rules create allow-http-80 \
    --allow=tcp:80 \
    --target-tags=http-server`

## 1) Install Docker on the VM
SSH in:
- `gcloud compute ssh bloodbridge-vm --zone=asia-south1-c`

Install Docker (Debian 12):
- `sudo apt-get update`
- `sudo apt-get install -y ca-certificates curl gnupg`
- `sudo install -m 0755 -d /etc/apt/keyrings`
- `curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg`
- `echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null`
- `sudo apt-get update`
- `sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`
- `sudo usermod -aG docker $USER`

Log out and back in for group changes to apply.

## 2) Copy the project to the VM
On the VM:
- `git clone https://github.com/Baiju-R/25_12_2025.git bloodbridge`
- `cd bloodbridge`

## 3) Copy your CURRENT SQLite + uploads
On your laptop (this repo folder), copy:
- `db.sqlite3`
- `media/` (if you have uploads you need to keep)

To the VM (recommended paths used by `docker-compose.sqlite.yml`):
- `gcloud compute scp db.sqlite3 bloodbridge-vm:~/bloodbridge/data/db.sqlite3 --zone=asia-south1-c`
- `gcloud compute scp --recurse media bloodbridge-vm:~/bloodbridge/media --zone=asia-south1-c`

On the VM, ensure folders exist:
- `mkdir -p ~/bloodbridge/data ~/bloodbridge/media`

## 4) Set production env vars
Edit `docker-compose.sqlite.yml` on the VM and set:
- `SECRET_KEY` (required)
- `ALLOWED_HOSTS` (set to the VM external IP or your domain)

Optional admin provisioning (non-interactive):
- set `PROVISION_ADMIN_ON_STARTUP=true`
- set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`

## 5) Start the app
On the VM:
- `cd ~/bloodbridge`
- `docker compose -f docker-compose.sqlite.yml up -d --build`

## 6) Verify
- Open `http://<VM_EXTERNAL_IP>/`
- Your existing logins should work exactly the same.

## Notes (important)
- This is a **single-server** setup. SQLite works well here, but scaling to multiple instances later will require moving to Postgres (Cloud SQL).
- Backups: copy `~/bloodbridge/data/db.sqlite3` regularly (or snapshot the VM disk).
