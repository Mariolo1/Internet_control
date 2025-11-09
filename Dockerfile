# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

# Zainstaluj narzędzia potrzebne do pingu i wykrywania bramy
RUN apt-get update \
 && apt-get install -y --no-install-recommends iputils-ping iproute2 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# (opcjonalnie) strefa czasowa przez zmienną TZ; bez instalacji tzdata używamy UTC
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY auto_net_ping_watch.py /app/auto_net_ping_watch.py

# Brak zewnętrznych zależności pip — tylko standardowa biblioteka.
# Jeśli chcesz nie-root: dodaj użytkownika i setcap na /bin/ping.
# Tu dla prostoty uruchamiamy jako root (w kontenerze to akceptowalne).

ENTRYPOINT ["python", "/app/auto_net_ping_watch.py"]
