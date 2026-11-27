# Putting RightPrice on Azure

The portal's menu names change from time to time; the settings below are what matter.

## Live site (set up 24 Nov 2026)

`https://rightprice-bnf2bwbga8bga6eb.indiasouthcentral-01.azurewebsites.net`: web app `rightprice`,
resource group `rightprice-rg`, plan `ASP-rightpricerg-a720` (Basic B1, India South Central),
Azure for Students subscription. Every push to `main` redeploys it through
`.github/workflows/main_rightprice.yml`.

Since 24 Nov 2026 the start command runs `server.py` (the new front end), which starts the earlier
Streamlit screens beside itself and serves them under `/classic`. Nothing in the portal changes: the
Startup Command is still `bash startup.sh`, and web sockets must stay on (the classic screens need them).
To go back to the Streamlit screens alone without a redeploy, add the app setting
`RIGHTPRICE_UI` = `classic` and restart; remove it to return to the new front end.

Lessons from the first setup:

- A student subscription allows only a few regions (Policy > Assignments > Allowed resource
  deployment regions). "South India" was refused; "India South Central" was allowed.
- Connect GitHub and let the first deploy finish **before** setting the startup command. With the
  command set and no code, the app fails to start, the site shows 503 and Deployment Center cannot save.
- The Free F1 plan ran out of its daily processor quota ("Site Disabled", status "Quota exceeded").
  Basic B1 is the smallest plan that runs the tool comfortably.
- Stopping the web app does not stop the B1 charge; scale the plan down to Free F1 to stop paying.

## Before you start

- An Azure subscription (Azure for Students, a free trial, or pay-as-you-go).
- The private GitHub repository `rightprice`.
- Decide whether purchase data should go to the server. The app needs only `data/Rate_Master.xlsx`.
  `inputs/`, `data/plm_specs_for_po.csv` and `pilot/` are not used by the running app.

## 1. Create the web app

Portal > **App Services** > **Create** > **Web App**.

| Field | Value |
|---|---|
| Name | `rightprice` (gives `https://rightprice.azurewebsites.net`; add letters if the name is taken) |
| Publish | Code |
| Runtime stack | Python 3.11 |
| Operating system | Linux |
| Region | Central India, or the nearest one your subscription allows |
| Pricing plan | Basic B1 for daily use. Free F1 works for a trial but sleeps and has a daily limit |

## 2. Connect GitHub

In the web app > **Deployment Center**: Source **GitHub**, sign in, pick the `rightprice`
repository and the `main` branch, then Save. Azure adds a workflow file to the repository, and every
push to `main` updates the site. Run `git pull` on your laptop afterwards to receive that file.

## 3. Settings

Web app > **Settings** > **Environment variables** > App settings. Add:

| Name | Value | Why |
|---|---|---|
| `RIGHTPRICE_DATA` | `/home/rightprice-data` | Rate changes, saved costings and imported price files are kept here and survive redeploys and restarts |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` | Installs the packages in `requirements.txt` |

Web app > **Settings** > **Configuration** > General settings:

| Setting | Value |
|---|---|
| Startup Command | `bash startup.sh` |
| Web sockets | On (Streamlit needs them) |
| Always on | On (not available on the Free plan) |

Save, then restart the app. The first start takes a few minutes.

## 4. Limit who can open it

Web app > **Settings** > **Authentication** > Add identity provider > **Microsoft**.
Set "Restrict access" to **Require authentication**. Without this, anyone with the address can open the tool.

## How the rate master behaves on the server

- On first start the app copies `data/Rate_Master.xlsx` from the code into `/home/rightprice-data`.
  From then on the server's copy is the live one, and edits made in the app stay.
- A later push that changes `data/Rate_Master.xlsx` in GitHub does **not** replace the server's copy.
  To replace it on purpose, delete `/home/rightprice-data/Rate_Master.xlsx` (web app >
  Development Tools > SSH) and restart.
- New rate tables are the exception. When a new version of the code needs tables the server's copy
  does not have (the mill rate card, 24 Nov 2026), the app adds them to the server's copy the first
  time it opens, after saving `Rate_Master before rate card <date>.xlsx` in the same folder. Rates
  edited on the server are kept, the printing rate included. The one thing that changes is the
  finishes the card prices, which take the card's figure.
- To take a copy of the live rate master, download it from the same folder (Advanced Tools > Kudu >
  file browser), or use the downloads on the Rate tables screen.

## The database (stage 1 of the rebuild, from 27 Nov 2026)

The app keeps its shared data (the rate master, the fabric list, the negotiation tracker, the alerts marked seen and the
mill cost sheets) in the files in `/home/rightprice-data` until the app setting `DATABASE_URL` is added. With it, the
data is kept in the PostgreSQL database instead. The classic screens follow the same setting. Yarn price documents
brought in through the price intake stay as files in `/home/rightprice-data/price_sources`.

The database: Azure Database for PostgreSQL flexible server `rightprice-db`
(`rightprice-db.postgres.database.azure.com`, port 5432, SSL required), administrator `rpadmin`, resource group
`rightprice-rg`, India South Central, PostgreSQL 16, Burstable B1ms, 32 GiB, backups 7 days, public access with
"allow Azure services" on. Created by GP; the deployment completed on 27 Nov 2026. The app uses the default database,
`postgres`. **The live site moved to it on 27 Nov 2026 at 12:13 UTC.** Its firewall: "Allow public access from any
Azure service within Azure to this server" ticked (without it the app timed out); a tighter choice is one firewall rule
per outbound address of the web app (web app > Networking). Never add "0.0.0.0 - 255.255.255.255".

### Switching the live site to the database

Do this only once the code of stage 1 is merged and its deploy run is green; until then the app does not read the
setting.

1. Optional but cheap: a copy of the data folder. Web app > Development Tools > SSH, then
   `cp -r /home/rightprice-data /home/rightprice-data-before-database`. The move only reads the files; this copy is for
   peace of mind.
2. Web app `rightprice` > **Settings** > **Environment variables** > **App settings** > **+ Add**:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | `postgresql://rpadmin:YOUR-PASSWORD@rightprice-db.postgres.database.azure.com:5432/postgres?sslmode=require` |

   Type the password exactly as it is, even with `@ # : / ? %` in it, and do not percent-encode it (write `@`, not
   `%40`): the app reads the setting itself. Apply, and confirm the restart. The password stays in Azure; never paste it
   into a chat.
