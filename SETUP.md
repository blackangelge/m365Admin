# Setup-Anleitung: m365Admin

## Voraussetzungen

- Docker Desktop installiert und gestartet
- Zugriff auf das Azure Portal (portal.azure.com) als Administrator

> **Das TLS-Zertifikat wird automatisch beim ersten `docker compose up` generiert.**
> Kein OpenSSL und keine manuelle Zertifikatserstellung notwendig.

---

## Schritt 1 — Azure AD App-Registrierung

1. Öffne [portal.azure.com](https://portal.azure.com)
2. Navigiere zu: **Azure Active Directory → App-Registrierungen → Neue Registrierung**
3. Fülle das Formular aus:
   - **Name:** `m365Admin`
   - **Unterstützte Kontotypen:** "Nur Konten in diesem Organisationsverzeichnis"
   - **Umleitungs-URI:**
     - Plattform: **Web**
     - URI: `https://<DEINE-HOST-IP>/auth/callback`
     - *(ersetze `<DEINE-HOST-IP>` mit der tatsächlichen IP-Adresse des Servers)*
4. Klicke **Registrieren**

### Client-Secret erstellen

1. Gehe zu: **Zertifikate & Geheimnisse → Neuer geheimer Clientschlüssel**
2. Beschreibung: `m365Admin Production`
3. Ablauf: nach Bedarf wählen (z.B. 12 Monate)
4. Kopiere den **Wert** (wird nur einmal angezeigt!)

### Werte notieren

Notiere dir aus der App-Registrierung:
- **Anwendungs-ID (Client-ID)** → `AZURE_CLIENT_ID`
- **Verzeichnis-ID (Tenant-ID)** → `AZURE_TENANT_ID`
- **Client-Secret-Wert** → `AZURE_CLIENT_SECRET`

### API-Berechtigungen prüfen

Gehe zu **API-Berechtigungen** und stelle sicher, dass diese delegierten Berechtigungen vorhanden sind:
- `openid`
- `profile`
- `email`
- `User.Read`

*(Diese sind standardmäßig bereits hinzugefügt — keine Admin-Zustimmung erforderlich)*

---

## Schritt 2 — .env-Datei erstellen

```powershell
cd D:\Python\m365Admin
Copy-Item .env.example .env
```

Öffne `.env` und trage alle Werte ein:

```ini
# App-Geheimschlüssel generieren:
# python -c "import secrets; print(secrets.token_hex(32))"
APP_SECRET_KEY=<generierter-schlüssel>
APP_SESSION_COOKIE_NAME=m365admin_session
APP_DEBUG=false

DATABASE_URL=sqlite+aiosqlite:////data/m365admin.db

AZURE_TENANT_ID=<Tenant-ID aus Schritt 1>
AZURE_CLIENT_ID=<Client-ID aus Schritt 1>
AZURE_CLIENT_SECRET=<Client-Secret aus Schritt 1>
AZURE_REDIRECT_URI=https://<DEINE-HOST-IP>/auth/callback
AZURE_SCOPES=openid profile email User.Read

# TLS-Zertifikat — wird beim ersten Start automatisch generiert
CERT_IP=<DEINE-HOST-IP>
CERT_CN=m365admin
CERT_DAYS=365
```

**App-Geheimschlüssel generieren:**
```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Schritt 3 — App starten

```powershell
cd D:\Python\m365Admin

# Build und Start
docker compose up --build -d

# Logs beobachten (beim ersten Start wird das Zertifikat generiert)
docker compose logs -f nginx
```

Beim ersten Start erscheint in den nginx-Logs:
```
[cert] Generating self-signed TLS certificate...
[cert] Certificate generated and saved to /etc/nginx/certs/cert.pem (valid 365 days, SAN=IP:192.168.1.100)
```

Das Zertifikat wird im Docker-Volume `m365admin_certs` gespeichert und bei jedem weiteren Start **wiederverwendet**.

---

## Schritt 4 — Admin-E-Mail konfigurieren

Der erste Administrator wird automatisch gesetzt — kein manueller Datenbankeingriff nötig.

Trage in der `.env` deine M365-E-Mail-Adresse ein:

```ini
ADMIN_EMAIL=deine@email.de
```

Beim nächsten Login mit dieser Adresse wird `is_admin` automatisch auf `true` gesetzt.
Der Wert wird bei **jedem Login** geprüft, sodass auch ein versehentlich entferntes Admin-Recht sofort wiederhergestellt wird.

---

## Nützliche Befehle

```powershell
# App stoppen
docker compose down

# App neu starten (nach Code-Änderungen)
docker compose up --build -d

# Zertifikat erneuern (Volume löschen → wird beim nächsten Start neu generiert)
docker compose down
docker volume rm m365admin_certs
docker compose up -d

# Zertifikat aus Volume exportieren (z.B. für Browser-Import)
docker run --rm -v m365admin_certs:/certs -v D:/backup:/backup alpine `
  cp /certs/cert.pem /backup/m365admin-cert.pem

# Datenbank inspizieren
docker compose exec m365admin sh -c "sqlite3 /data/m365admin.db '.tables'"
docker compose exec m365admin sh -c "sqlite3 /data/m365admin.db 'SELECT id, email, display_name, is_admin FROM users;'"

# Health-Check
curl -k https://<DEINE-HOST-IP>/health

# Logs
docker compose logs -f m365admin
docker compose logs -f nginx

# Datenbank sichern
docker run --rm -v m365admin_data:/data -v D:/backup:/backup alpine `
  tar czf /backup/m365admin_backup_$(Get-Date -Format 'yyyyMMdd').tar.gz /data
```

---

## Problemlösungen

### Port 80/443 bereits belegt
```powershell
netstat -ano | findstr ":80"
netstat -ano | findstr ":443"
# PID im Task-Manager suchen und Prozess beenden
```

### Fehler "AZURE_REDIRECT_URI mismatch"
- Prüfe, ob die URI in Azure **exakt** mit `AZURE_REDIRECT_URI` in `.env` übereinstimmt
- Achte auf `https://` vs `http://`, Großschreibung und den Pfad `/auth/callback`

### Browser akzeptiert selbstsigniertes Zertifikat nicht
- Chrome: Tippe `thisisunsafe` auf der Fehlerseite
- Firefox: Klicke "Erweitert → Risiko akzeptieren und fortfahren"
- Oder: Zertifikat aus dem Volume exportieren (Befehl oben) und in Windows als vertrauenswürdig importieren:
  ```powershell
  Import-Certificate -FilePath D:\backup\m365admin-cert.pem `
    -CertStoreLocation Cert:\LocalMachine\Root
  ```
