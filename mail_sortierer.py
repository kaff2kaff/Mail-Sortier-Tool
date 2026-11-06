#!/usr/bin/env python3
"""
Mail-Sortier-Tool
=================

Sortiert Werbe-E-Mails im Posteingang eines Gmail-/Googlemail-Kontos in den
Spam-Ordner. Das Tool arbeitet direkt per IMAP auf dem Google-Server – da die
Apple-App "Mail" das Konto ebenfalls per IMAP synchronisiert, erscheinen die
verschobenen Mails dort automatisch im Ordner "Spam" (auf Mac, iPhone, iPad).

Nur Python-Standardbibliothek, keine Installation nötig (Python >= 3.8).

Beispiele:
    python3 mail_sortierer.py                 # Testlauf: zeigt nur an, verschiebt nichts
    python3 mail_sortierer.py --apply         # verschiebt erkannte Werbung in den Spam
    python3 mail_sortierer.py --days 30 -v    # letzte 30 Tage, mit Begründung je Mail
"""

from __future__ import annotations

import argparse
import email
import email.policy
import getpass
import imaplib
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.utils import parseaddr
from pathlib import Path
from typing import Iterable

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
KEYCHAIN_SERVICE = "mail-sortierer"
DEFAULT_CONFIG = Path(__file__).with_name("config.json")

log = logging.getLogger("mail-sortierer")

# --------------------------------------------------------------------------- #
# Standard-Regeln (können in config.json erweitert/überschrieben werden)
# --------------------------------------------------------------------------- #

DEFAULT_SUBJECT_KEYWORDS = [
    # Deutsch
    "rabatt", "angebot", "gutschein", "gutscheincode", "sale", "schnäppchen",
    "nur heute", "nur noch", "jetzt sparen", "sparen sie", "gratis",
    "kostenlos", "versandkostenfrei", "aktion", "deal", "black friday",
    "cyber monday", "newsletter", "exklusiv", "reduziert", "prozent",
    "letzte chance", "jetzt zugreifen", "neu eingetroffen", "sonderangebot",
    # Englisch
    "% off", "discount", "coupon", "promo", "limited time", "free shipping",
    "special offer", "save up to", "last chance", "exclusive", "don't miss",
]

DEFAULT_SENDER_PATTERNS = [
    r"^newsletter", r"^news@", r"^marketing", r"^promo", r"^angebote?@",
    r"^deals?@", r"^offers?@", r"^mailing", r"^info@.*\.(shop|store)$",
    r"^hello@", r"^team@", r"^email@", r"^mail@news",
]

# Header, die typischerweise von Massenversand-Diensten gesetzt werden
BULK_MAILER_HEADERS = [
    "X-Mailchimp-Campaign", "X-MC-User", "X-Campaign", "X-CampaignID",
    "X-SG-EID", "X-SFMC-Stack", "X-Mailgun-Tag", "X-Newsletter",
    "X-Mailer-RecptId", "X-rpcampaign", "X-CSA-Complaints",
]


# --------------------------------------------------------------------------- #
# Konfiguration
# --------------------------------------------------------------------------- #

@dataclass
class Config:
    email: str = ""
    threshold: int = 5
    use_gmail_promotions: bool = True
    days: int = 7
    source_folder: str = "INBOX"
    target_folder: str = ""          # leer = Spam-Ordner automatisch erkennen
    whitelist: list[str] = field(default_factory=list)   # nie verschieben
    blacklist: list[str] = field(default_factory=list)   # immer verschieben
    subject_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_SUBJECT_KEYWORDS))
    sender_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_SENDER_PATTERNS))
    extra_subject_keywords: list[str] = field(default_factory=list)
    extra_sender_patterns: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None) -> "Config":
        cfg = cls()
        if path and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, value in data.items():
                if key.startswith("_"):
                    continue  # Kommentarfelder
                if not hasattr(cfg, key):
                    raise ValueError(f"Unbekannte Einstellung in {path}: {key!r}")
                setattr(cfg, key, value)
        cfg.subject_keywords = [k.lower() for k in cfg.subject_keywords + cfg.extra_subject_keywords]
        cfg.sender_patterns = cfg.sender_patterns + cfg.extra_sender_patterns
        cfg.whitelist = [w.lower().strip() for w in cfg.whitelist]
        cfg.blacklist = [b.lower().strip() for b in cfg.blacklist]
        return cfg


# --------------------------------------------------------------------------- #
# Klassifikation
# --------------------------------------------------------------------------- #

@dataclass
class Verdict:
    is_ad: bool
    score: int
    reasons: list[str]


