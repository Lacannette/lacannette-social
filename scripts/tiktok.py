"""TikTok : connexion du compte, stockage chiffré des jetons, envoi des contenus.

Les jetons ne sont jamais écrits en clair : ils sont chiffrés avec une clé dérivée
du secret client TikTok (secret GitHub) et rangés dans rapports/tiktok.enc.
"""
import base64
import datetime as dt
import hashlib
import json
import os
import time
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken

from common import ROOT, CONFIG, MetaError, media_url, is_video, open_issue

API = "https://open.tiktokapis.com/v2"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
SCOPES = "user.info.basic,video.upload,video.publish"
REDIRECT = CONFIG["media_base_url"].rstrip("/") + "/retour.html"
STORE = os.path.join(ROOT, "rapports", "tiktok.enc")

KEY = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()


class TikTokError(MetaError):
    pass


def _fernet():
    if not SECRET:
        raise TikTokError("Secret TIKTOK_CLIENT_SECRET absent")
    digest = hashlib.sha256(("lacannette-tiktok:" + SECRET).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def scrub(text):
    text = str(text)
    for s in (SECRET, KEY):
        if s:
            text = text.replace(s, "***")
    return text


def load_tokens():
    if not os.path.exists(STORE):
        return None
    try:
        with open(STORE, "rb") as f:
            return json.loads(_fernet().decrypt(f.read()))
    except (InvalidToken, ValueError):
        raise TikTokError("Jetons TikTok illisibles : refaire la connexion")


def save_tokens(tok):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "wb") as f:
        f.write(_fernet().encrypt(json.dumps(tok).encode()))


