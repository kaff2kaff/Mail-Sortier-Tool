/**
 * Mail-Sortier-Tool – Google-Apps-Script-Version
 * ==============================================
 * Läuft direkt in deinem Google-Konto (kein Mac/PC nötig, Einrichtung auch am iPhone).
 * Verschiebt Werbe-Mails aus dem Posteingang in den Spam. Apple Mail zeigt das automatisch.
 *
 * Bedienung (oben im Editor Funktion auswählen und auf "Ausführen" tippen):
 *   testlauf    – zeigt im Protokoll, was verschoben würde (verschiebt nichts)
 *   aufraeumen  – verschiebt erkannte Werbung jetzt in den Spam
 *   einrichten  – startet die Automatik (alle 30 Minuten)
 *   stoppen     – beendet die Automatik
 */

// ======================= EINSTELLUNGEN =======================
var EINSTELLUNGEN = {
  schwelle: 5,          // ab so vielen Punkten gilt eine Mail als Werbung
  tage: 7,              // wie viele Tage zurück geprüft wird
  gmailWerbungNutzen: true,  // Gmails eigene Kategorie "Werbung" mitzählen

  // Absender/Domains, die NIE verschoben werden
  whitelist: [
    // '@meine-bank.de',
    // 'chef@firma.de',
  ],

  // Absender/Domains, die IMMER in den Spam kommen
  blacklist: [
    // '@nervige-werbung.com',
  ],

  // Statt Spam ein eigenes Label verwenden (z. B. 'Werbung'). Leer = Spam.
  zielLabel: '',
};
// =============================================================

var STICHWOERTER = [
  'rabatt', 'angebot', 'gutschein', 'gutscheincode', 'sale', 'schnäppchen',
  'nur heute', 'nur noch', 'jetzt sparen', 'sparen sie', 'gratis', 'kostenlos',
  'versandkostenfrei', 'aktion', 'deal', 'black friday', 'cyber monday',
  'newsletter', 'exklusiv', 'reduziert', 'prozent', 'letzte chance',
  'jetzt zugreifen', 'neu eingetroffen', 'sonderangebot',
  '% off', 'discount', 'coupon', 'promo', 'limited time', 'free shipping',
  'special offer', 'save up to', 'last chance', 'exclusive', "don't miss",
];

var ABSENDER_MUSTER = [
  /^newsletter/, /^news@/, /^marketing/, /^promo/, /^angebote?@/, /^deals?@/,
  /^offers?@/, /^mailing/, /^hello@/, /^team@/, /^email@/, /^mail@news/,
];

var MASSENVERSAND_HEADER = [
  'X-Mailchimp-Campaign', 'X-MC-User', 'X-Campaign', 'X-CampaignID', 'X-SG-EID',
  'X-SFMC-Stack', 'X-Mailgun-Tag', 'X-Newsletter', 'X-CSA-Complaints',
];

// ---------------------------------------------------------------------------

function testlauf()   { sortieren_(false); }
function aufraeumen() { sortieren_(true); }

function einrichten() {
  stoppen();
  ScriptApp.newTrigger('aufraeumen').timeBased().everyMinutes(30).create();
  Logger.log('Automatik aktiv: alle 30 Minuten wird aufgeräumt.');
}

function stoppen() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'aufraeumen') ScriptApp.deleteTrigger(t);
  });
  Logger.log('Automatik gestoppt.');
}

function sortieren_(ausfuehren) {
  var E = EINSTELLUNGEN;
  var zeitraum = 'newer_than:' + E.tage + 'd';

  var promoIds = {};
  if (E.gmailWerbungNutzen) {
    GmailApp.search('in:inbox category:promotions ' + zeitraum, 0, 500)
      .forEach(function (t) { promoIds[t.getId()] = true; });
  }

  var threads = GmailApp.search('in:inbox ' + zeitraum, 0, 500);
  var treffer = [];
  var label = E.zielLabel ? (GmailApp.getUserLabelByName(E.zielLabel) ||
                             GmailApp.createLabel(E.zielLabel)) : null;

  threads.forEach(function (thread) {
    var msg = thread.getMessages()[0];
    var urteil = bewerten_(msg, !!promoIds[thread.getId()]);
    if (urteil.werbung) {
      treffer.push(thread);
      Logger.log('[WERBUNG] %s  %s  %s', urteil.punkte, msg.getFrom(), msg.getSubject());
      Logger.log('          ' + urteil.gruende.join('; '));
    }
  });

  if (!treffer.length) { Logger.log('Keine Werbung gefunden.'); return; }
  if (!ausfuehren) {
    Logger.log('%s Mail(s) würden verschoben. Zum Ausführen "aufraeumen" starten.', treffer.length);
    return;
  }
  treffer.forEach(function (thread) {
    if (label) { thread.addLabel(label); thread.moveToArchive(); }
    else { thread.moveToSpam(); }
  });
  Logger.log('%s Mail(s) verschoben nach %s.', treffer.length, E.zielLabel || 'Spam');
}

function adresse_(from) {
  var m = String(from).match(/<([^>]+)>/);
  return (m ? m[1] : String(from)).trim().toLowerCase();
}

function passtListe_(adr, liste) {
  var domain = adr.split('@').pop();
  for (var i = 0; i < liste.length; i++) {
    var e = String(liste[i]).toLowerCase().replace(/^@/, '');
    if (adr === e || domain === e || domain.slice(-(e.length + 1)) === '.' + e) return e;
  }
  return null;
}

function bewerten_(msg, gmailWerbung) {
  var E = EINSTELLUNGEN;
  var adr = adresse_(msg.getFrom());
  var betreff = String(msg.getSubject() || '').toLowerCase();

  var w = passtListe_(adr, E.whitelist);
  if (w) return { werbung: false, punkte: 0, gruende: ['Whitelist (' + w + ')'] };
  var b = passtListe_(adr, E.blacklist);
  if (b) return { werbung: true, punkte: 99, gruende: ['Blacklist (' + b + ')'] };

  var punkte = 0, gruende = [];
  function plus(p, g) { punkte += p; gruende.push((p > 0 ? '+' : '') + p + ' ' + g); }

  if (gmailWerbung) plus(4, 'Gmail-Kategorie Werbung');
  if (msg.getHeader('List-Unsubscribe')) plus(3, 'Abmelde-Link');
  var prec = String(msg.getHeader('Precedence') || '').toLowerCase();
  if (['bulk', 'list', 'junk'].indexOf(prec) >= 0) plus(2, 'Precedence: ' + prec);
  if (msg.getHeader('List-Id')) plus(1, 'List-Id');
  for (var i = 0; i < MASSENVERSAND_HEADER.length; i++) {
    if (msg.getHeader(MASSENVERSAND_HEADER[i])) { plus(2, 'Massenversand (' + MASSENVERSAND_HEADER[i] + ')'); break; }
  }
  for (var j = 0; j < ABSENDER_MUSTER.length; j++) {
    if (ABSENDER_MUSTER[j].test(adr)) { plus(2, 'Absender ' + ABSENDER_MUSTER[j]); break; }
  }
  var kw = STICHWOERTER.filter(function (k) { return betreff.indexOf(k) >= 0; });
  if (kw.length) plus(Math.min(kw.length, 3), 'Stichwörter ' + kw.slice(0, 3).join(', '));
  if (/\d{1,2}\s?%/.test(betreff)) plus(1, 'Prozent im Betreff');
  if (/^\s*(re|aw|fwd?|wg)\s*:/.test(betreff)) plus(-5, 'Antwort/Weiterleitung');

  return { werbung: punkte >= E.schwelle, punkte: punkte, gruende: gruende };
}
