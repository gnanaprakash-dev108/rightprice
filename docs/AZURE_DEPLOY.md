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
pack, the quote alerts and a fabric's negotiation steps, and **record a negotiation step** (the one tool that
changes anything; the step is marked "AI assistant", and the tracker's refusals apply). It cannot change rates,
upload or remove rows, or mark alerts seen.

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
