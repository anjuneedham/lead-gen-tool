"""Website enrichment: turn a homepage into buying signals.

A phone number and an address are commodity data — anyone can buy that list.
What actually predicts whether a business will buy a messaging product is how
they already operate: do they run bookings through WhatsApp, are they on a
booking platform already, can a human even reach them. That's what this reads.
"""

import re
import urllib.robotparser
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

TIMEOUT = 10
CONTACT_KEYWORDS = ("contact", "about", "kontakt", "contacto", "contatto", "impressum", "nous-contacter")
MAX_CONTACT_PAGES = 2
MAX_PAGE_BYTES = 2_000_000

USER_AGENT = "Mozilla/5.0 (compatible; LeadGenResearchBot/0.2; +local research tool)"

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._%+-]*@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
MAILTO_REGEX = re.compile(r'href=["\']mailto:([^"\'?]+)', re.IGNORECASE)

# wa.me/351912345678, api.whatsapp.com/send?phone=..., whatsapp://send?phone=...
WHATSAPP_LINK_REGEX = re.compile(
    r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=|whatsapp://send\?phone=|web\.whatsapp\.com/send\?phone=)"
    r"\+?(\d{6,20})",
    re.IGNORECASE,
)
WHATSAPP_ANY_REGEX = re.compile(r"wa\.me|whatsapp", re.IGNORECASE)

SOCIAL_PATTERNS = {
    "instagram": re.compile(r"instagram\.com/([A-Za-z0-9_.]+)", re.IGNORECASE),
    "facebook": re.compile(r"facebook\.com/([A-Za-z0-9_.\-]+)", re.IGNORECASE),
    "linkedin": re.compile(r"linkedin\.com/(?:company|in)/([A-Za-z0-9_.\-]+)", re.IGNORECASE),
}

# Booking/PMS platforms. Presence means they already pay for software — a
# different conversation than someone running a spreadsheet.
BOOKING_PLATFORMS = {
    "lodgify": "lodgify.com",
    "guesty": "guesty.com",
    "hostaway": "hostaway.com",
    "smoobu": "smoobu.com",
    "avantio": "avantio.com",
    "cloudbeds": "cloudbeds.com",
    "beds24": "beds24.com",
    "ownerrez": "ownerrez.com",
    "bookingsync": "bookingsync.com",
    "hostfully": "hostfully.com",
    "checkfront": "checkfront.com",
    "fareharbor": "fareharbor.com",
    "rezdy": "rezdy.com",
    "bookeo": "bookeo.com",
    "hqrentals": "hqrentals.app",
    "navotar": "navotar.com",
    "rentsyst": "rentsyst.com",
    "thermeon": "thermeon.com",
    "booking.com": "booking.com",
    "airbnb": "airbnb.",
    "vrbo": "vrbo.com",
}

EMAIL_BLOCKLIST_DOMAINS = (
    "sentry.io", "wixpress.com", "example.com", "godaddy.com",
    "yourdomain.com", "domain.com", "email.com", "sentry-next.wixpress.com",
)
EMAIL_BLOCKLIST_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")

# Matched as prefixes, so "reserva" also catches reservas/reservation(s), and
# "info" catches informacion/informazioni/informatie. These are deliberately
# multilingual — an English-only list quietly picks the wrong address in half
# the world, e.g. preferring 'recrutamento@' over 'reservas@' in Portugal.
BOOKING_INTENT_PREFIXES = (
    # English
    "reservation", "reservations", "booking", "bookings", "enquir", "inquir",
    "sales", "rental", "stay",
    # Portuguese / Spanish
    "reserva", "vendas", "ventas", "comercial", "atencion", "atendimento",
    # French
    "reserv", "accueil",
    # Italian
    "prenotazion",
    # German / Dutch
    "buchung", "anfrage", "vertrieb", "boeking", "verkoop",
    # Nordic / Slavic / Turkish / Indonesian
    "rezervacij", "rezerwacj", "rezervasyon", "pemesanan", "booking",
)