3. Wait two or three minutes, then open `https://rightprice-bnf2bwbga8bga6eb.indiasouthcentral-01.azurewebsites.net/api/store`
   (signed in). It should show `"store": "postgres"`, `"ok": true`, and under `copied_in` > `checked` > `summary`:
   the rate master the same workbook byte for byte; the fabric list's rows the same and each costed on both, equal to
   the paisa; the tracker, the alerts seen and the mill cost sheets the same. `counts` gives how many of each it holds.
4. Look at the site as usual: Right cost, the fabric list, the Dashboard, a supplier page, the quote alert count, the
   rate tables. They should be as they were before the setting was added.
5. One change, to see it kept: mark one quote alert seen, restart the web app (Overview > Restart), check it is still
   marked seen, then bring it back.

If something is wrong, `/api/store` says what and what to do. The pages answer "503" with the reason meanwhile.
- **"could not be reached"** (a timeout): the app tries again by itself every 15 seconds. Check that `rightprice-db` is
  running (it can be stopped in the portal) and, under its own **Networking** (not the web app's), that "Allow public
  access from any Azure service within Azure to this server" is ticked and saved. This was the cause on 27 Nov. A wrong password says "password authentication failed". Do not remove `DATABASE_URL` for an outage.
- **"Copying the files in was stopped and nothing was kept"**: nothing moved. Remove `DATABASE_URL` and restart to go
  back to the files, and send the message to the build session.

### Going back to the files

Delete the app setting `DATABASE_URL` and restart. The app returns to the files in `/home/rightprice-data` **as they were
when they were copied in**; `/api/store` then says so. Changes made on the database since stay in the database and are not
in the files. To have them as files: `python store.py export /home/rightprice-data-from-database` in the SSH window
with the setting still on (it writes a new folder and changes nothing else).

If work is done on the files while the setting is off and the setting is then added back, the app will not start on the
database: it says which files changed, so that neither side's work is lost. Either keep working on the files (remove the
setting again), or keep the database and set the files aside with `python store.py keep-database` (SSH window, in
`/home/site/wwwroot`) and restart. Deleting or moving the old files away after the move does not stop the app.

**Not tried by the build session** (it has no Azure access): the two `python store.py ...` commands in the web app's SSH
window. That window may not have the app's packages or settings loaded; if a command says a module is missing or that
`DATABASE_URL` is not set, stop and ask the build session rather than trying other things. Everything else above was
tried on a test PostgreSQL 16 and SQLite in the build container.

The app leaves one new file beside the data files after the move, `moved_to_database.json`, saying when and into which
database they went. With it there, an empty database (a wrong database name in the setting) is refused instead of being
filled again from old files.

### Cost

The portal showed USD 22.08 a month for this server, with "Free up to 750 hours" and "Free up to 32 GB" (the free
services of the first 12 months). Check Cost analysis for `rightprice-db` after the first week. If it is charged, the
agreed fallback is a database file on the web app's own storage: `DATABASE_URL=sqlite:////home/rightprice-data/rightprice.db`
(four slashes). The build session should look at that again before it is used: `/home` on App Service is a network
share, and SQLite needs care there with two processes (the app and the classic screens).

## Letting an AI assistant in (MCP), and e-mail drafts

Two app settings, both optional. Web app > **Settings** > **Environment variables** > App settings:

