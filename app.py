from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import os

app = Flask(__name__)
CORS(app)  # Permet les requêtes cross-origin

def extraire_medicament(code):
    url = f"https://medicament.ma/?choice=barcode&s={code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return {"erreur": f"Site inaccessible (code {resp.status_code})"}
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Vérifier si la page contient une erreur (par ex. "Aucun résultat")
        if "Aucun médicament trouvé" in resp.text or soup.find("h1") is None:
            return {"erreur": "Médicament non trouvé pour ce code-barres"}
        
        # Extraction du nom commercial
        titre = soup.find("h1")
        nom_commercial = titre.get_text(strip=True) if titre else ""
        
        # Initialisation
        dci = ""
        dosage = ""
        
        # Parcourir tous les paragraphes pour trouver Composition et Dosage
        for p in soup.find_all("p"):
            texte = p.get_text(strip=True)
            if "Composition" in texte:
                # Nettoyer : enlever "Composition" et les ":", puis espaces superflus
                dci = texte.replace("Composition", "").replace(":", "").strip()
            elif "Dosage" in texte:
                dosage = texte.replace("Dosage", "").replace(":", "").strip()
        
        # Extraction de la forme : on prend la partie après la virgule dans le nom commercial
        forme = ""
        if "," in nom_commercial:
            forme = nom_commercial.split(",")[-1].strip()
            # Parfois la forme est du type "Solution injectable (SC) en stylo pré-rempli de 1,5 ML"
            # On garde tel quel, c'est acceptable.
        
        return {
            "Code CIP": code,
            "Nom commercial": nom_commercial,
            "DCI": dci,
            "Dosage": dosage,
            "Forme": forme
        }
    
    except requests.exceptions.Timeout:
        return {"erreur": "Délai d'attente dépassé"}
    except requests.exceptions.ConnectionError:
        return {"erreur": "Erreur de connexion"}
    except Exception as e:
        return {"erreur": f"Erreur inattendue : {str(e)}"}

@app.route('/scan', methods=['GET'])
def scan():
    code = request.args.get('code')
    if not code:
        return jsonify({"erreur": "Paramètre 'code' manquant"}), 400
    
    # Nettoyage du code (enlever les espaces éventuels)
    code = code.strip()
    
    resultat = extraire_medicament(code)
    return jsonify(resultat)

@app.route('/')
def index():
    return "API de recherche de médicaments par code-barres - Utilisez /scan?code=VOTRE_CODE"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)