def _matches_list(address: str, entries: Iterable[str]) -> str | None:
    """Prüft Adresse gegen Liste aus vollen Adressen oder Domains (auch '@domain.de')."""
    address = address.lower()
    domain = address.rsplit("@", 1)[-1]
    for entry in entries:
        entry = entry.lstrip("@")
        if address == entry or domain == entry or domain.endswith("." + entry):
            return entry
    return None


def classify(msg: email.message.Message, cfg: Config, gmail_promotion: bool = False) -> Verdict:
    """Bewertet eine Mail anhand ihrer Header. Liefert Punkte + Begründungen."""
    sender = parseaddr(str(msg.get("From", "")))[1].lower()
    subject = str(msg.get("Subject", "")).lower()

    hit = _matches_list(sender, cfg.whitelist)
    if hit:
        return Verdict(False, 0, [f"Whitelist ({hit})"])
    hit = _matches_list(sender, cfg.blacklist)
    if hit:
        return Verdict(True, 99, [f"Blacklist ({hit})"])

    score = 0
    reasons: list[str] = []

    def add(points: int, reason: str) -> None:
        nonlocal score
        score += points
        reasons.append(f"+{points} {reason}")

    if gmail_promotion:
        add(4, "Gmail-Kategorie 'Werbung'")
    if msg.get("List-Unsubscribe"):
        add(3, "List-Unsubscribe-Header")
    if str(msg.get("Precedence", "")).lower() in ("bulk", "list", "junk"):
        add(2, f"Precedence: {msg.get('Precedence')}")
    if msg.get("List-Id"):
        add(1, "List-Id-Header")
    mailer_hits = [h for h in BULK_MAILER_HEADERS if msg.get(h)]
    if mailer_hits:
        add(2, f"Massenversand-Header ({mailer_hits[0]})")

    local_part = sender.split("@", 1)[0]
    for pattern in cfg.sender_patterns:
        if re.search(pattern, sender) or re.search(pattern, local_part):
            add(2, f"Absender-Muster '{pattern}'")
            break

    kw_hits = [k for k in cfg.subject_keywords if k in subject]
    if kw_hits:
        add(min(len(kw_hits), 3), f"Betreff-Stichwörter {kw_hits[:3]}")
    if re.search(r"\d{1,2}\s?%", subject):
        add(1, "Prozentangabe im Betreff")

    # Persönliche Antworten/Weiterleitungen schützen
    if re.match(r"^\s*(re|aw|fwd?|wg)\s*:", subject):
        score -= 5
        reasons.append("-5 Antwort/Weiterleitung")

    return Verdict(score >= cfg.threshold, score, reasons)


# --------------------------------------------------------------------------- #
# Passwort
# --------------------------------------------------------------------------- #

def get_password(account: str) -> str:
    """App-Passwort aus Umgebungsvariable, macOS-Schlüsselbund oder Eingabe."""
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    if pw:
        return pw
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["security", "find-generic-password", "-a", account, "-s", KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, check=True,
            )
            return out.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    if not sys.stdin.isatty():
        raise SystemExit("Kein App-Passwort gefunden (Schlüsselbund oder GMAIL_APP_PASSWORD).")
    return getpass.getpass(f"Google-App-Passwort für {account}: ")


# --------------------------------------------------------------------------- #
# IMAP
# --------------------------------------------------------------------------- #

