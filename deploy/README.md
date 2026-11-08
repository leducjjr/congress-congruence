# Deploying the dev site

What you end up with: `https://dev.<your domain>` shows the panel page behind
a password, and `https://dev.<your domain>/api/v1/...` serves the API.

```
browser ──HTTPS──> nginx ──/───────> /var/www/congress-dev   (panel files)
                         └─/api/──> uvicorn on 127.0.0.1:8000 (API, read-only DB login)
```

Run everything as `john` from `~/congress-congruence`, with the project's Python
active (`source .venv/bin/activate`).

## 0. DNS (once)

In Bluehost's DNS settings for your domain, add an **A record**: host `dev`,
value `162.214.171.209`. Wait until this shows the server's address
(usually minutes, sometimes a few hours):

```bash
getent hosts dev.yourdomain.org
```

## 1. Set your domain name for the commands below

```bash
DEV_HOST=dev.yourdomain.org        # change this
```

## 2. Install the web server and tools

```bash
git pull
pip install -r requirements.txt
sudo apt install -y nginx apache2-utils certbot python3-certbot-nginx
sudo ufw allow 'Nginx Full'
```

## 3. A database login that can only read

```bash
API_PW=$(python3 -c "import secrets; print(secrets.token_hex(24))")
sudo -u postgres psql congress_dev <<SQL
create role ccapi login password '$API_PW';
grant connect on database congress_dev to ccapi;
grant usage on schema core to ccapi;
grant select on all tables in schema core to ccapi;
alter default privileges for role john in schema core grant select on tables to ccapi;
SQL
echo "API_DATABASE_URL=postgresql://ccapi:$API_PW@localhost/congress_dev" >> .env
chmod 600 .env
unset API_PW
```

The password lives only in `.env`, which only `john` can read.

## 4. Start the API as a service

```bash
sudo cp deploy/congress-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now congress-api
curl -s localhost:8000/v1/health | head -c 300; echo
```

## 5. Publish the panel and set up nginx

```bash
scripts/publish_web.sh
sed "s/dev.example.org/$DEV_HOST/" deploy/nginx-dev.conf | sudo tee /etc/nginx/sites-available/congress-dev >/dev/null
sudo ln -sf /etc/nginx/sites-available/congress-dev /etc/nginx/sites-enabled/congress-dev
sudo rm -f /etc/nginx/sites-enabled/default
sudo htpasswd -c /etc/nginx/congress-dev.htpasswd john      # choose the dev-site password
sudo nginx -t && sudo systemctl reload nginx
```

## 6. HTTPS

```bash
sudo certbot --nginx -d "$DEV_HOST" --redirect --agree-tos -m you@example.com --no-eff-email
```

Use your own email address; Let's Encrypt only uses it for expiry warnings.
Certificates renew automatically.

Open `https://dev.yourdomain.org`, sign in with `john` and the dev-site password.

## Later updates

```bash
git pull
pip install -r requirements.txt
sudo systemctl restart congress-api     # if API code changed
scripts/publish_web.sh                  # if panel files changed
```

## If something's wrong

```bash
sudo systemctl status congress-api        # is the API running?
sudo journalctl -u congress-api -n 50     # its recent log
sudo tail -20 /var/log/nginx/error.log    # web server errors
```

## Backups

`scripts/run_job.sh backup` (scheduled daily at 05:40 UTC) writes
`~/backups/congress-YYYY-MM-DD.dump`, checks it's readable, and keeps 14 days.

Test a restore now and then, into a scratch database:

```bash
createdb congress_restore_test
pg_restore --no-owner -d congress_restore_test ~/backups/congress-YYYY-MM-DD.dump
psql congress_restore_test -c "select count(*) from core.roll_call;"
dropdb congress_restore_test
```

These copies are on the same server. To keep one somewhere else, copy it to
your PC from PowerShell every week or two:

```powershell
scp john@162.214.171.209:backups/congress-YYYY-MM-DD.dump $HOME\Documents\
```

## Alerts (healthchecks.io)

Each scheduled job can report to healthchecks.io, which emails you when a job
fails or doesn't report on time (which also catches the server being down).

1. Sign up at https://healthchecks.io (free plan).
2. Create one check per job, with these schedules (cron, UTC) and a grace time:

   | Check name | Schedule | Grace |
   | --- | --- | --- |
   | backup | `40 5 * * *` | 1 hour |
   | members | `10 6 * * *` | 1 hour |
   | house | `17 */2 * * *` | 1 hour |
   | senate-voteview | `40 6 * * *` | 1 hour |

3. Add each check's ping URL to `.env`:

   ```
   HEALTHCHECK_BACKUP=https://hc-ping.com/your-uuid-1
   HEALTHCHECK_MEMBERS=https://hc-ping.com/your-uuid-2
   HEALTHCHECK_HOUSE=https://hc-ping.com/your-uuid-3
   HEALTHCHECK_SENATE_VOTEVIEW=https://hc-ping.com/your-uuid-4
   ```

Jobs report "started" and then "succeeded" or "failed" with their exit code.
No `.env` line means no reporting for that job; nothing else changes.
