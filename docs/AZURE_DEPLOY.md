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

## Users and roles (stage 3 of the rebuild)

Microsoft sign-in decides who can reach the site; RightPrice's own list decides what each person may do there. Until
the app setting `RIGHTPRICE_ADMINS` is added, the app behaves as before: everyone who can sign in may use everything
(the page Users and roles, under the user icon, says "Permissions are off"). Deploying the code changes nothing for
anyone.

With the setting on:
- nobody gets in until an admin adds them on Users and roles (their e-mail address, name and role). Someone signed in
  but not added sees: "You have not been given access yet. Ask an admin to add you: you are signed in as <their
  address>". Everything with data they ask the server for is refused (403); the page itself (which holds no data) opens
  without the database, so a slow database never stops the site from opening;
- the addresses in the setting are always Admin, whether or not they are in the list;
- the server checks every request against the person's role; the screens only hide what the role may not use;
- every change on Users and roles (a person added, a role changed, someone switched off or on, a permission given or
  taken away) is kept in the record at the foot of that page, with who made it and when;
- `/mcp` (the AI assistant) is not affected: it still needs its token, and nothing else.

The four roles, as GP decided on 27 Nov 2026 (the pages and actions of each can be changed on Users and roles):

| Role | May |
|---|---|
| Admin | Everything, users included |
| Rates editor | Every page; edit rates and apply mill cost sheet drafts; uploads, tracker steps, alerts seen, drafts; no user admin |
| Buyer | Every page; uploads, tracker steps, alerts seen, drafts; no rate edits; no user admin |
| Viewer | Every page, to read; changes nothing |

The earlier screens (`/classic`, "Earlier screens" under the user icon) can change rates, so they open only for roles
that may edit rates. Each person's own marks (Status and Remarks in Right cost, saved searches, Library lists) stay in
their own browser, as before.

What a tick does, plainly:
- **Actions** (edit rates, apply drafts, upload, record steps, mark alerts seen, draft messages, manage users) are
  strict: a role without one cannot do it anywhere, whatever a screen shows.
