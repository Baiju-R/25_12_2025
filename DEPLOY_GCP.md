# Deploy to Google Cloud (Cloud Run)

This repo is already set up for container deployment (Gunicorn + WhiteNoise). The recommended path on GCP is **Cloud Run**.

## 0) Prereqs
- Install the Google Cloud CLI: https://cloud.google.com/sdk/docs/install
- Login and pick a project:
  - `gcloud auth login`
  - `gcloud config set project YOUR_GCP_PROJECT_ID`

Enable required APIs:

- `gcloud services enable run.googleapis.com cloudbuild.googleapis.com`

## 1) Production env vars
Cloud Run will run with `DEBUG=false`. Set these on deploy:

- `SECRET_KEY`: required (do not use the default fallback in production)
- `DEBUG=false`
- `ALLOWED_HOSTS`: recommended: `.a.run.app,localhost,127.0.0.1`

Optional but common:
- `DATABASE_URL`: recommended for real deployments (Cloud SQL Postgres)
- `CSRF_TRUSTED_ORIGINS`: if you use a custom domain (e.g. `https://yourdomain.com`)

## 2) Deploy to Cloud Run
From the repo root:

- `gcloud run deploy bloodbridge \
    --source . \
    --region asia-south1 \
    --allow-unauthenticated \
    --set-env-vars SECRET_KEY=CHANGE_ME,DEBUG=false,ALLOWED_HOSTS=.a.run.app`

After deploy, Cloud Run prints a service URL like `https://...a.run.app`.

## 3) Database notes (important)
### SQLite (default)
By default this project uses SQLite. On Cloud Run this is **not suitable for production** because:
- data won’t be shared across instances
- data can be lost on restart/redeploy

It can be OK for a demo.

### Recommended: Cloud SQL Postgres (persistent data + logins)
This project already includes `dj-database-url` + `psycopg2-binary`.

If you want your **current data and login credentials** to stay available (and survive restarts), move to Cloud SQL.

High-level flow:
1) Create a Cloud SQL Postgres instance + DB + user
2) Attach the Cloud SQL instance to Cloud Run
3) Set `DATABASE_URL` to Postgres
4) Run migrations once
5) (Optional) import your existing SQLite data into Postgres

Example `DATABASE_URL` for Cloud Run + Cloud SQL via Unix socket:

- `DATABASE_URL=postgres://DB_USER:DB_PASSWORD@/DB_NAME?host=/cloudsql/INSTANCE_CONNECTION_NAME`

Where `INSTANCE_CONNECTION_NAME` looks like:

- `bloodbridge-prod:asia-south1:YOUR_INSTANCE`

Typical approach:
- Create a Cloud SQL Postgres instance
- Set `DATABASE_URL` to a Postgres URL
- Configure Cloud Run to connect to Cloud SQL (Cloud SQL connector)

### Importing existing SQLite data (optional)
If your current `db.sqlite3` contains demo/real records you want to preserve:

1) Export from SQLite locally:
- `py manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.Permission > data.json`

2) After Cloud Run is pointed at Postgres and migrations have run, load into Postgres:
- `py manage.py loaddata data.json`

Note: if you have a lot of data, we can do this via a one-off Cloud Run Job instead of locally.

### Non-interactive admin login (recommended)
On Cloud Run you can’t use interactive `createsuperuser`. This repo includes a command to provision an admin account from env vars:

- Set `PROVISION_ADMIN_ON_STARTUP=true`
- Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`

Then the container will run `python manage.py provision_admin` at startup (after migrations) to ensure the admin login exists.

If you tell me your preferred region and DB name/user, I can add an exact step-by-step Cloud SQL + Cloud Run config section.

## 4) Static/media
- Static files are served by WhiteNoise (built at image build time via `collectstatic`).
- User uploads in `media/` are not durable on Cloud Run. For production, store uploads in **Cloud Storage**.

## 5) Celery / Redis (optional)
If you want background SMS jobs:
- Run Redis (recommended: Memorystore for Redis)
- Deploy a separate worker service using the same image but with a different command.

For a simple deployment without Redis/workers, you can set:
- `CELERY_TASK_ALWAYS_EAGER=true` (runs `.delay()` tasks inline in the web request)

Note: On Cloud Run, this repo defaults to eager mode automatically unless you explicitly set `CELERY_TASK_ALWAYS_EAGER=false`.

