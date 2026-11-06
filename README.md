# Mail-Sortier-Tool

Sortiert **Werbe-E-Mails** im Posteingang deines **Gmail-/Googlemail-Kontos** automatisch
in den **Spam-Ordner**. Das Ergebnis siehst du direkt in der **Apple-App „Mail“**
auf dem Mac, iPhone und iPad.

## So funktioniert es

Apple Mail synchronisiert dein Google-Konto per IMAP. Das Tool verbindet sich ebenfalls
per IMAP mit `imap.gmail.com`, prüft die Mails im Posteingang und verschiebt Werbung
auf dem Server in den Spam-Ordner. Apple Mail übernimmt die Änderung sofort.

Jede Mail bekommt Punkte. Ab der Schwelle (Standard **5 Punkte**) gilt sie als Werbung:

| Merkmal                                                   | Punkte |
|-----------------------------------------------------------|-------:|
| Gmail selbst hat sie als „Werbung“ (Promotions) eingestuft |     +4 |
| `List-Unsubscribe`-Header (Abmelde-Link)                  |     +3 |
| `Precedence: bulk/list`                                   |     +2 |
| Header von Massenversand-Diensten (Mailchimp, SendGrid …) |     +2 |
| Absender wie `newsletter@`, `marketing@`, `deals@` …      |     +2 |
| Werbe-Stichwörter im Betreff („Rabatt“, „Gutschein“, „% off“ …) | +1 bis +3 |
| Prozentangabe im Betreff                                  |     +1 |
| `List-Id`-Header                                          |     +1 |
| Antwort oder Weiterleitung (`AW:`, `Re:`, `WG:`, `Fwd:`)  |     −5 |

Absender auf der **Whitelist** werden nie verschoben. Absender auf der **Blacklist**
werden immer verschoben.

Das Tool liest nur die Header. Mails bleiben also **ungelesen**, und es wird nichts gelöscht.

## Einrichtung (einmalig, auf dem Mac)

### 1. Google-App-Passwort erstellen

Google erlaubt Programmen den Login nur mit einem **App-Passwort**:

1. Unter <https://myaccount.google.com/security> die **Bestätigung in zwei Schritten** aktivieren (falls noch nicht aktiv).
2. <https://myaccount.google.com/apppasswords> öffnen, als Namen z. B. „Mail-Sortierer“ eingeben und auf **Erstellen** klicken.
3. Das 16-stellige Passwort kopieren.

IMAP ist bei Gmail inzwischen immer aktiviert. Weil Apple Mail bereits funktioniert, ist hier nichts weiter zu tun.

### 2. Tool herunterladen und konfigurieren

```bash
cd ~
git clone https://github.com/kaff2kaff/Mail-Sortier-Tool.git
cd Mail-Sortier-Tool
cp config.example.json config.json
open -e config.json        # E-Mail-Adresse eintragen, Whitelist anpassen
```

### 3. Passwort sicher im macOS-Schlüsselbund speichern

```bash
python3 mail_sortierer.py --save-password
```

Alternativ: Umgebungsvariable `GMAIL_APP_PASSWORD` setzen oder das Passwort bei jedem Start eingeben.

## Benutzung

```bash
# Testlauf: zeigt nur an, was verschoben würde (empfohlen für den Anfang!)
python3 mail_sortierer.py

# Mit Begründung für jede Mail
python3 mail_sortierer.py -v

# Wirklich verschieben
python3 mail_sortierer.py --apply

# Die letzten 60 Tage aufräumen
python3 mail_sortierer.py --days 60 --apply

# Strenger (weniger Treffer) oder lockerer (mehr Treffer)
python3 mail_sortierer.py --threshold 7
python3 mail_sortierer.py --threshold 4

# Statt in den Spam in einen eigenen Ordner/Label "Werbung" verschieben
python3 mail_sortierer.py --target Werbung --apply
```

## Automatisch alle 30 Minuten ausführen

1. In `launchd/de.mailsortierer.plist` den Pfad `/Users/DEINNAME/...` anpassen.
2. Installieren:

```bash
cp launchd/de.mailsortierer.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/de.mailsortierer.plist
```

Das Protokoll steht in `/tmp/mail-sortierer.log`. Zum Beenden:
`launchctl unload ~/Library/LaunchAgents/de.mailsortierer.plist`

## Einstellungen (`config.json`)

| Feld                     | Bedeutung                                                         |
|--------------------------|-------------------------------------------------------------------|
| `email`                  | Deine Gmail-/Googlemail-Adresse                                   |
| `threshold`              | Punkte-Schwelle (Standard 5)                                      |
| `days`                   | Wie viele Tage zurück geprüft wird (Standard 7)                   |
| `use_gmail_promotions`   | Gmails eigene Kategorie „Werbung“ mitnutzen (Standard `true`)     |
| `source_folder`          | Zu prüfender Ordner (Standard `INBOX`)                            |
| `target_folder`          | Zielordner. Leer bedeutet: Spam-Ordner wird automatisch erkannt   |
| `whitelist`              | Adressen/Domains, die nie verschoben werden, z. B. `"@bank.de"`   |
| `blacklist`              | Adressen/Domains, die immer verschoben werden                     |
| `extra_subject_keywords` | Zusätzliche Betreff-Stichwörter                                   |
| `extra_sender_patterns`  | Zusätzliche Absender-Muster (reguläre Ausdrücke)                  |

## Wichtige Hinweise

- **Gmail löscht Mails im Spam-Ordner nach 30 Tagen automatisch.** Wenn du Werbung
  behalten willst, nimm einen eigenen Zielordner (`--target Werbung`).
- Verschieben in den Spam **trainiert Gmails Spamfilter**. Künftige Mails dieser Absender
  landen dann oft von selbst im Spam.
- Falls eine wichtige Mail falsch einsortiert wird: die Mail in Apple Mail zurück in den Posteingang
  ziehen bzw. auf **„Keine Werbung“** klicken und den Absender in die `whitelist` aufnehmen.
- In der deutschen Apple-Mail-App heißt der Spam-Ordner teils **„Werbung“**. Das ist derselbe Ordner.
- Prüfe zuerst mit dem Testlauf (ohne `--apply`), ob die Erkennung für dich passt.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
