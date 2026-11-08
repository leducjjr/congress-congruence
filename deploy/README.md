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
scripts/publish_web.sh                  # if the panel or any page changed (builds the site)
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
sudo -u postgres createdb -O john congress_restore_test   # your login can't create databases
pg_restore --no-owner -d congress_restore_test ~/backups/congress-YYYY-MM-DD.dump
psql congress_restore_test -c "select count(*) from core.roll_call;"
sudo -u postgres dropdb congress_restore_test
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
   | survey-watch | `25 7 1 * *` | 1 day |
   | bills | `5 7 * * *` | 1 hour |

3. Add each check's ping URL to `.env`:

   ```
   HEALTHCHECK_BACKUP=https://hc-ping.com/your-uuid-1
   HEALTHCHECK_MEMBERS=https://hc-ping.com/your-uuid-2
   HEALTHCHECK_HOUSE=https://hc-ping.com/your-uuid-3
   HEALTHCHECK_SENATE_VOTEVIEW=https://hc-ping.com/your-uuid-4
   HEALTHCHECK_SURVEY_WATCH=https://hc-ping.com/your-uuid-5
   HEALTHCHECK_BILLS=https://hc-ping.com/your-uuid-6
   ```

Jobs report "started" and then "succeeded" or "failed" with their exit code.
No `.env` line means no reporting for that job; nothing else changes.

## New survey and Census releases

`survey-watch` runs on the 1st of each month. For surveys it never changes what
the panel shows. When the CES publishes a new year it downloads it, writes the inspection
report, and drafts `config/drafts/ces_<year>_items.yaml` listing every
support/oppose question about Congress with the closest-matching votes as
comments. When a year already loaded gets a new version, it says so.

It writes what needs attention to `logs/review_needed.txt`, and if `.env` has
`NOTIFY_URL` (an ntfy.sh topic, for example) sends a phone notification.

To act on a new year: review the draft with Claude or by hand, save it as
`config/ces_<year>_items.yaml`, then `ces link <year>` (check the matches) and
`ces load <year>`.

```bash
python -m congress_congruence.ingest.watch --list    # releases seen so far
```

The first run only records the releases that already exist.

**Census population** is different: once the Census Bureau publishes the next
American Community Survey 1-year release (usually September), the watcher loads
it automatically, since population figures need no judgment, and reports it in
the same log and notification. It needs `CENSUS_API_KEY` in `.env`; a missing or
expired key shows up as a failed run (and an alert, if alerts are set up).

## Loading the Program for Public Consultation surveys

```bash
git pull && pip install -r requirements.txt     # adds pypdf, for reading the PDFs
python -m congress_congruence.db migrate         # 006: survey organization, vote side, related votes
sudo systemctl restart congress-api && scripts/publish_web.sh
python -m congress_congruence.ingest.ppc fetch 2026
less logs/ppc_2026_review.txt                    # check PROBLEMS first, then the numbers
python -m congress_congruence.ingest.ppc link 2026
python -m congress_congruence.ingest.ppc load 2026
```

`fetch` reads only public PDFs; nothing reaches the panel until `load`.

## Feedback form

The Contact page's form posts to `/api/v1/feedback`, which emails the message from a send-only
mailbox (`feedback@`) to the project inbox and keeps nothing. Add to `.env` (see `.env.example`):

```
FEEDBACK_SMTP_USER=feedback@uscongressvsvoters.org
FEEDBACK_SMTP_PASSWORD=...
FEEDBACK_TO=contact@uscongressvsvoters.org
```

then `sudo systemctl restart congress-api`. Without these the form tells visitors to use email.
