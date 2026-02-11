from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
import time

app = Flask(__name__)
CORS(app)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
BASE_URL = "https://medicament.ma"

# -------------------------------------------------------------------
# 1. Recherche par code-barres
# -------------------------------------------------------------------
def extract_by_barcode(code):
    url = f"{BASE_URL}/?choice=barcode&s={code}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        nom_tag = soup.find("h1")
        nom = nom_tag.get_text(strip=True) if nom_tag else ""
        dci = dosage = forme = ""
        for p in soup.find_all("p"):
            texte = p.get_text(strip=True)
            if "Composition" in texte:
                dci = texte.replace("Composition", "").replace(":", "").strip()
            if "Dosage" in texte:
                dosage = texte.replace("Dosage", "").replace(":", "").strip()
            if "Présentation" in texte and not forme:
                forme = texte.replace("Présentation", "").replace(":", "").strip()
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
        return {"erreur": str(e)}

@app.route('/scan')
def scan_barcode():
    code = request.args.get('code')
    if not code:
        return jsonify({"erreur": "Code-barres manquant"}), 400
    return jsonify(extract_by_barcode(code))

# -------------------------------------------------------------------
# 2. RECHERCHE PAR NOM – CORRIGÉE
# -------------------------------------------------------------------
@app.route('/search')
def search_by_name():
    term = request.args.get('name')
    if not term:
        return jsonify({"erreur": "Paramètre 'name' manquant"}), 400

    url = f"{BASE_URL}/?comparison=contains&choice=specialite&keyword=contains&s={term}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')

        results = []
        # Méthode plus fiable : chercher les blocs <article> ou <div> contenant les résultats
        # Sur medicament.ma, les résultats sont souvent dans des <div class="product-item">
        product_blocks = soup.find_all('div', class_=re.compile('product|item|result|card'))

        if not product_blocks:
            # Fallback : chercher tous les liens contenant "choice=barcode&s="
            product_links = soup.find_all('a', href=re.compile(r'choice=barcode&s=\d+'))
            seen_codes = set()
            for link in product_links:
                href = link.get('href', '')
                match = re.search(r's=(\d+)', href)
                if not match:
                    continue
                code = match.group(1)
                if code in seen_codes:
                    continue
                seen_codes.add(code)

                nom = link.get_text(strip=True)
                if not nom:
                    parent = link.find_parent(['div', 'article', 'li'])
                    if parent:
                        titre = parent.find(['h2', 'h3', 'strong'])
                        nom = titre.get_text(strip=True) if titre else ""

                # Extraire le laboratoire et le prix depuis le texte parent
                labo = ""
                prix = ""
                if parent:
                    text = parent.get_text(" ", strip=True)
                    # Laboratoire (après un tiret)
                    labo_match = re.search(r'-\s*([A-Za-z\séèêâîôûïëç]+?)(?:\s|$)', text)
                    if labo_match:
                        labo = labo_match.group(1).strip()
                    # Prix
                    prix_match = re.search(r'PPV:\s*([\d\s,.]+)\s*dhs', text)
                    if prix_match:
                        prix = prix_match.group(1).replace(" ", "") + " dhs"

                results.append({
                    "code_barre": code,
                    "nom": nom,
                    "laboratoire": labo,
                    "prix": prix,
                    "url_detail": href if href.startswith('http') else BASE_URL + href
                })

        return jsonify(results)

    except Exception as e:
        return jsonify({"erreur": f"Erreur recherche : {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