GENERAL_CONTACT_PREFIXES = (
    "info", "contact", "kontakt", "contatt", "hello", "hallo", "hola", "office",
    "reception", "empfang", "admin", "team", "mail", "welcome", "bienvenue",
    "iletisim", "biuro",
)

# Real addresses, wrong desk. Also multilingual.
DEPRIORITIZED_EMAIL_PREFIXES = (
    # Hiring
    "career", "job", "recruit", "recrut", "reclut", "empleo", "bewerbung",
    "kariyer", "trabalh", "lavoraconnoi",
    # Press
    "press", "media", "imprensa", "prensa", "presse", "stampa",
    # Legal / privacy / finance
    "privac", "legal", "juridic", "gdpr", "dpo", "datenschutz", "abuse",
    "billing", "invoice", "factur", "fatur", "rechnung", "buchhaltung",
    "contabil", "accounts", "accounting",
    # Machine addresses
    "webmaster", "postmaster", "hostmaster", "noreply", "no-reply",
    "donotreply", "unsubscribe", "mailer-daemon",
)

BOOKING_INTENT_SCORE = 100
GENERAL_CONTACT_SCORE = 70
GOOD_EMAIL_SCORE = 50  # at or above this, stop crawling for something better


@dataclass
class Enrichment:
    """Everything the website told us. All fields degrade to empty, never None."""

    email: str = ""
    all_emails: list = field(default_factory=list)
    whatsapp_number: str = ""
    uses_whatsapp: bool = False
    socials: dict = field(default_factory=dict)
    booking_platforms: list = field(default_factory=list)
    has_contact_form: bool = False
    site_reachable: bool = False
    pages_crawled: int = 0
    blocked_by_robots: bool = False
    error: str = ""


def score_email(email, site_domain=""):
    """Rank an email by how useful it is as an outreach contact (higher is better).

    Tiered rather than positional, so adding a language to the lists above
    can't shuffle the ranking of everything after it.
    """
    local, _, domain = email.partition("@")
    score = 0

    if any(local.startswith(prefix) for prefix in BOOKING_INTENT_PREFIXES):
        score += BOOKING_INTENT_SCORE
    elif any(local.startswith(prefix) for prefix in GENERAL_CONTACT_PREFIXES):
        score += GENERAL_CONTACT_SCORE

    if any(local.startswith(prefix) for prefix in DEPRIORITIZED_EMAIL_PREFIXES):
        score -= 150

    # An address on the business's own domain beats a web agency's.
    if site_domain and domain == site_domain:
        score += 10

    return score


def pick_best_email(emails, site_domain=""):
    if not emails:
        return ""
    return max(sorted(emails), key=lambda e: score_email(e, site_domain))


def is_valid_email(email):
    email = email.lower().strip().strip(".,;:")
    if not EMAIL_REGEX.fullmatch(email):
        return False
    if email.split("@")[-1] in EMAIL_BLOCKLIST_DOMAINS:
        return False
    if email.endswith(EMAIL_BLOCKLIST_EXTENSIONS):
        return False
    return True


def extract_emails(html, soup):
    found = set()
    for match in MAILTO_REGEX.finditer(html):
        candidate = unescape(match.group(1)).strip().split("?")[0]
        if is_valid_email(candidate):
            found.add(candidate.lower())
    for match in EMAIL_REGEX.finditer(soup.get_text(" ")):
        if is_valid_email(match.group(0)):
            found.add(match.group(0).lower())
    return found