def _quote(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find_spam_folder(imap: imaplib.IMAP4_SSL) -> str:
    """Findet den Spam-Ordner über das IMAP-Attribut \\Junk (sprachunabhängig)."""
    typ, data = imap.list()
    if typ != "OK":
        raise RuntimeError("Ordnerliste konnte nicht geladen werden")
    for raw in data:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        if "\\Junk" in line:
            m = re.search(r'"([^"]+)"\s*$', line) or re.search(r"(\S+)\s*$", line)
            if m:
                return m.group(1)
    for fallback in ("[Gmail]/Spam", "[Google Mail]/Spam"):
        if imap.select(_quote(fallback), readonly=True)[0] == "OK":
            return fallback
    raise RuntimeError("Spam-Ordner nicht gefunden – bitte 'target_folder' in config.json setzen.")


def search_uids(imap: imaplib.IMAP4_SSL, criteria: str) -> list[bytes]:
    typ, data = imap.uid("SEARCH", None, criteria)
    if typ != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def fetch_headers(imap: imaplib.IMAP4_SSL, uids: list[bytes], chunk: int = 100):
    """Lädt nur die Header (PEEK = Mails bleiben ungelesen)."""
    for i in range(0, len(uids), chunk):
        part = b",".join(uids[i:i + chunk]).decode()
        typ, data = imap.uid("FETCH", part, "(UID BODY.PEEK[HEADER])")
        if typ != "OK":
            continue
        for item in data:
            if not isinstance(item, tuple):
                continue
            m = re.search(rb"UID (\d+)", item[0])
            if m:
                yield m.group(1), email.message_from_bytes(item[1], policy=email.policy.default)


def move(imap: imaplib.IMAP4_SSL, uids: list[bytes], target: str) -> None:
    for i in range(0, len(uids), 200):
        part = b",".join(uids[i:i + 200]).decode()
        typ, _ = imap.uid("MOVE", part, _quote(target))
        if typ != "OK":  # Fallback ohne MOVE-Erweiterung
            imap.uid("COPY", part, _quote(target))
            imap.uid("STORE", part, "+FLAGS", r"(\Deleted)")
            imap.expunge()


def run(cfg: Config, apply: bool, verbose: bool) -> int:
    if not cfg.email:
        raise SystemExit("Bitte E-Mail-Adresse in config.json ('email') oder per --email angeben.")

    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        imap.login(cfg.email, get_password(cfg.email))
    except imaplib.IMAP4.error as exc:
        raise SystemExit(f"Anmeldung fehlgeschlagen: {exc}\n"
                         "Tipp: Ein Google-App-Passwort verwenden (siehe README).")

    try:
        target = cfg.target_folder or find_spam_folder(imap)
        typ, _ = imap.select(_quote(cfg.source_folder), readonly=not apply)
        if typ != "OK":
            raise SystemExit(f"Ordner {cfg.source_folder!r} nicht gefunden.")

        since = (date.today() - timedelta(days=cfg.days)).strftime("%d-%b-%Y")
        uids = search_uids(imap, f"SINCE {since}")
        promo_uids: set[bytes] = set()
        if cfg.use_gmail_promotions:
            promo_uids = set(search_uids(imap, f'SINCE {since} X-GM-RAW "category:promotions"'))

        log.info("Prüfe %d Mails in %s (letzte %d Tage) …", len(uids), cfg.source_folder, cfg.days)

        to_move: list[bytes] = []
        for uid, msg in fetch_headers(imap, uids):
            verdict = classify(msg, cfg, gmail_promotion=uid in promo_uids)
            if verdict.is_ad:
                to_move.append(uid)
            if verdict.is_ad or verbose:
                mark = "WERBUNG" if verdict.is_ad else "ok     "
                log.info("[%s] %3d  %-35.35s  %s", mark, verdict.score,
                         parseaddr(str(msg.get("From", "")))[1], str(msg.get("Subject", ""))[:70])
                if verbose:
                    log.info("              %s", "; ".join(verdict.reasons) or "-")

        if not to_move:
            log.info("Keine Werbung gefunden.")
        elif apply:
            move(imap, to_move, target)
            log.info("%d Mail(s) nach %r verschoben.", len(to_move), target)
        else:
            log.info("%d Mail(s) würden nach %r verschoben. "
                     "Zum Ausführen mit --apply starten.", len(to_move), target)
        return len(to_move)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Werbe-Mails in Gmail in den Spam-Ordner sortieren.")
    p.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG, help="Pfad zur config.json")
    p.add_argument("--email", help="Gmail-Adresse (überschreibt config.json)")
    p.add_argument("--days", type=int, help="Wie viele Tage zurück prüfen")
    p.add_argument("--threshold", type=int, help="Punkte-Schwelle für 'Werbung'")
    p.add_argument("--target", help="Zielordner statt Spam (z. B. 'Werbung')")
    p.add_argument("--apply", action="store_true", help="Wirklich verschieben (sonst nur Testlauf)")
    p.add_argument("-v", "--verbose", action="store_true", help="Alle Mails mit Begründung anzeigen")
    p.add_argument("--save-password", action="store_true",
                   help="App-Passwort im macOS-Schlüsselbund speichern und beenden")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    cfg = Config.load(args.config)
    if args.email:
        cfg.email = args.email
    if args.days is not None:
        cfg.days = args.days
    if args.threshold is not None:
        cfg.threshold = args.threshold
    if args.target:
        cfg.target_folder = args.target

    if args.save_password:
        if not cfg.email:
            raise SystemExit("Bitte zuerst --email angeben oder in config.json eintragen.")
        pw = getpass.getpass(f"Google-App-Passwort für {cfg.email}: ").replace(" ", "")
        subprocess.run(["security", "add-generic-password", "-U", "-a", cfg.email,
                        "-s", KEYCHAIN_SERVICE, "-w", pw], check=True)
        print("Gespeichert im Schlüsselbund.")
        return

    run(cfg, apply=args.apply, verbose=args.verbose)


if __name__ == "__main__":
    main()
