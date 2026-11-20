"""Avis Google de LaCannette → avis/avis-google.json (lu par le site, chaque nuit).

Utilise l'API Google Places (New). Gratuit à ce volume : 1 appel par jour.
Secret GitHub requis : GOOGLE_PLACES_KEY. Optionnel : GOOGLE_PLACE_ID
(sinon la fiche est retrouvée avec la recherche « LaCannette Porto-Vecchio »).
Pour masquer un avis : ajouter le nom de son auteur dans avis/masques.txt (un par ligne).
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "avis" / "avis-google.json"
MASQUES = ROOT / "avis" / "masques.txt"
KEY = os.environ.get("GOOGLE_PLACES_KEY", "").strip()
PLACE_ID = os.environ.get("GOOGLE_PLACE_ID", "").strip()
RECHERCHE = "LaCannette Porto-Vecchio"


def call(url, mask, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 method="POST" if body else "GET")
    req.add_header("X-Goog-Api-Key", KEY)
    req.add_header("X-Goog-FieldMask", mask)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    if not KEY:
        print("Secret GOOGLE_PLACES_KEY absent : rien à faire.")
        return 0
    pid = PLACE_ID
    if not pid:
        res = call("https://places.googleapis.com/v1/places:searchText", "places.id,places.displayName",
                   {"textQuery": RECHERCHE, "languageCode": "fr"})
        places = res.get("places") or []
        if not places:
            print(f"Fiche introuvable pour « {RECHERCHE} ».")
            return 1
        pid = places[0]["id"]
        print("Fiche trouvée :", places[0].get("displayName", {}).get("text"), pid)
    d = call(f"https://places.googleapis.com/v1/places/{pid}?languageCode=fr",
             "displayName,rating,userRatingCount,googleMapsUri,reviews")
    masques = set()
    if MASQUES.exists():
        masques = {l.strip().lower() for l in MASQUES.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
    avis = []
    for r in d.get("reviews") or []:
        nom = (r.get("authorAttribution") or {}).get("displayName", "").strip()
        texte = ((r.get("originalText") or r.get("text") or {}).get("text") or "").strip()
        if not nom or not texte or nom.lower() in masques:
            continue
        avis.append({
            "nom": nom,
            "note": r.get("rating", 5),
            "texte": texte,
            "quand": r.get("relativePublishTimeDescription", ""),
            "date": r.get("publishTime", ""),
            "lien": r.get("googleMapsUri") or (r.get("authorAttribution") or {}).get("uri", ""),
        })
    data = {
        "note": d.get("rating"),
        "total": d.get("userRatingCount"),
        "fiche": d.get("googleMapsUri", ""),
        "avis": avis,
    }
    OUT.parent.mkdir(exist_ok=True)
    old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    new = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    if old != new:
        OUT.write_text(new, encoding="utf-8")
        print(f"Avis mis à jour : {len(avis)} avis, note {data['note']} ({data['total']} avis au total).")
    else:
        print("Aucun changement.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
