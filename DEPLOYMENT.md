# Deployment Notes

## Local Migrations (SQLite)
Set the app module and run the migration commands:

```powershell
$env:FLASK_APP = "app.py"
flask db init        # first time only
flask db migrate -m "add constraint"
flask db upgrade
```

## Environment Variables
Set these in your local `.env` or host environment:

- `DATABASE_URL`: Postgres connection string for production.
  - Example: `postgresql://user:pass@host:5432/dbname`
- `SESSION_SECRET`: Flask session secret key.

If `DATABASE_URL` is not set, the app falls back to SQLite at `instance/cell_tracker.db`.

## Setup (First Admin User)
Create the first admin user once per environment:

```bash
export FLASK_APP=app.py
flask bootstrap-admin --username admin --password "your-strong-password"
```

To create additional users (admin or user):

```bash
flask create-admin --username user1 --password "your-password" --role user
```

You can link a user to a leader later by setting `leader_id` in the database.

### Git Bash (Local)
You can load a local `.env` file like this:

```bash
set -a
source .env
set +a
```

## Running `db upgrade` On The Host
Run the upgrade after deploying new code or migrations:

```bash
export FLASK_APP=app.py
export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
flask db upgrade
```

For Windows hosts:

```powershell
$env:FLASK_APP = "app.py"
$env:DATABASE_URL = "postgresql://user:pass@host:5432/dbname"
flask db upgrade
```

## One-Command Deploy (Git Bash)
Use the helper script (edit values and restart command first):

```bash
./scripts/deploy_and_migrate.sh
```