| Name | Value | Why |
|---|---|---|
| `ANTHROPIC_API_KEY` | your Claude API key | "Draft a message to the mill" is written by Claude. Without it a fixed template is used and the dialog says so |
| `RIGHTPRICE_MCP_TOKEN` | a long random secret, 24 characters or more | Switches on `/mcp`, the way in for an AI assistant. Without it `/mcp` answers 404 |

Restart the app after adding either.

### The MCP endpoint and Microsoft sign-in

The site requires Microsoft sign-in for every address, and an AI assistant cannot sign in. So `/mcp` has to be let
through the sign-in, and is then protected by the token alone: every request must carry
`Authorization: Bearer <the token>`. Nothing else is let through.

1. Make the token. In Cloud Shell (the `>_` icon at the top of the portal) run `openssl rand -hex 32` and keep the
   result somewhere safe. Treat it like a password: anyone holding it can read the costings and record
   negotiation steps.
2. Add it as the app setting `RIGHTPRICE_MCP_TOKEN` (table above) and restart.
3. Let `/mcp` through the sign-in. The portal's Authentication page has no box for this; Microsoft's setting is
   `globalValidation.excludedPaths` in the app's authentication settings (documented under "authsettingsV2").
   In Cloud Shell:

   ```
   az extension add --name authV2
   az webapp auth show --resource-group rightprice-rg --name rightprice > auth-before.json
   az webapp auth update --resource-group rightprice-rg --name rightprice --excluded-paths "[/mcp, /mcp/health]"
   az webapp auth show --resource-group rightprice-rg --name rightprice --query "properties.globalValidation"
   ```

   The last command should show `excludedPaths` holding `/mcp` and `/mcp/health`, with `requireAuthentication`
   still `true`. **Not tried by the build session** (it has no Azure access): Microsoft's page lists
   `--excluded-paths` but gives no example of how the list is written. If the command complains about the value,
   try `--excluded-paths "/mcp,/mcp/health"`, or set the two paths in Resource Explorer
   (`resources.azure.com` > the web app > `config` > `authsettingsV2` > `globalValidation.excludedPaths`).
   `auth-before.json` is the settings as they were, to put back if anything looks wrong.
4. Check it from any computer (replace the token):

   ```
   curl -i https://rightprice-bnf2bwbga8bga6eb.indiasouthcentral-01.azurewebsites.net/mcp/health
   curl -s -H "Authorization: Bearer THE-TOKEN" https://rightprice-bnf2bwbga8bga6eb.indiasouthcentral-01.azurewebsites.net/mcp/health
   ```

   The first must answer `401` with "A token is needed" (a redirect to login.microsoftonline.com means step 3 has
   not taken; `404` "switched off" means step 2 has not). The second must answer `{"ok": true, ...}`.
   Then open the site's home page in a private window: it must still ask for Microsoft sign-in.
5. To switch it off again: delete the app setting `RIGHTPRICE_MCP_TOKEN` and restart. To change the token, change
   the setting and restart; the old token stops working at once.

### Connecting an assistant

- **Claude Desktop, to the live site.** Claude Desktop's own "custom connector" screen does not send a fixed
  token, so use the `mcp-remote` bridge (needs Node.js). In Claude Desktop > Settings > Developer > Edit Config:

  ```
  {"mcpServers": {"rightprice": {"command": "npx", "args": ["mcp-remote",
     "https://rightprice-bnf2bwbga8bga6eb.indiasouthcentral-01.azurewebsites.net/mcp",
     "--header", "Authorization: Bearer THE-TOKEN"]}}}
  ```

  **Not tried by the build session**; the endpoint itself was tried with the MCP package's own client.
- **On a laptop, on that laptop's own data** (no token, no Azure): `{"mcpServers": {"rightprice": {"command":
  "python", "args": ["C:\\path\\to\\rightprice\\mcp_server.py"]}}}`.
- **A build session checking a deploy**: with the token saved for the site's host through the secure form, it can
  call `/mcp/health`, which reports which code is running.

What the assistant can do: cost a fabric, find costings, read a fabric's brief, a supplier's page, a negotiation
pack, the quote alerts and a fabric's negotiation steps, and **record a negotiation step** (marked "AI assistant"; the tracker's refusals apply, and it must record the
mill's first quote before a revised quote or an agreement). It can undo a step it recorded itself, but not one a
person recorded. It cannot change rates, upload or remove rows, or mark alerts seen. Every step it records carries
the same name, "AI assistant": there is one token, so the tool cannot tell which person was behind it.

## If the page does not load

- Web app > **Log stream** shows the start-up messages.
- "Application Error" straight after deploy usually means the packages are still installing, or the
  startup command is missing.
- A page that loads and then stays on "Please wait" means web sockets are off.
- The new pages load but "Edit rates" shows "The classic screens are still starting": wait a few
  seconds and reload. If it persists, the Streamlit process did not start; see the Log stream.

## Cost

The plan is charged by the hour whether or not anyone uses the app. Check the current B1 price in the
Azure pricing calculator, and stop or delete the web app and its App Service plan when it is not needed.