def _token_request(data):
    data.update({"client_key": KEY, "client_secret": SECRET})
    try:
        r = requests.post(f"{API}/oauth/token/", data=data, timeout=60,
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        body = r.json()
    except (requests.RequestException, ValueError) as e:
        raise TikTokError(scrub(f"TikTok injoignable : {e}"))
    if "access_token" not in body:
        raise TikTokError(scrub(f"TikTok refuse la connexion : {body.get('error_description') or body.get('error') or body}"))
    now = int(time.time())
    return {
        "access_token": body["access_token"],
        "access_expires": now + int(body.get("expires_in", 86400)),
        "refresh_token": body["refresh_token"],
        "refresh_expires": now + int(body.get("refresh_expires_in", 31536000)),
        "open_id": body.get("open_id"),
        "scope": body.get("scope"),
    }


def connect(code):
    """Échange le code reçu sur la page de retour contre des jetons."""
    tok = _token_request({"code": code.strip(), "grant_type": "authorization_code",
                          "redirect_uri": REDIRECT})
    save_tokens(tok)
    return tok


def access_token():
    tok = load_tokens()
    if not tok:
        raise TikTokError("Compte TikTok non connecté")
    if tok["access_expires"] - time.time() < 3600:
        if tok["refresh_expires"] < time.time():
            raise TikTokError("Autorisation TikTok expirée : refaire la connexion")
        tok = _token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
        save_tokens(tok)
    return tok["access_token"]


def refresh_deadline():
    tok = load_tokens()
    if not tok:
        return None
    return dt.datetime.fromtimestamp(tok["refresh_expires"], dt.timezone.utc).date()


def _call(path, body=None):
    try:
        r = requests.post(f"{API}{path}", json=body or {}, timeout=60,
                          headers={"Authorization": f"Bearer {access_token()}",
                                   "Content-Type": "application/json; charset=UTF-8"})
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        raise TikTokError(scrub(f"TikTok injoignable : {e}"))
    err = data.get("error", {})
    if r.status_code >= 400 or (err and err.get("code") not in (None, "ok")):
        raise TikTokError(scrub(f"{err.get('message') or 'erreur'} (code {err.get('code')}, HTTP {r.status_code})"))
    return data.get("data", {})


def user_info():
    try:
        r = requests.get(f"{API}/user/info/", params={"fields": "open_id,display_name,avatar_url"},
                         headers={"Authorization": f"Bearer {access_token()}"}, timeout=60)
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        raise TikTokError(scrub(f"TikTok injoignable : {e}"))
    err = data.get("error", {})
    if err and err.get("code") not in (None, "ok"):
        raise TikTokError(scrub(f"{err.get('message')} (code {err.get('code')})"))
    return data.get("data", {}).get("user", {})


def _wait(publish_id, max_wait=600):
    start = time.time()
    while True:
        st = _call("/post/publish/status/fetch/", {"publish_id": publish_id})
        status = st.get("status")
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return status
        if status == "FAILED":
            raise TikTokError(f"TikTok a refusé le contenu ({st.get('fail_reason', 'raison inconnue')})")
        if time.time() - start > max_wait:
            raise TikTokError("Traitement TikTok trop long (plus de 10 min)")
        time.sleep(10)


def publish(item, urls):
    """Envoie le contenu dans la boîte de réception TikTok du compte.

    Tant que l'application n'a pas passé l'audit TikTok, seul cet envoi en
    brouillon est possible pour un compte public : la publication finale se
    fait d'un geste dans l'application TikTok.
    """
    t = item["type"]
    text = item.get("texte_tiktok", item.get("texte", ""))
    if t == "story":
        return "non concerné (pas de story sur TikTok)"
    videos = [u for u in urls if is_video(u)]
    if t == "reel" or videos:
        pid = _call("/post/publish/inbox/video/init/",
                    {"source_info": {"source": "PULL_FROM_URL", "video_url": videos[0]}})["publish_id"]
    else:
        title = text.split("\n", 1)[0][:90]
        pid = _call("/post/publish/content/init/", {
            "post_info": {"title": title, "description": text[:4000]},
            "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0, "photo_images": urls[:35]},
            "post_mode": "MEDIA_UPLOAD", "media_type": "PHOTO"})["publish_id"]
    status = _wait(pid)
    return "dans ta boîte de réception TikTok, à publier" if status == "SEND_TO_USER_INBOX" else "publié"


# ---------- Tâches lancées depuis GitHub ----------

def task_link():
    if not KEY:
        raise SystemExit("Secret TIKTOK_CLIENT_KEY absent")
    url = AUTH_URL + "?" + urlencode({"client_key": KEY, "scope": SCOPES, "response_type": "code",
                                      "redirect_uri": REDIRECT, "state": "lacannette"})
    open_issue("TikTok : lien de connexion",
               "**Action :** ouvre ce lien sur l'ordinateur, connecte-toi avec @lacanettte "
               "(QR code), puis clique sur **Autoriser**.\n\n"
               f"[Connecter mon compte TikTok]({url})\n\n"
               "La page suivante affiche un code : suis ensuite les instructions de Claude.")
    print("Lien de connexion créé dans une alerte GitHub.")


def task_connect():
    code = os.environ.get("TIKTOK_AUTH_CODE", "").strip()
    if not code:
        raise SystemExit("Secret TIKTOK_AUTH_CODE absent")
    try:
        tok = connect(code)
        user = user_info()
    except TikTokError as e:
        open_issue("TikTok : connexion échouée",
                   f"**Cause :** {scrub(e)}\n\n**Impact :** rien n'est envoyé sur TikTok.\n\n"
                   "**Action :** le code n'est valable que quelques minutes et une seule fois. "
                   "Transmets le titre de cette alerte à Claude.")
        raise SystemExit(1)
    end = dt.datetime.fromtimestamp(tok["refresh_expires"], dt.timezone.utc).strftime("%d/%m/%Y")
    open_issue("TikTok : compte connecté",
               f"**Compte :** {user.get('display_name', 'inconnu')}\n\n"
               f"**Autorisations :** {tok.get('scope')}\n\n"
               f"**Valable jusqu'au :** {end} (alerte 14 jours avant).\n\n"
               "**Action :** supprime maintenant le secret GitHub TIKTOK_AUTH_CODE, il ne sert plus.")
    print("Compte TikTok connecté.")


if __name__ == "__main__":
    import sys
    {"lien": task_link, "connexion": task_connect}[sys.argv[1]]()
