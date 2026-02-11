from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re

app = Flask(__name__)
CORS(app)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
BASE_URL = "https://medicament.ma"

# -------------------------------------------------------------------
# 1. Fonction générique d'extraction depuis UNE PAGE détaillée
#    (quel que soit le moyen d'y accéder : code-barres ou lien direct)
# -------------------------------------------------------------------
def extract_medicine_from_page(soup, code_barre=None):
    """
    Extrait les 5 champs depuis une page de détail (BeautifulSoup).
    Supporte à la fois l'ancienne structure (p/strong) et la nouvelle (medicine-details).
    Si code_barre est fourni, l'utilise, sinon tente de le trouver dans la page.
    """
    result = {
        "Code CIP": code_barre or "",
        "Nom commercial": "",
        "DCI": "",
        "Dosage": "",
        "Forme": ""
    }

    # ----- 1. Nom commercial (toujours dans <h1>) -----
    h1 = soup.find("h1")
    if h1:
        result["Nom commercial"] = h1.get_text(strip=True)

    # ----- 2. Détection du code-barres s'il n'est pas fourni -----
    if not result["Code CIP"]:
        result["Code CIP"] = find_barcode_in_page(soup)

    # ----- 3. Extraction par la structure "medicine-details" (NOUVELLE) -----
    details_block = soup.find("div", class_="medicine-details")
    if details_block:
        items = details_block.find_all("div", class_="detail-item")
        for item in items:
            header = item.find("div", class_="detail-header")
            content = item.find("div", class_="detail-content")
            if not header or not content:
                continue
            header_text = header.get_text(strip=True).lower()
            value = content.get_text(" ", strip=True)

            if "composition" in header_text:
                result["DCI"] = value
            elif "dosage" in header_text:
                result["Dosage"] = value
            # Pour la forme, on l'extrait plus tard (depuis le nom ou présentation)
            # mais on peut stocker la présentation pour aide
            elif "présentation" in header_text:
                result["_presentation"] = value
    else:
        # ----- 4. Extraction par l'ancienne structure (p / strong) -----
        # DCI
        comp = soup.find('p', string=re.compile(r'^Composition', re.I))
        if comp:
            result["DCI"] = comp.get_text(strip=True).replace("Composition", "", 1).replace(":", "").strip()
        else:
            strong = soup.find(['strong', 'b'], string=re.compile(r'Composition', re.I))
            if strong:
                parent = strong.find_parent('p')
                if parent:
                    text = parent.get_text(" ", strip=True)
                    result["DCI"] = text.replace("Composition", "", 1).replace(":", "").strip()
                else:
                    next_node = strong.next_sibling
                    if next_node:
                        result["DCI"] = next_node.strip()
        # Dosage
        dos = soup.find('p', string=re.compile(r'^Dosage', re.I))
        if dos:
            result["Dosage"] = dos.get_text(strip=True).replace("Dosage", "", 1).replace(":", "").strip()
        else:
            strong = soup.find(['strong', 'b'], string=re.compile(r'Dosage', re.I))
            if strong:
                parent = strong.find_parent('p')
                if parent:
                    text = parent.get_text(" ", strip=True)
                    result["Dosage"] = text.replace("Dosage", "", 1).replace(":", "").strip()
                else:
                    next_node = strong.next_sibling
                    if next_node:
                        result["Dosage"] = next_node.strip()

    # ----- 5. Nettoyage des champs -----
    result["DCI"] = re.sub(r'\s+', ' ', result["DCI"]).strip()
    result["Dosage"] = re.sub(r'\s+', ' ', result["Dosage"]).strip()

    # ----- 6. Extraction de la FORME -----
    forme = ""
    # Stratégie 1 : depuis le nom (après la virgule)
    if "," in result["Nom commercial"]:
        candidate = result["Nom commercial"].split(",")[-1].strip()
        if candidate and not re.match(r'^[\d\s,.]+\s*MG?$', candidate, re.I):
            forme = candidate
    # Stratégie 2 : depuis la présentation (nouvelle structure)
    if not forme and "_presentation" in result:
        pres = result["_presentation"].lower()
        formes_list = ["comprimé", "gélule", "sirop", "solution", "sachet", "pommade", "crème",
                       "suppositoire", "ovule", "collyre", "ampoule", "stylo", "patch", "inhaleur"]
        for f in formes_list:
            if f in pres:
                forme = result["_presentation"]
                break
    # Stratégie 3 : depuis la présentation (ancienne structure)
    if not forme:
        pres_p = soup.find('p', string=re.compile(r'^Présentation', re.I))
        if pres_p:
            pres_text = pres_p.get_text(strip=True).replace("Présentation", "", 1).replace(":", "").strip()
            for f in formes_list:
                if f in pres_text.lower():
                    forme = pres_text
                    break
    # Stratégie 4 : dernière chance, on prend ce qu'il y a après la virgule
    if not forme and "," in result["Nom commercial"]:
        forme = result["Nom commercial"].split(",")[-1].strip()

    result["Forme"] = forme
    # Supprimer le champ temporaire
    result.pop("_presentation", None)

    return result

