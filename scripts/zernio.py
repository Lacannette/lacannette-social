"""Publication TikTok et YouTube Shorts via Zernio (service de publication validé par TikTok).

La clé Zernio est un secret GitHub (ZERNIO_API_KEY) : elle n'apparaît jamais dans le dépôt.
"""
import os
import time

import requests

from common import MetaError, media_url, is_video, open_issue

API = "https://zernio.com/api/v1"
KEY = os.environ.get("ZERNIO_API_KEY", "").strip()


class ZernioError(MetaError):
    pass


def enabled():
    return bool(KEY)


def scrub(text):
    text = str(text)
    return text.replace(KEY, "***") if KEY else text


def _req(method, path, body=None, timeout=120):
    try:
        r = requests.request(method, f"{API}{path}", json=body, timeout=timeout,
                             headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise ZernioError(scrub(f"Zernio injoignable : {e}"))
    try:
        data = r.json()
    except ValueError:
        data = {"error": r.text[:300]}
    if r.status_code >= 400:
        msg = data.get("error") or data.get("message") or data
        raise ZernioError(scrub(f"Zernio refuse : {msg} (HTTP {r.status_code})"))
    return r.status_code, data


_ACCOUNTS = None


def accounts():
    global _ACCOUNTS
    if _ACCOUNTS is None:
        _, data = _req("GET", "/accounts")
        _ACCOUNTS = data.get("accounts", data if isinstance(data, list) else [])
    return _ACCOUNTS


def account_id(platform):
    for a in accounts():
        if a.get("platform") == platform and a.get("isActive", True):
            return a.get("_id") or a.get("id")
    raise ZernioError(f"Aucun compte {platform} connecté dans Zernio")


def _first_line(text, n):
    line = (text or "").strip().split("\n", 1)[0]
    return line[:n].rstrip()


def _result(code, data, platform):
    """Contrôle la réponse : 201 = parti, 207 = échec partiel ou total."""
    post = data.get("post", {}) if isinstance(data, dict) else {}
    pr = data.get("platformResults") or post.get("platforms") or []
    for p in pr:
        if p.get("platform") == platform and p.get("status") == "failed":
            raise ZernioError(scrub(f"{platform} a refusé : {p.get('error') or p.get('errorMessage')}"))
    if code == 207 and data.get("error"):
        raise ZernioError(scrub(f"{platform} a refusé : {data.get('error')}"))
    pid = post.get("_id")
    for p in pr:
        if p.get("platform") == platform:
            url = p.get("platformPostUrl") or p.get("url")
            if url:
                return url
    return _wait(pid, platform) if pid else "publié via Zernio"


def _wait(pid, platform, max_wait=600):
    start = time.time()
    while time.time() - start < max_wait:
        _, data = _req("GET", f"/posts/{pid}")
        post = data.get("post", data)
        for p in post.get("platforms", []):
            if p.get("platform") != platform:
                continue
            st = p.get("status")
            if st == "published":
                return p.get("platformPostUrl") or "publié via Zernio"
            if st == "failed":
                raise ZernioError(scrub(f"{platform} a refusé : {p.get('errorMessage') or p.get('error')}"))
        if post.get("status") in ("published",):
            return "publié via Zernio"
        time.sleep(15)
    raise ZernioError(f"{platform} : publication toujours en cours après 10 min (vérifier dans Zernio)")


def publish_tiktok(item, urls, privacy="PUBLIC_TO_EVERYONE"):
    t = item["type"]
    if t == "story":
        return "non concerné (pas de story sur TikTok)"
    text = item.get("texte_tiktok", item.get("texte", ""))
    video = t == "reel" or any(is_video(u) for u in urls)
    settings = {"privacy_level": privacy, "allow_comment": True, "allow_duet": True, "allow_stitch": True,
                "content_preview_confirmed": True, "express_consent_given": True}
    if privacy == "PUBLIC_TO_EVERYONE":
        settings["brand_organic_toggle"] = True  # contenu de sa propre marque
    if video:
        media = [{"type": "video", "url": next(u for u in urls if is_video(u))}]
    else:
        media = [{"type": "image", "url": u} for u in urls[:35]]
        settings.update({"media_type": "PHOTO", "photo_cover_index": 0, "title": _first_line(text, 90),
                         "description": text[:4000]})
    psd = {"tiktokSettings": settings}
    if video and item.get("couverture"):
        # Zernio ajoute l'image en première image fixe et la définit comme couverture TikTok
        psd["videoCoverImageUrl"] = media_url(item["couverture"])
    body = {"content": text[:2200], "mediaItems": media, "tiktokSettings": settings,
            "platforms": [{"platform": "tiktok", "accountId": account_id("tiktok"),
                           "platformSpecificData": psd}],
            "publishNow": True}
    code, data = _req("POST", "/posts", body, timeout=600)
    return _result(code, data, "tiktok")


def publish_youtube(item, urls, visibility="public"):
    if item["type"] != "reel":
        return "non concerné (YouTube Shorts : vidéos uniquement)"
    text = item.get("texte_youtube", item.get("texte", ""))
    title = _first_line(text, 90)
    if "#shorts" not in title.lower():
        title = (title + " #Shorts")[:100]
    media = {"type": "video", "url": next(u for u in urls if is_video(u))}
    if item.get("couverture"):
        media["thumbnail"] = media_url(item["couverture"])
    body = {"content": text[:4900], "mediaItems": [media],
            "platforms": [{"platform": "youtube", "accountId": account_id("youtube"),
                           "platformSpecificData": {"title": title, "visibility": visibility,
                                                    "madeForKids": False, "categoryId": "22"}}],
            "publishNow": True}
    code, data = _req("POST", "/posts", body, timeout=600)
    return _result(code, data, "youtube")


# ---------- Tâche « zernio-test » ----------

def task_test():
    """Vérifie la clé et les comptes, puis publie un essai PRIVÉ sur TikTok et YouTube."""
    if not KEY:
        raise SystemExit("Secret ZERNIO_API_KEY absent")
    lines = []
    try:
        accs = accounts()
        names = [f"{a.get('platform')} ({a.get('username') or a.get('displayName')})" for a in accs]
        lines.append("**Comptes connectés :** " + (", ".join(names) or "aucun"))
    except ZernioError as e:
        open_issue("Zernio : test échoué", f"**Cause :** {scrub(e)}\n\n**Action :** transmets le titre à Claude.")
        raise SystemExit(1)
    photo = {"id": "test", "type": "image",
             "texte": "Test du robot LaCannette (privé) – à supprimer\nTest automatique."}
    video = {"id": "test", "type": "reel", "couverture": "contenu/2026-11/2026-11-24-sondage-format/01.jpg",
             "texte": "Test du robot LaCannette (privé) – à supprimer\nTest automatique."}
    ok = True
    for label, fn in (("TikTok (photo privée)", lambda: publish_tiktok(
                          photo, [media_url("contenu/2026-11/2026-11-24-sondage-format/01.jpg")], "SELF_ONLY")),
                      ("YouTube (Short privé)", lambda: publish_youtube(
                          video, [media_url("contenu/2026-12/2026-12-09-reel-gobelet/01.mp4")], "private"))):
        try:
            lines.append(f"**{label} :** Vérifié — {fn()}")
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f"**{label} :** ÉCHEC — {scrub(e)}")
    open_issue("Zernio : test réussi" if ok else "Zernio : test à vérifier",
               "\n\n".join(lines) + "\n\n**Action :** " +
               ("rien à faire. Les deux essais sont privés : tu peux les supprimer de TikTok et YouTube quand tu veux."
                if ok else "transmets le titre de cette alerte à Claude."))
    print("\n".join(lines))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    import sys
    {"test": task_test}[sys.argv[1]]()
