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

## Loading earlier Congresses

Votes for earlier Congresses come from the same sources as today's (House Clerk files, Voteview
for the Senate). A House Congress is about 1,000–1,800 votes at one request a second, so allow an
hour or two per Congress; the Senate is one download each. Each House file is ~90 KB and is kept,
so check space first (`df -h ~`): budget ~150 MB of files and ~100 MB of database per Congress.

```bash
git pull
python -m congress_congruence.ingest.backfill 117 117          # try one Congress first
nohup python -m congress_congruence.ingest.backfill 110 116 > logs/backfill.log 2>&1 &
tail -f logs/backfill.log                                       # Ctrl+C stops watching, not the load
sudo systemctl restart congress-api && scripts/publish_web.sh   # once, for the seat history display
```

Stopping it (or a reboot) is harmless: run the same command again and it carries on.

## Adding earlier CES years

Once the votes of the matching Congresses are loaded (see above), prepare each past CES year for
review. This downloads each year's data file (100–800 MB), writes `logs/ces_<year>_inspect.txt`,
and drafts `config/drafts/ces_<year>_items.yaml` with the closest-matching votes as comments:

```bash
git pull
nohup python -m congress_congruence.ingest.watch --draft $(seq 2007 2023) > logs/ces_drafts.log 2>&1 &
tail -f logs/ces_drafts.log
tar czf ~/ces_drafts.tgz config/drafts logs/ces_*_inspect.txt     # one file to review
```

A person (or Claude) checks each draft, saves it as `config/ces_<year>_items.yaml`, and then
`python -m congress_congruence.ingest.ces link <year>` / `load <year>`.

## Loading state ballot-measure results

The results are typed into `config/ballot_<year>_items.yaml` (certified counts, with a link
per measure), so there is nothing to download.

```bash
git pull
python -m congress_congruence.db migrate          # 008: survey kind (survey | ballot), measure names
python -m congress_congruence.ingest.ballots link 2024   # check which Senate vote each item uses
python -m congress_congruence.ingest.ballots load 2024
sudo systemctl restart congress-api && scripts/publish_web.sh
```

## Feedback form

The Contact page's form posts to `/api/v1/feedback`, which emails the message from a send-only
mailbox (`feedback@`) to the project inbox and keeps nothing. Add to `.env` (see `.env.example`):

```
FEEDBACK_SMTP_USER=feedback@uscongressvsvoters.org
FEEDBACK_SMTP_PASSWORD=...
FEEDBACK_TO=contact@uscongressvsvoters.org
```

then `sudo systemctl restart congress-api`. Without these the form tells visitors to use email.

**Titan (Bluehost Professional Email) refuses logins from programs by default** (SMTP error 535 even
with the right password). In webmail, signed in as `feedback@`: Settings (gear) → **Enable Titan on
other apps**. Two-factor authentication must also be off for `feedback@` (it blocks other apps); keep
it on for `admin@` and `contact@`. To test the login without sending anything:

```bash
python -c "from congress_congruence import config; import os, smtplib, ssl; s = smtplib.SMTP_SSL('smtp.titan.email', 465, context=ssl.create_default_context(), timeout=20); s.login(os.environ['FEEDBACK_SMTP_USER'], os.environ['FEEDBACK_SMTP_PASSWORD']); print('login OK'); s.quit()"
```

**Copies to visitors.** When a visitor gives their email address, the form also emails them a copy
of what they sent, from "US Congress vs Voters", with replies going to `contact@` (Reply-To), so
their reply starts a thread in the inbox. Copies are limited to 2 an hour per address and 30 an hour in
all, so the form can't be used to flood someone.

The copy is sent from `feedback@` by default. To show `contact@` as the From address instead, the mail
service must let `feedback@` send as `contact@` (signing in as `contact@` itself isn't an option while it
has two-factor authentication, which it should keep). Test whether Titan allows it by sending one email
to yourself (replace the To address):

```bash
python - <<'PY'
from congress_congruence import config; import os, smtplib, ssl
from email.message import EmailMessage
m = EmailMessage(); m["From"] = "US Congress vs Voters <contact@uscongressvsvoters.org>"
m["To"] = "YOUR-OWN-ADDRESS@example.com"; m["Subject"] = "Send-as test"; m.set_content("Test of sending as contact@.")
s = smtplib.SMTP_SSL('smtp.titan.email', 465, context=ssl.create_default_context(), timeout=20)
s.login(os.environ['FEEDBACK_SMTP_USER'], os.environ['FEEDBACK_SMTP_PASSWORD']); s.send_message(m); s.quit(); print('accepted')
PY
```

If it prints `accepted` and the email arrives (check spam too), add `FEEDBACK_COPY_FROM=contact@uscongressvsvoters.org`
to `.env` and restart the API. If Titan refuses ("sender address rejected" or similar), leave it unset.

Save the password with a prompt (not in shell history), quoted so any character works:

```bash
python - <<'PY'
import getpass, re
from pathlib import Path
p = Path('.env')
keep = [l for l in p.read_text().splitlines() if not re.match(r'(FEEDBACK_SMTP_USER|FEEDBACK_SMTP_PASSWORD|FEEDBACK_TO)=', l)]
pw = getpass.getpass('feedback@ password: ').replace('\\', '\\\\').replace("'", "\\'")
keep += ['FEEDBACK_SMTP_USER=feedback@uscongressvsvoters.org', f"FEEDBACK_SMTP_PASSWORD='{pw}'", 'FEEDBACK_TO=contact@uscongressvsvoters.org']
p.write_text('\n'.join(keep) + '\n')
print('saved')
PY
```