- **Pages** decide which pages a role can open. They are **not** a way to keep figures secret. Data several pages read
  stays open to a role that has any of them, so unticking one page never breaks another (the Dashboard reads the fabric
  list and the quote alerts; Compare reads the fabric list; Right cost's fabric pages cost the fabric). Many figures
  show on more than one page: the Dashboard shows the pilot results by fabric type and by supplier, the cotton price by
  year and the mill rate card's terms; the drop-down lists every screen loads carry the yarn master with its rates, for
  anyone let in. The admin page says, for each page, what unticking it hides and where its figures still show.
- The screens shown inside the shell from the earlier front end (the Dashboard, the price pages, Bulk upload, Create
  cost, Compare, the pack, Mill cost sheets) still show their buttons to a role that may not use them; pressing one
  answers "Your role (...) may not ...". Stage 4 moves these screens into the shell and can hide them then.

How the person is read: from `X-MS-CLIENT-PRINCIPAL-NAME` alone, as App Service's sign-in sets it, or, only when that is
absent, from the sign-in's `preferred_username` or `upn` claim; never from the display name. Microsoft describes that
header as "a human-readable name ... such as an email address or user principal name" and does not say which it is for
a personal or a guest account, so add each person by the address the refusal shows them (a personal account written
`live.com#name@example.com` is read as `name@example.com`). A request carrying a sign-in header twice is refused.

App Service sign-in must stay on. On Azure the app trusts the sign-in headers only while App Service says sign-in is on
(the setting `WEBSITE_AUTH_ENABLED`, which App Service sets itself). If Authentication is ever turned off while
`RIGHTPRICE_ADMINS` is set, nobody is let in, admins included, and the page says why: turn sign-in back on, or remove
`RIGHTPRICE_ADMINS`.

### Switching it on

Do this only with the database in use (`/api/store` says `"store": "postgres"` and `"ok": true`): the list of people
is kept in the database. With the setting on and no database, only the addresses in the setting can use the site, and
everyone else is told a database is needed.

Going back is always one step: deleting the app setting `RIGHTPRICE_ADMINS` (and restarting) returns the site to how it
is today, open to everyone who can sign in. The list of people and the record are kept for later.

1. Before adding anything, open `https://rightprice-bnf2bwbga8bga6eb.indiasouthcentral-01.azurewebsites.net/api/me`
   (signed in) and check two things:
   - `"email"` is your own address, as you sign in. That exact address goes into the setting.
   - `"sign_in"` says `"on"`. It is how the app reads App Service's own setting `WEBSITE_AUTH_ENABLED`, which the
     build session could not see on the live site. If it says `"off"` while Authentication is on in the portal, do not
     add `RIGHTPRICE_ADMINS`: with it, nobody would be let in. Tell the build session what `/api/me` shows.
2. Web app `rightprice` > **Settings** > **Environment variables** > **App settings** > **+ Add**:

   | Name | Value |
   |---|---|
   | `RIGHTPRICE_ADMINS` | that address, for example `gp@yourcompany.com` (more than one: separate them with commas) |

   Apply, and confirm the restart. The app also reads `"gp@yourcompany.com"`, `GP <gp@yourcompany.com>`,
   `mailto:gp@yourcompany.com`, `live.com#gp@outlook.com` and a full stop after the address. Anything that is still not an e-mail address is
   ignored (an admin sees which on Users and roles). If the setting names no valid address at all, nobody is an admin
   from it: everyone refused is told "the app setting RIGHTPRICE_ADMINS names no valid e-mail address", and the Log
   stream says so too.
3. After a minute, open the site, then the user icon > **Users and roles**. It should say "Permissions are on" and show
   your address as always Admin. (If instead you are shut out, delete `RIGHTPRICE_ADMINS` again: the site is as before.) Add yourself as Admin in the list too, so you stay an admin if the setting is changed
   later. From now on, the others see "You have not been given access yet" until you add them, so add them straight
   away (next steps).

### Adding the 10 people

1. Each person must be able to sign in to the site with Microsoft. The sign-in was set up with the express settings
   ("Workforce configuration (current tenant)", supported account type "Current tenant - Single tenant"), which lets in
   the accounts of your own Microsoft Entra directory and its guests. Someone from outside it is invited as a guest:
   [Microsoft Entra admin center](https://entra.microsoft.com) > **Entra ID** > **Users** > **Invite external user**:
   their e-mail address and name, tick **Send invite message**, **Review and invite**, **Invite**. They open the
   e-mail "Microsoft Invitations on behalf of ..." and press **Accept invitation**. Inviting needs at least the
   "Guest Inviter" or "User Administrator" role in that directory. If the directory belongs to a college (an Azure for
   Students subscription can sit in one), you may not have that role: ask the build session for the other way (a
   directory of your own).
2. On Users and roles > **Add a person**: their e-mail address (as they sign in), name and role, then **Add**.
3. Ask each to open the site. If one sees "You have not been given access yet", the page shows the address Microsoft
   gave for them: add exactly that address (a guest account can arrive under another address than the one invited).

Changing a role, switching someone off or on, and changing what a role may do are on the same page. Nobody is ever
deleted, only switched off, so the record keeps its meaning. The last Admin in the list cannot be made something else or
switched off: make someone else Admin first.

### Switching it off

Delete the app setting `RIGHTPRICE_ADMINS` and restart: everyone who can sign in may use everything again. The list of
people and the record are kept for when it is added back. While it is off, the Users and roles page is not shown and
nothing on it can be changed (the app cannot tell an admin from anyone else then, and the page lists people's addresses).

**Do not use `RIGHTPRICE_UI=classic` while permissions are on**: it runs the earlier screens alone, without the app that
checks permissions, so everyone signed in could change rates.

**Not tried by the build session** (it has no Azure access and cannot sign in): everything above on the live site.
What was tried: the app, on a test PostgreSQL 16 and on SQLite, given the headers Microsoft documents for a signed-in
person ("Work with user identities in AuthN/AuthZ", updated November 2026: `X-MS-CLIENT-PRINCIPAL-NAME`, and
`X-MS-CLIENT-PRINCIPAL` holding the claims, which "external requests aren't allowed to set"). Which address Microsoft
puts there for a guest or a personal Microsoft account was not seen, nor the value App Service gives
`WEBSITE_AUTH_ENABLED` on this web app (Microsoft's reference says only that it is "injected ... to indicate whether App
Service authentication is enabled"; the app takes `True` or `1` as on). If switching permissions on shows everyone
"App Service sign-in (Authentication) is off" although it is on, remove `RIGHTPRICE_ADMINS` (the site opens as before)
and tell the build session. Optional, also not tried: in the
Entra admin center, the app's Enterprise application > Properties > "Assignment required?" = Yes, then Users and
groups > add the 10, so that nobody else can even sign in.

## Letting an AI assistant in (MCP), and e-mail drafts

Two app settings, both optional. Web app > **Settings** > **Environment variables** > App settings:

| Name | Value | Why |
|---|---|---|
| `ANTHROPIC_API_KEY` | your Claude API key | "Draft a message to the mill" is written by Claude. Without it a fixed template is used and the dialog says so |
| `RIGHTPRICE_MCP_TOKEN` | a long random secret, 24 characters or more | Switches on `/mcp`, the way in for an AI assistant. Without it `/mcp` answers 404 |

Restart the app after adding either.

**The token is an admin key (GP's decision, 27 Nov 2026).** Whoever holds it can do, through an assistant, everything an
Admin can do in the app: change rates, upload and remove fabrics, apply mill cost sheet drafts, mark alerts seen, record
and remove negotiation steps, and add people, change their roles and switch them off. Keep it as you keep the Azure
password: only in the app setting and in your own Claude Desktop settings, never in an e-mail, a chat or a file you share.

### The MCP endpoint and Microsoft sign-in

The site requires Microsoft sign-in for every address, and an AI assistant cannot sign in. So `/mcp` has to be let
through the sign-in, and is then protected by the token alone: every request must carry
`Authorization: Bearer <the token>`. Nothing else is let through.

1. Make the token. In Cloud Shell (the `>_` icon at the top of the portal) run `openssl rand -hex 32` and keep the
   result somewhere safe. Treat it like a password: anyone holding it can do what an Admin can.
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
   not taken; `404` "switched off" means step 2 has not). The second must answer `{"ok": true, ...}`, with
   `"tools": 46`. Then open the site's home page in a private window: it must still ask for Microsoft sign-in.

### Cutting it off

- **At once, for everyone:** delete the app setting `RIGHTPRICE_MCP_TOKEN` (web app > Settings > Environment
  variables) and restart the app. `/mcp` then answers 404 to everything; nothing else on the site changes.
- **If the token may have been seen by someone else:** make a new one (step 1), put it in the app setting in place
  of the old one, and restart. The old token stops working at once; put the new one in your Claude Desktop settings.
- **To see what the assistant changed:** every change it makes is recorded as "AI assistant": on Users and roles
  (Record of changes) for people and roles; in a fabric's Log for tracker steps; in the rate master's versions
  (`/api/store` shows who saved the one in use) for rates; on the fabric list and Mill cost sheets for uploads.
  There is one token, so the record cannot say which person was behind the assistant.
- The assistant is not on the admin page's list of people and its column there cannot be unticked: it is a fixed
  role in the code, and the token is the switch. `RIGHTPRICE_ADMINS` does not affect it (it needs its token, and
  only its token).

### Connecting Claude Desktop

Claude Desktop's own "custom connector" screen does not send a fixed token, so use the `mcp-remote` bridge, which
runs on your computer and adds the token to every request. It needs Node.js (nodejs.org, the LTS installer).

1. In Claude Desktop: **Settings** > **Developer** > **Edit Config**. This opens `claude_desktop_config.json`.
2. Put this in it (or add the `"rightprice"` part to the `"mcpServers"` already there), with your token after
   `Bearer `:

   ```
   {"mcpServers": {"rightprice": {
       "command": "npx",
       "args": ["-y", "mcp-remote",
                "https://rightprice-bnf2bwbga8bga6eb.indiasouthcentral-01.azurewebsites.net/mcp",
                "--header", "Authorization:${AUTH_HEADER}"],
       "env": {"AUTH_HEADER": "Bearer THE-TOKEN"}}}}
   ```

   The token sits in `"env"`, not in the header line itself: on Windows, Claude Desktop breaks a value with a space
   in it (`Bearer THE-TOKEN`) when it starts `npx`, and `mcp-remote` puts `${AUTH_HEADER}` back together.
3. Quit Claude Desktop fully (also from the tray icon) and open it again. RightPrice's tools show under the tools
   icon in a new chat. Ask "What is the store status of RightPrice?" to try it.
4. Claude Desktop asks before each tool that changes something (they are marked as such); read what it says it will
   change before you allow it. The assistant is told to change a rate only when you ask for that change, and to say
   the old and the new figure first.

Tried by the build session on 27 Nov 2026 against the app on its own machine (not the live site): `mcp-remote` 0.1.37
and 0.17.1 with exactly these arguments, listing the tools (40 then; 46 since stage 5's dated rates), reading a rate table and adding a cotton price (saved as
"AI assistant"). Claude Desktop itself was not tried.

- **On a laptop, on that laptop's own data** (no token, no Azure): `{"mcpServers": {"rightprice": {"command":
  "python", "args": ["C:\\path\\to\\rightprice\\mcp_server.py"]}}}`. The same tools; with no sign-in there,
  changes to people and roles are refused (they need the database and `RIGHTPRICE_ADMINS`).
- **A build session checking a deploy**: with the token saved for the site's host through the secure form, it can
  call `/mcp/health`, which reports which code is running. Remember the token is an admin key.

### What the assistant can do (46 tools)

Each tool does what one address of the screens does, through the same rule, with the same refusals:

- **Read:** cost a fabric; find costings; a fabric's brief and negotiation steps; a supplier's page and the list of
  suppliers; a negotiation pack; the quote alerts; the fabric list (with a yarn price move tried); the rate tables,
  the yarn master, cotton prices; the dated yarn rates and what loading the market history would give; the Dashboard's
  panels and what negotiation has won; the pilot results; mill cost sheets and their drafts; Users and roles with the
  record of changes; where the data is kept (`store_status`); cost a filled template (nothing kept).
- **Change (Claude Desktop asks first):** edit a rate table (cell by cell, giving the old and new figure, or the whole
  table; the version before is kept); add a cotton price; Bring in prices (read a file, a page or a JSON endpoint, map
  its columns, add the checked rows to the market reference or as dated yarn rates); enter or remove a dated yarn
  rate, load the market history's dated rates; upload a mill's sheet or a template to the fabric list, add one fabric,
  remove rows; upload and remove mill cost sheets and apply their drafts; mark alerts seen or bring them back; record
  a tracker step, undo its own, or remove any step; add a person, change a role or name, switch someone off or on,
  change what a role may do (the last admin in the list stays an admin).
- **Draft a message to a mill** (nothing is sent or kept).

A file (a mill's sheet, a price list) is given to a tool as base64 with its name. **Not tried:** whether Claude
Desktop can hand a file you attach to a tool that way (it may see only the file's text). If it cannot, upload the file
on the screen. Downloads (the template, the list as Excel, cost sheets) stay on the screens.

When a later stage adds an action to the app, it adds the matching tool (mcp_server.py, "Adding a tool"); the checks
fail until it does.

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
