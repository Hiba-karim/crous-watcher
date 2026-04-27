import requests
from bs4 import BeautifulSoup
import json
import os
import smtplib
import ssl
from email.message import EmailMessage

# ================== À PERSONNALISER ==================

URLS = [
    # Mets ici tes URLs de recherche CROUS filtrées
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.1807546_48.8616453_2.225689_48.8263653&locationName=Saint-Cloud+%2892210%29",
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.222799_48.853442_2.2627757_48.8214969&locationName=Boulogne-Billancourt+%2892100%29",
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.1997654_48.8827632_2.2367935_48.8593914&locationName=Suresnes+%2892150%29",
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.169302_48.9205991_2.234232_48.8742291&locationName=Nanterre+%2892000%29",
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.2224557_48.8956658_2.2543627_48.8695071&locationName=Puteaux+%2892800%29",
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.2357127_48.8346266_2.2893877_48.813264&locationName=Issy-les-Moulineaux+%2892130%29",
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.2026567_48.8239813_2.2550087_48.7815769&locationName=Meudon",
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.0699384_48.82861_2.1683504_48.7792297&locationName=Versailles+%2878000%29",
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.1758695_48.8209276_2.2060365_48.7972296&locationName=Chaville+%2892370%29",
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.1580547_48.8159419_2.1869771_48.7875442&locationName=Viroflay+%2878220%29",
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.1666593_48.8561246_2.2055225_48.8377372&locationName=Garches+%2892380%29",
    "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=2.1456536_48.851648_2.1826039_48.8213777&locationName=Vaucresson+%2892420%29"]

STATE_FILE = "known_accommodations.json"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

if not SMTP_USER or not SMTP_PASSWORD or not EMAIL_TO:
    raise RuntimeError("Variables d'environnement SMTP_USER / SMTP_PASSWORD / EMAIL_TO manquantes")

EMAIL_FROM = SMTP_USER

# =====================================================


def fetch_html(url: str) -> str:
    resp = requests.get(url, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.text


def parse_accommodations(html: str):
    """
    Retourne une liste de dicts :
    [
      {"id": "/tools/42/accommodations/1671", "name": "Torcy", "price": "450 €", "href": "..."},
      ...
    ]
    """
    soup = BeautifulSoup(html, "html.parser", from_encoding="utf-8")
    results = []

    for card in soup.select("div.fr-card"):
        title_a = card.select_one("h3.fr-card__title a")
        if not title_a:
            continue

        name = title_a.get_text(strip=True)
        href = title_a.get("href", "").strip()

        price_el = card.select_one("p.fr-badge")
        price = price_el.get_text(strip=True) if price_el else None

        acc_id = href or name  # ID unique pour suivre le logement

        results.append(
            {
                "id": acc_id,
                "name": name,
                "price": price,
                "href": href,
            }
        )

    return results


def load_state(path: str):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send_email(subject: str, body: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


def main():
    state = load_state(STATE_FILE)  # {url: [id1, id2, ...]}

    all_new = []  # pour construire le mail final

    for url in URLS:
        print(f"Check URL: {url}")
        html = fetch_html(url)
        accs = parse_accommodations(html)

        known_ids = set(state.get(url, []))
        current_ids = {a["id"] for a in accs}

        # ⚠️ différence importante :
        # - si known_ids est vide => on considère TOUS les logements comme "nouveaux"
        # - sinon => seulement ceux qui n'étaient pas encore vus
        if not known_ids:
            print("  Première exécution pour cette URL, on prend tous les logements comme nouveaux.")
            new_ids = current_ids
        else:
            new_ids = current_ids - known_ids

        if new_ids:
            print(f"  {len(new_ids)} nouveau(x) logement(s) détecté(s).")
            new_accs = [a for a in accs if a["id"] in new_ids]
            all_new.append((url, new_accs))

        # on met à jour l'état dans tous les cas
        state[url] = list(current_ids)

    # On sauvegarde l'état (pour les prochaines exécutions)
    save_state(STATE_FILE, state)

    if not all_new:
        print("Aucun nouveau logement sur l'ensemble des URLs, pas de mail.")
        return

    # Construire le mail avec uniquement les logements détectés comme nouveaux
    lines = []
    lines.append("Nouveaux logements CROUS détectés :\n")

    total_new = 0
    for url, accs in all_new:
        if not accs:
            continue
        lines.append(f"URL : {url}")
        for a in accs:
            total_new += 1
            full_url = "https://trouverunlogement.lescrous.fr" + a["href"]  # ← ajoute ça
            if a["price"]:
                lines.append(f"- {a['name']} ({a['price']}) → {full_url}")  # ← modifie ça
            else:
                lines.append(f"- {a['name']} → {full_url}") ['name']}")
        lines.append("")

    if total_new == 0:
        print("Pas de nouveaux logements après filtrage, pas de mail.")
        return

    body = "\n".join(lines)
    subject = f"[CROUS] {total_new} nouveau(x) logement(s)"

    print("Envoi du mail de test / notification...")
    send_email(subject, body)
    print("Mail envoyé.")


if __name__ == "__main__":
    main()
