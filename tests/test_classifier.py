import email
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mail_sortierer import Config, classify  # noqa: E402


def msg(headers: str):
    return email.message_from_string(headers.strip() + "\n\n")


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config.load(None)

    def test_typical_newsletter_is_ad(self):
        m = msg("""
From: Shop <newsletter@shop.de>
Subject: Nur heute: 30% Rabatt auf alles!
List-Unsubscribe: <mailto:unsub@shop.de>
Precedence: bulk
""")
        v = classify(m, self.cfg)
        self.assertTrue(v.is_ad, v.reasons)

    def test_personal_mail_is_not_ad(self):
        m = msg("""
From: Anna <anna@example.org>
Subject: Treffen am Samstag?
""")
        self.assertFalse(classify(m, self.cfg).is_ad)

    def test_reply_is_protected(self):
        m = msg("""
From: Anna <anna@example.org>
Subject: AW: Angebot für die Küche
List-Unsubscribe: <mailto:x@example.org>
""")
        self.assertFalse(classify(m, self.cfg).is_ad)

    def test_gmail_promotion_plus_unsubscribe(self):
        m = msg("""
From: info@brand.com
Subject: Unsere Herbstkollektion
List-Unsubscribe: <https://brand.com/u>
""")
        self.assertTrue(classify(m, self.cfg, gmail_promotion=True).is_ad)

    def test_whitelist_wins(self):
        self.cfg.whitelist = ["meine-bank.de"]
        m = msg("""
From: newsletter@service.meine-bank.de
Subject: 50% Rabatt Angebot Gutschein
List-Unsubscribe: <mailto:x@y>
""")
        self.assertFalse(classify(m, self.cfg).is_ad)

    def test_blacklist_wins(self):
        self.cfg.blacklist = ["@nervig.com"]
        m = msg("""
From: hallo@nervig.com
Subject: Hallo
""")
        self.assertTrue(classify(m, self.cfg).is_ad)


if __name__ == "__main__":
    unittest.main()
