# 🕵️ Auto Ping Watch

A lightweight Python-based network monitor that periodically pings your local router and public hosts, detecting Internet or LAN outages and notifying you via email.

---

## 🐳 Run in Docker Container

This project can be easily run inside a lightweight Docker container.  
No external Python dependencies are required — the application uses only the standard library.

### 🧱 1. Build the image

Run the following command from the root of the project (where the `Dockerfile` is located):

```bash
docker build -t pingwatch:latest -f Dockerfile .
```

This will create a Docker image named **`pingwatch`**.

---

### ▶️ 2. Run the container

Before starting the container, make sure you have a valid `.env` file in the project directory with your configuration (for example, SMTP credentials and monitoring settings):

```env
ANPW_SMTP_HOST=smtp.gmail.com
ANPW_SMTP_PORT=587
ANPW_SMTP_USER=your_email@gmail.com
ANPW_SMTP_PASS=your_app_password
ANPW_MAIL_FROM="Ping Watch <your_email@gmail.com>"
ANPW_MAIL_TO=your_email@gmail.com
ANPW_INTERVAL=5
ANPW_FAIL_THRESHOLD=3
ANPW_OK_THRESHOLD=2
ANPW_PING_TIMEOUT=1
ANPW_PUBLIC=8.8.8.8
TZ=Europe/Warsaw
```

Then start the container:

```bash
docker run -d   --name pingwatch   --restart unless-stopped   --network host   --cap-add=NET_RAW   --env-file .env   pingwatch:latest
```

**Explanation of key options:**
- `--network host` → allows the container to access your host network stack (needed for ping).  
- `--cap-add=NET_RAW` → grants permission to send ICMP packets.  
- `--env-file .env` → loads configuration variables from the `.env` file.  
- `--restart unless-stopped` → ensures the monitor restarts automatically after reboot.

---

### 🧭 3. Check logs

To see the current status and network events:
```bash
docker logs -f pingwatch
```

You should see entries like:
```
2025-11-01 14:49:23,601 INFO Auto Ping Watch — start (Docker)
2025-11-01 14:49:23,604 INFO Detected gateway (router): 10.0.0.1
2025-11-01 14:57:57,129 WARNING Detected outage: LAN_DOWN (...)
```

---

### 🧹 4. Stop and remove the container (optional)

```bash
docker stop pingwatch && docker rm pingwatch
```

---

### ⚙️ 5. Environment summary

| Variable | Description | Example |
|-----------|-------------|----------|
| `ANPW_SMTP_HOST` | SMTP server hostname | `smtp.gmail.com` |
| `ANPW_SMTP_PORT` | SMTP port | `587` |
| `ANPW_SMTP_USER` | SMTP username | `your_email@gmail.com` |
| `ANPW_SMTP_PASS` | App password for email | *(16-character Gmail app password)* |
| `ANPW_MAIL_FROM` | Sender address (with name) | `"Ping Watch <your_email@gmail.com>"` |
| `ANPW_MAIL_TO` | Email recipient | `your_email@gmail.com` |
| `ANPW_PUBLIC` | Targets to ping (comma separated) | `1.1.1.1` |
| `TZ` | Time zone | `Europe/Warsaw` |

---

### 🧰 6. Requirements

- Python 3.10 or newer  
- Docker Engine 24+  
- No external dependencies required (uses only Python standard library).

---

💡 *Tip:* If you want to run it locally (without Docker), simply execute:
```bash
python auto_net_ping_watch.py
```
with the same `.env` file in the current directory.
