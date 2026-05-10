"""
Hardcoded list of all features (Funktionen) that can be toggled per permission.
To add a new feature:
  1. Add an entry to FEATURES
  2. The matching Boolean column is automatically added to permissions table
     via the ALTER TABLE migration in database.py init_db()
"""

FEATURES: list[dict] = [
    # ── App-interne Funktionen ────────────────────────────────────────────────
    {
        "key":         "mitarbeiter_ansehen",
        "label":       "Mitarbeiter ansehen",
        "description": "Mitarbeiterliste und Profil-Details einsehen",
        "section":     "App",
    },
    {
        "key":         "mitarbeiter_verwalten",
        "label":       "Mitarbeiter verwalten",
        "description": "Benutzer aktivieren, deaktivieren und Rechte vergeben",
        "section":     "App",
    },
    {
        "key":         "logs_einsehen",
        "label":       "Logs einsehen",
        "description": "Aktivitätslogs aller Mitarbeiter einsehen",
        "section":     "App",
    },
    {
        "key":         "einstellungen",
        "label":       "Einstellungen",
        "description": "Systemeinstellungen wie Zeitzone konfigurieren",
        "section":     "App",
    },

    # ── M365 Admin Center — Benutzer ─────────────────────────────────────────
    {
        "key":         "m365_aktive_user",
        "label":       "Aktive User ansehen",
        "description": "Liste und Details aller aktiven M365-Benutzer einsehen",
        "section":     "Admin Center – Benutzer",
    },
    {
        "key":         "m365_benutzer_erstellen",
        "label":       "Benutzer erstellen",
        "description": "Neue M365-Benutzer im Tenant anlegen",
        "section":     "Admin Center – Benutzer",
    },
    {
        "key":         "m365_offboarden",
        "label":       "Benutzer offboarden",
        "description": "M365-Benutzerkonten deaktivieren",
        "section":     "Admin Center – Benutzer",
    },
    {
        "key":         "m365_geloeschte_user",
        "label":       "Gelöschte Benutzer",
        "description": "Gelöschte Benutzer anzeigen und wiederherstellen",
        "section":     "Admin Center – Benutzer",
    },
    {
        "key":         "m365_benutzer_bearbeiten",
        "label":       "Benutzer bearbeiten",
        "description": "Kontakt, Lizenzen, Gruppen, Postfacheinstellungen bearbeiten",
        "section":     "Admin Center – Benutzer",
    },

    # ── M365 Admin Center — Teams & Gruppen ──────────────────────────────────
    {
        "key":         "m365_teams_gruppen",
        "label":       "Teams & Gruppen ansehen",
        "description": "Liste aller Microsoft 365 Gruppen und Teams",
        "section":     "Admin Center – Teams & Gruppen",
    },
    {
        "key":         "m365_geloeschte_gruppen",
        "label":       "Gelöschte Gruppen",
        "description": "Gelöschte Gruppen anzeigen und wiederherstellen",
        "section":     "Admin Center – Teams & Gruppen",
    },
    {
        "key":         "m365_postfaecher",
        "label":       "Freigegebene Postfächer",
        "description": "Freigegebene Exchange Online Postfächer verwalten",
        "section":     "Admin Center – Teams & Gruppen",
    },

    # ── M365 Admin Center — Einstellungen ────────────────────────────────────
    {
        "key":         "m365_lizenzen",
        "label":       "Lizenzen ansehen",
        "description": "Tenant-Lizenzen und deren Verfügbarkeit einsehen",
        "section":     "Admin Center – Einstellungen",
    },
]

FEATURE_KEYS: list[str] = [f["key"] for f in FEATURES]

# Features grouped by section (for the permissions UI)
FEATURE_SECTIONS: dict[str, list[dict]] = {}
for _feat in FEATURES:
    _sec = _feat.get("section", "Sonstige")
    FEATURE_SECTIONS.setdefault(_sec, []).append(_feat)


def user_has_feature(user, feature_key: str) -> bool:
    """Check if a user (ORM object) has a specific feature via any of their permissions."""
    if user.is_admin:
        return True
    return any(getattr(p, f"feat_{feature_key}", False) for p in user.permissions)
