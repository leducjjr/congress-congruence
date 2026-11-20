# Handover

What changes hands when the site moves from its current maintainer to a new one, and what to do about
each. This repository is public: account names, passwords and private email addresses are deliberately
not written here. The current maintainer hands those over directly.

## Accounts and resources

| Item | Where it is | Handover step |
| --- | --- | --- |
| Source code | GitHub repo `uscongressvsvoters/congress-congruence`, in the project's own GitHub organization (moved there Nov 20, 2026; the old `leducjjr/...` address redirects). The Claude GitHub app is installed on the organization for that repo | Invite the new maintainer to the `uscongressvsvoters` organization as an **Owner** (People → Invite member). Check that the "Protect main" ruleset still lets Repository admin and Organization admin bypass. |
| Domains | uscongressvsvoters.org (primary), .com and .online, registered at Bluehost | Transfer to the new maintainer's registrar account, or keep the account and add them. DNS also holds the email records (MX, SPF, DKIM, DMARC) and the Google Search Console TXT record. |
| Server | Bluehost self-managed VPS (address in `deploy/README.md`), Linux user `john`. It also hosts the maintainer's other projects, including a temporary demo of another app | Best: build a new server for the site from `deploy/README.md` and move the database (`pg_dump`/`pg_restore`), so the new maintainer gets a server of their own. Then point the DNS A records at it. |
| Email | Bluehost Professional Email (Titan) on the .org: public `contact@` (aliases corrections@, press@, privacy@, security@), send-only `feedback@`, and a private admin mailbox | The admin mailbox is the login and recovery address for the hosting, code, data and monitoring accounts. Hand it over, or change each account's email to the new maintainer's before the switch. |
| Data API keys | Congress.gov (api.data.gov) and Census keys in the server's `.env` | The new maintainer signs up for their own (free) keys. |
| senate.gov access | senate.gov allowed the current server's address on Nov 10, 2026 | A new server address needs a new request to the Senate webmaster; until then Senate votes come from Voteview. |
| Survey data permissions | AP-NORC (AP VoteCast) permission requested Nov 2026, pending | Tell AP-NORC about the change of maintainer if granted. |
| Monitoring | healthchecks.io checks and an ntfy.sh topic, if set up (`deploy/README.md`) | Re-create under the new maintainer's account, update `.env`. |
| Search engines | Google Search Console property; IndexNow key in `.env` | Add the new maintainer as an owner in Search Console. The IndexNow key can stay. |
| Off-server backups | The server keeps 14 nightly backups in `~/backups`; the maintainer's laptop downloads the newest one each morning into OneDrive (keeps 7), with its own SSH key that can only fetch backups (`deploy/README.md`, "Backups") | The new maintainer sets up the same download on their own PC. Then remove the old laptop's `backup-download` line from the server's `~/.ssh/authorized_keys` and its Task Scheduler task. |
| Read-only deploy key | On the GitHub repo, used by the server to pull code | Replace with the new server's key. |
| Name on the site | About, Press and How it was built pages credit the maintainer by name | Update the pages, with a What's new entry. |
| `security.txt` | `site/static/.well-known/security.txt`, Expires 2027-11-01 | Renew yearly; check the contact address. |

## GitHub organization settings

Settings for the `uscongressvsvoters` organization (Settings in the organization, not the repo). Only
owners should be able to create, delete, move or hide repositories, since the public repo is the
project's transparency promise. Check them at handover and after adding anyone.

| Where (organization Settings) | Setting |
| --- | --- |
| Authentication security | Require two-factor authentication for everyone; only secure methods (authenticator app, passkey, security key, GitHub Mobile) |
| Member privileges → Base permissions | **No permission**: the repo is public, so this only controls who can change it |
| Member privileges → Repository creation | Public and Private both **off**: only owners create repos |
| Member privileges → Repository forking | Forking of private repositories **off** (the public repo can be forked by anyone, as intended) |
| Member privileges → Pages creation | Public **off** (the site runs on the project's own server, not GitHub Pages) |
| Member privileges → App access requests | **Members only** |
| Member privileges → Repository visibility change | **Off**: nobody but an owner can make the public repo private |
| Member privileges → Repository deletion and transfer | **Off**: only owners can delete or transfer repos |
| Member privileges → Team creation rules | **Off**: only owners create teams |

On the repo itself: the "Protect main" ruleset, secret scanning and push protection (free for public
repos), private commit email, GitHub Actions off.

## Handover checklist

- [x] Repo transferred to a project organization (Nov 20, 2026).
- [ ] New maintainer is an owner of the `uscongressvsvoters` GitHub organization; the organization
      settings above checked.
- [ ] Daily backup download set up on the new maintainer's PC; the old one removed.
- [ ] New maintainer can run the tests and the site locally (README.md).
- [ ] Server: new server built, or new maintainer given their own SSH key and sudo login; previous
      maintainer's access removed.
- [ ] All passwords and secrets changed after the handover: database logins, mailbox passwords,
      `.env` values, dev-site password, API keys.
- [ ] Domains, email and account recovery addresses moved to the new maintainer.
- [ ] Site pages updated to name the new maintainer, with a What's new entry.
- [ ] `docs/DECISIONS.md` and `PROJECT_NOTES.md` reviewed together.
