from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re

app = Flask(__name__)
CORS(app)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
BASE_URL = "https://medicament.ma"

# ---------- Scan par code-barres ----------
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

# ---------- Recherche par nom ----------
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
        items = soup.select('li.listing-item')
        for item in items:
            link = item.find('a')
            if not link:
                continue
            href = link.get('href')
            detail_url = href if href.startswith('http') else BASE_URL + href
            p_primary = link.find('p', class_='primary')
            nom = p_primary.get_text(strip=True) if p_primary else ""
            span_secondary = link.find('span', class_='secondary')
            labo = prix = presentation = ""
            if span_secondary:
                text = span_secondary.get_text(" ", strip=True)
                labo_match = re.search(r'-\s*([^-\n]+)$', text)
                if labo_match:
                    labo = labo_match.group(1).strip()
                prix_match = re.search(r'PPV:\s*([\d\s,.]+)\s*dhs', text)
                if prix_match:
                    prix = prix_match.group(1).replace(" ", "") + " dhs"
                pres_match = re.search(r'(Bo[iî]te\s+de\s+\d+(?:\s+\w+)?)', text, re.I)
                if pres_match:
                    presentation = pres_match.group(1)
            results.append({
                "code_barre": "",  # à remplir plus tard
                "nom": nom,
                "laboratoire": labo,
                "prix": prix,
                "presentation": presentation,
                "url_detail": detail_url
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500

# ---------- Debug : page détaillée ----------
@app.route('/debug-detail')
def debug_detail():
    url = request.args.get('url')
    if not url:
        return "Paramètre 'url' manquant", 400
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        return resp.text
    except Exception as e:
        return f"Erreur: {str(e)}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
