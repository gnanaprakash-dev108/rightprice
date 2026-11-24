# Putting RightPrice on Azure

The portal's menu names change from time to time; the settings below are what matter.

## Live site (set up 24 Nov 2026)

`https://rightprice-bnf2bwbga8bga6eb.indiasouthcentral-01.azurewebsites.net`: web app `rightprice`,
resource group `rightprice-rg`, plan `ASP-rightpricerg-a720` (Basic B1, India South Central),
Azure for Students subscription. Every push to `main` redeploys it through
`.github/workflows/main_rightprice.yml`.

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
- To take a copy of the live rate master, download it from the same folder (Advanced Tools > Kudu >
  file browser), or use the downloads on the Rate tables screen.

## If the page does not load

- Web app > **Log stream** shows the start-up messages.
- "Application Error" straight after deploy usually means the packages are still installing, or the
  startup command is missing.
- A page that loads and then stays on "Please wait" means web sockets are off.

## Cost

The plan is charged by the hour whether or not anyone uses the app. Check the current B1 price in the
Azure pricing calculator, and stop or delete the web app and its App Service plan when it is not needed.