def extract_signals(html, soup, into):
    """Read WhatsApp, social and booking-platform signals out of one page."""
    match = WHATSAPP_LINK_REGEX.search(html)
    if match:
        into.uses_whatsapp = True
        if not into.whatsapp_number:
            into.whatsapp_number = "+" + match.group(1)
    elif WHATSAPP_ANY_REGEX.search(html):
        # Mentions WhatsApp without a click-to-chat link — still a signal that
        # they take enquiries there, just not a dialable number.
        into.uses_whatsapp = True

    for network, pattern in SOCIAL_PATTERNS.items():
        if network in into.socials:
            continue
        found = pattern.search(html)
        if found and found.group(1).lower() not in ("sharer", "share", "plugins", "tr", "profile.php"):
            into.socials[network] = found.group(1)

    lowered = html.lower()
    for name, needle in BOOKING_PLATFORMS.items():
        if needle in lowered and name not in into.booking_platforms:
            into.booking_platforms.append(name)

    if not into.has_contact_form:
        for form in soup.find_all("form"):
            inputs = form.find_all(["input", "textarea"])
            if any(
                (i.get("type") == "email" or i.name == "textarea" or "mail" in (i.get("name") or "").lower())
                for i in inputs
            ):
                into.has_contact_form = True
                break


class SiteEnricher:
    def __init__(self, session=None, sleep=None, delay=1.5, respect_robots=True):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.delay = delay
        self.respect_robots = respect_robots
        self._robots = {}
        if sleep is None:
            import time as _time

            sleep = _time.sleep
        self.sleep = sleep

    def _allowed(self, url):
        if not self.respect_robots:
            return True
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(root)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(urljoin(root, "/robots.txt"))
            try:
                response = self.session.get(urljoin(root, "/robots.txt"), timeout=TIMEOUT)
                if response.status_code == 200:
                    parser.parse(response.text.splitlines())
                else:
                    parser.parse([])  # no robots.txt = crawling allowed
            except requests.RequestException:
                parser.parse([])
            self._robots[root] = parser
        try:
            return parser.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def _fetch(self, url):
        try:
            response = self.session.get(url, timeout=TIMEOUT, stream=True)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                return None
            content = response.raw.read(MAX_PAGE_BYTES, decode_content=True)
            return content.decode(response.encoding or "utf-8", errors="replace")
        except (requests.RequestException, ValueError, OSError):
            return None

    def enrich(self, website):
        """Crawl a business site for contact and operating signals."""
        result = Enrichment()
        if not website:
            return result

        url = website if website.startswith(("http://", "https://")) else f"https://{website}"
        site_domain = urlparse(url).netloc.lower().removeprefix("www.")

        if not self._allowed(url):
            result.blocked_by_robots = True
            result.error = "disallowed by robots.txt"
            return result

        self.sleep(self.delay)
        html = self._fetch(url)
        if not html:
            result.error = "homepage unreachable"
            return result

        result.site_reachable = True
        result.pages_crawled = 1
        soup = BeautifulSoup(html, "html.parser")
        emails = extract_emails(html, soup)
        extract_signals(html, soup, result)

        best = pick_best_email(emails, site_domain)
        needs_more = not best or score_email(best, site_domain) < GOOD_EMAIL_SCORE
        if needs_more:
            for link in self._contact_links(soup, url):
                if not self._allowed(link):
                    continue
                self.sleep(self.delay)
                sub_html = self._fetch(link)
                if not sub_html:
                    continue
                result.pages_crawled += 1
                sub_soup = BeautifulSoup(sub_html, "html.parser")
                emails |= extract_emails(sub_html, sub_soup)
                extract_signals(sub_html, sub_soup, result)
                best = pick_best_email(emails, site_domain)
                if best and score_email(best, site_domain) >= GOOD_EMAIL_SCORE:
                    break

        result.email = best
        result.all_emails = sorted(emails)
        return result

    def _contact_links(self, soup, base_url):
        base_domain = urlparse(base_url).netloc
        links, seen = [], set()
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            absolute = urljoin(base_url, href)
            if urlparse(absolute).netloc != base_domain:
                continue
            haystack = f"{href} {anchor.get_text(' ')}".lower()
            if any(keyword in haystack for keyword in CONTACT_KEYWORDS) and absolute not in seen:
                seen.add(absolute)
                links.append(absolute)
        return links[:MAX_CONTACT_PAGES]
