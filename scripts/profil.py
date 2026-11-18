"""Tâche « photo-profil » : met le logo LaCannette en photo de profil de la page Facebook,
puis vérifie ce que la clé Meta permet sur les commentaires Instagram (pour les réponses automatiques)."""
from common import CONFIG, PAGE, get, post, media_url, open_issue, scrub

lines = []
try:
    r = post(f"{PAGE}/picture", picture=media_url("marque/logo-profil.jpg"))
    lines.append(f"**Photo de profil Facebook :** Vérifié — mise à jour ({r})")
except Exception as e:  # noqa: BLE001
    lines.append(f"**Photo de profil Facebook :** ÉCHEC — {scrub(e)}")
ig = CONFIG.get("instagram_user_id") or CONFIG.get("instagram_id")
try:
    media = get(f"{ig}/media", fields="id", limit=3).get("data", [])
    if media:
        c = get(f"{media[0]['id']}/comments", fields="id,text,username", limit=5)
        lines.append(f"**Lecture des commentaires Instagram :** Vérifié — {len(c.get('data', []))} commentaire(s) lus sur le dernier post")
except Exception as e:  # noqa: BLE001
    lines.append(f"**Lecture des commentaires Instagram :** ÉCHEC — {scrub(e)}")
open_issue("Photo de profil et commentaires : résultat", "\n\n".join(lines))
print("\n".join(lines))
