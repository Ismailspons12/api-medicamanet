from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import time
import re

app = Flask(__name__)
CORS(app)  # Permet les appels depuis n'importe quelle origine

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
BASE_URL = "https://medicament.ma"

# -------------------------------------------------------------------
# 1. Recherche par code-barres (existant, amélioré)
# -------------------------------------------------------------------
def extract_by_barcode(code):
    url = f"{BASE_URL}/?choice=barcode&s={code}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Nom commercial
        nom_tag = soup.find("h1")
        nom = nom_tag.get_text(strip=True) if nom_tag else ""

        # DCI, Dosage, etc.
        dci = dosage = forme = ""
        for p in soup.find_all("p"):
            texte = p.get_text(strip=True)
            if "Composition" in texte:
                dci = texte.replace("Composition", "").replace(":", "").strip()
            if "Dosage" in texte:
                dosage = texte.replace("Dosage", "").replace(":", "").strip()
            if "Présentation" in texte and not forme:
                # On garde la présentation comme forme si on ne trouve pas mieux
                forme = texte.replace("Présentation", "").replace(":", "").strip()

        # Extraire la forme depuis le nom (après la virgule)
        if "," in nom:
            forme_candidate = nom.split(",")[-1].strip()
            if forme_candidate and not forme_candidate[0].isdigit():
                forme = forme_candidate

        return {
            "Code CIP": code,
            "Nom commercial": nom,
            "DCI": dci,
            "Dosage": dosage,
            "Forme": forme
        }
    except Exception as e:
        return {"erreur": f"Erreur lors de l'extraction : {str(e)}"}

@app.route('/scan')
def scan_barcode():
    code = request.args.get('code')
    if not code:
        return jsonify({"erreur": "Code-barres manquant"}), 400
    result = extract_by_barcode(code)
    return jsonify(result)

# -------------------------------------------------------------------
# 2. RECHERCHE PAR NOM (NOUVEAU)
# -------------------------------------------------------------------
def search_by_name(term):
    """
    Interroge la page de recherche de medicament.ma et retourne la liste
    des médicaments correspondants avec les informations essentielles.
    """
    url = f"{BASE_URL}/?comparison=contains&choice=specialite&keyword=contains&s={term}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')

        results = []
        # Sélecteur approximatif : chercher tous les liens vers des fiches produits
        # La structure réelle est à adapter si nécessaire
        product_links = soup.select('a[href*="choice=barcode&s="]')

        for link in product_links:
            href = link.get('href')
            # Extraire le code-barres depuis le lien
            match = re.search(r's=(\d+)', href)
            if not match:
                continue
            code = match.group(1)

            # Le parent contient souvent le nom et d'autres infos
            parent = link.find_parent(['div', 'article', 'li'])
            if not parent:
                continue

            # Nom du médicament (souvent le texte du lien ou un titre proche)
            nom = link.get_text(strip=True)
            if not nom:
                # Chercher un titre dans le parent
                titre = parent.find(['h2', 'h3', 'strong'])
                if titre:
                    nom = titre.get_text(strip=True)

            # Extraire quelques infos supplémentaires (prix, labo, présentation)
            prix = ""
            labo = ""
            presentation = ""

            # Chercher des motifs comme "PPV: 9.10 dhs", "- LAPROPHAN"
            text_parent = parent.get_text(" ", strip=True)
            # Prix
            prix_match = re.search(r'PPV:\s*([\d\s,.]+)\s*dhs', text_parent)
            if prix_match:
                prix = prix_match.group(1).replace(" ", "") + " dhs"
            # Laboratoire (souvent après un tiret)
            labo_match = re.search(r'-\s*([A-Za-z\s]+?)(?:\s|$)', text_parent)
            if labo_match:
                labo = labo_match.group(1).strip()
            # Présentation (ex: "Boite de 12")
            pres_match = re.search(r'(Bo[iî]te\s+de\s+\d+)', text_parent, re.IGNORECASE)
            if pres_match:
                presentation = pres_match.group(1)

            results.append({
                "code_barre": code,
                "nom": nom,
                "prix": prix,
                "laboratoire": labo,
                "presentation": presentation,
                "url_detail": href if href.startswith('http') else BASE_URL + href
            })

        # Éviter les doublons (même code)
        unique = {item['code_barre']: item for item in results}.values()
        return list(unique)

    except Exception as e:
        return {"erreur": f"Erreur recherche : {str(e)}"}

@app.route('/search')
def search():
    term = request.args.get('name')
    if not term:
        return jsonify({"erreur": "Paramètre 'name' manquant"}), 400
    results = search_by_name(term)
    return jsonify(results)

# -------------------------------------------------------------------
# Démarrer le serveur
# -------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