def find_barcode_in_page(soup):
    """Cherche un code-barres (CIP13) dans la page."""
    # 1. Lien avec choice=barcode&s=
    barcode_link = soup.find('a', href=re.compile(r'choice=barcode&s=\d+'))
    if barcode_link:
        href = barcode_link['href']
        match = re.search(r's=(\d+)', href)
        if match:
            return match.group(1)
    # 2. Canonical
    canonical = soup.find('link', rel='canonical')
    if canonical:
        href = canonical.get('href', '')
        match = re.search(r's=(\d+)', href)
        if match:
            return match.group(1)
    # 3. Texte contenant 13 chiffres (CIP13) ou 611... (code marocain?)
    text = soup.get_text()
    cip_match = re.search(r'\b(611\d{9}|\d{13})\b', text)
    if cip_match:
        return cip_match.group(1)
    return ""

# -------------------------------------------------------------------
# 2. Endpoint /scan (par code-barres)
# -------------------------------------------------------------------
@app.route('/scan')
def scan_barcode():
    code = request.args.get('code')
    if not code:
        return jsonify({"erreur": "Code-barres manquant"}), 400

    url = f"{BASE_URL}/?choice=barcode&s={code}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Vérifier que la page contient un médicament
        if not soup.find("h1"):
            return jsonify({"erreur": "Médicament non trouvé pour ce code-barres"}), 404

        data = extract_medicine_from_page(soup, code_barre=code)
        return jsonify(data)

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return jsonify({"erreur": "Code-barres non trouvé sur medicament.ma"}), 404
        return jsonify({"erreur": f"Erreur HTTP {e.response.status_code}"}), 500
    except Exception as e:
        return jsonify({"erreur": f"Erreur : {str(e)}"}), 500

# -------------------------------------------------------------------
# 3. Recherche par nom (inchangée)
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
                "code_barre": "",
                "nom": nom,
                "laboratoire": labo,
                "prix": prix,
                "presentation": presentation,
                "url_detail": detail_url
            })

        return jsonify(results)

    except Exception as e:
        return jsonify({"erreur": str(e)}), 500

# -------------------------------------------------------------------
# 4. Résolution d'une URL détaillée (utilise l'extraction unifiée)
# -------------------------------------------------------------------
@app.route('/resolve-detail')
def resolve_detail():
    url = request.args.get('url')
    if not url:
        return jsonify({"erreur": "URL manquante"}), 400

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        data = extract_medicine_from_page(soup)
        if not data["Code CIP"]:
            return jsonify({"erreur": "Impossible de trouver le code-barres pour ce médicament"}), 404
        return jsonify(data)

    except Exception as e:
        return jsonify({"erreur": f"Erreur lors de la résolution : {str(e)}"}), 500

# -------------------------------------------------------------------
# 5. Debug (optionnel)
# -------------------------------------------------------------------
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
    app.run(host='0.0.0.0', port=5000)
