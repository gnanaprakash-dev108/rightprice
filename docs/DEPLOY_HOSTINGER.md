# Putting RightPrice on a Hostinger server

Streamlit is a program that has to stay running, so it needs a **Hostinger VPS** (a KVM plan with
Ubuntu 24.04). Hostinger's shared "web hosting" plans cannot run it. The smallest VPS is enough.

The tool holds purchase prices and supplier names. Do not open it to the internet without the
password step (step 6).

Replace `rightprice.example.com` with your own address and `SERVER_IP` with the VPS address shown in
Hostinger's panel.

## 1. Create the server

In Hostinger: VPS → buy or open a plan → operating system **Ubuntu 24.04** → set a root password.
Note the IP address.

## 2. Point a name at it

In the DNS zone of your domain add an **A record**: name `rightprice`, value `SERVER_IP`.

## 3. Log in and install

```bash
ssh root@SERVER_IP
```

```bash
apt update && apt install -y python3-venv python3-pip git nginx apache2-utils certbot python3-certbot-nginx
```

```bash
adduser --disabled-password --gecos "" rightprice
```

## 4. Copy the tool across

The repository is private, so the simplest way is to copy the folder from your computer
(run this on your computer, from the folder that contains `rightprice`):

```bash
scp -r rightprice root@SERVER_IP:/home/rightprice/
```

Then on the server:

```bash
chown -R rightprice:rightprice /home/rightprice/rightprice
```

```bash
sudo -u rightprice bash -c "cd /home/rightprice/rightprice && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python check_engine.py"
```

The last line must end with `ALL OK`.

The app needs only `data/Rate_Master.xlsx`. You can leave `inputs/` and `pilot/` off the server; they
are needed only for `pilot.py` and `calibrate.py`.

## 5. Keep it running

```bash
cat > /etc/systemd/system/rightprice.service <<'EOF'
[Unit]
Description=RightPrice should-cost tool
After=network.target

[Service]
User=rightprice
WorkingDirectory=/home/rightprice/rightprice
ExecStart=/home/rightprice/rightprice/.venv/bin/streamlit run app.py --server.port 8502 --server.address 127.0.0.1 --server.headless true
Restart=always

[Install]
WantedBy=multi-user.target
EOF
```

```bash
systemctl daemon-reload && systemctl enable --now rightprice && systemctl status rightprice --no-pager
```

## 6. Password and web address

```bash
htpasswd -c /etc/nginx/.rightprice_users yourname
```

```bash
cat > /etc/nginx/sites-available/rightprice <<'EOF'
server {
    listen 80;
    server_name rightprice.example.com;
    client_max_body_size 50M;

    location / {
        auth_basic "RightPrice";
        auth_basic_user_file /etc/nginx/.rightprice_users;
        proxy_pass http://127.0.0.1:8502;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}
EOF
```

```bash
ln -sf /etc/nginx/sites-available/rightprice /etc/nginx/sites-enabled/ && nginx -t && systemctl reload nginx
```

```bash
certbot --nginx -d rightprice.example.com
```

```bash
ufw allow OpenSSH && ufw allow "Nginx Full" && ufw --force enable
```

Open `https://rightprice.example.com`. The browser asks for the name and password, then shows the tool.
Add more users with `htpasswd /etc/nginx/.rightprice_users anothername` (no `-c`).

## 7. Afterwards

- **The rate master on the server is the live one.** Rates edited in the app are saved to
  `/home/rightprice/rightprice/data/Rate_Master.xlsx` on the server. Copy it back before replacing the
  folder, or the edits are lost:

  ```bash
  scp root@SERVER_IP:/home/rightprice/rightprice/data/Rate_Master.xlsx ./Rate_Master_from_server.xlsx
  ```

- **Updating the code**: copy the changed `.py` files across (not `data/`), then

  ```bash
  systemctl restart rightprice
  ```

- **If the page does not load**:

  ```bash
  journalctl -u rightprice -n 50 --no-pager
  ```

- Everyone who logs in shares one rate master and one saved-costings list. There are no separate
  user accounts inside the tool in version 1.
