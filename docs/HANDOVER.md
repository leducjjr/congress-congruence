# Handover

What changes hands when the site moves from its current maintainer to a new one, and what to do about
each. This repository is public: account names, passwords and private email addresses are deliberately
not written here. The current maintainer hands those over directly.

## Accounts and resources

| Item | Where it is | Handover step |
| --- | --- | --- |
| Source code | GitHub repo `leducjjr/congress-congruence`, under the maintainer's personal account | Create a GitHub organization for the project and transfer the repo to it (Settings → Transfer); GitHub redirects the old URL. Make the new maintainer an owner. Re-create the "Protect main" ruleset, secret scanning and push protection if needed. Update the source link in `site/site.yaml`. |
| Domains | uscongressvsvoters.org (primary), .com and .online, registered at Bluehost | Transfer to the new maintainer's registrar account, or keep the account and add them. DNS also holds the email records (MX, SPF, DKIM, DMARC) and the Google Search Console TXT record. |
| Server | Bluehost self-managed VPS (address in `deploy/README.md`), Linux user `john`. It also hosts the maintainer's other projects, including a temporary demo of another app | Best: build a new server for the site from `deploy/README.md` and move the database (`pg_dump`/`pg_restore`), so the new maintainer gets a server of their own. Then point the DNS A records at it. |
| Email | Bluehost Professional Email (Titan) on the .org: public `contact@` (aliases corrections@, press@, privacy@, security@), send-only `feedback@`, and a private admin mailbox | The admin mailbox is the login and recovery address for the hosting, code, data and monitoring accounts. Hand it over, or change each account's email to the new maintainer's before the switch. |
| Data API keys | Congress.gov (api.data.gov) and Census keys in the server's `.env` | The new maintainer signs up for their own (free) keys. |
| senate.gov access | senate.gov allowed the current server's address on Nov 10, 2026 | A new server address needs a new request to the Senate webmaster; until then Senate votes come from Voteview. |
| Survey data permissions | AP-NORC (AP VoteCast) permission requested Nov 2026, pending | Tell AP-NORC about the change of maintainer if granted. |
| Monitoring | healthchecks.io checks and an ntfy.sh topic, if set up (`deploy/README.md`) | Re-create under the new maintainer's account, update `.env`. |
| Search engines | Google Search Console property; IndexNow key in `.env` | Add the new maintainer as an owner in Search Console. The IndexNow key can stay. |
| Read-only deploy key | On the GitHub repo, used by the server to pull code | Replace with the new server's key. |
| Name on the site | About, Press and How it was built pages credit the maintainer by name | Update the pages, with a What's new entry. |
| `security.txt` | `site/static/.well-known/security.txt`, Expires 2027-11-01 | Renew yearly; check the contact address. |

## Handover checklist

- [ ] Repo transferred to a project organization; new maintainer is an owner.
- [ ] New maintainer can run the tests and the site locally (README.md).
- [ ] Server: new server built, or new maintainer given their own SSH key and sudo login; previous
      maintainer's access removed.
- [ ] All passwords and secrets changed after the handover: database logins, mailbox passwords,
      `.env` values, dev-site password, API keys.
- [ ] Domains, email and account recovery addresses moved to the new maintainer.
- [ ] Site pages updated to name the new maintainer, with a What's new entry.
- [ ] `docs/DECISIONS.md` and `PROJECT_NOTES.md` reviewed together.
