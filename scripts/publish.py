"""Publie à l'heure prévue les éléments « programmé » de plan.json."""
import sys
import time

import requests

from common import (CONFIG, IG, PAGE, TOKEN, FMT, MetaError, get, post, rupload,
                    now, parse_date, media_url, is_video, load_plan, save_plan,
                    open_issue, scrub)

TYPES = ("image", "carrousel", "story", "reel")


def check_url(url):
    try:
        r = requests.head(url, allow_redirects=True, timeout=30)
    except requests.RequestException:
        raise MetaError(f"Fichier injoignable : {url}")
    if r.status_code != 200:
        raise MetaError(f"Fichier inaccessible (HTTP {r.status_code}) : {url}")


# ---------- Instagram ----------

def ig_wait(cid, max_wait=900):
    start = time.time()
    while True:
        status = get(cid, fields="status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise MetaError(f"Instagram a refusé le fichier (statut {status})")
        if time.time() - start > max_wait:
            raise MetaError("Traitement Instagram trop long (plus de 15 min)")
        time.sleep(10)


def ig_container(url, text=None, kind=None, child=False):
    data = {}
    if is_video(url):
        data["video_url"] = url
        data["media_type"] = kind or ("VIDEO" if child else "REELS")
    else:
        data["image_url"] = url
        if kind:
            data["media_type"] = kind
    if child:
        data["is_carousel_item"] = "true"
    if text:
        data["caption"] = text
    cid = post(f"{IG}/media", **data)["id"]
    ig_wait(cid)
    return cid


def ig_publish(cid):
    mid = post(f"{IG}/media_publish", creation_id=cid)["id"]
    try:
        return get(mid, fields="permalink").get("permalink", mid)
    except MetaError:
        return mid


def publish_instagram(item, urls):
    t, text = item["type"], item.get("texte", "")
    if t == "image":
        return ig_publish(ig_container(urls[0], text))
    if t == "carrousel":
        kids = [ig_container(u, child=True) for u in urls]
        cid = post(f"{IG}/media", media_type="CAROUSEL", children=",".join(kids), caption=text)["id"]
        ig_wait(cid)
        return ig_publish(cid)
    if t == "story":
        return " | ".join(ig_publish(ig_container(u, kind="STORIES")) for u in urls)
    if t == "reel":
        data = {"media_type": "REELS", "video_url": urls[0], "caption": text, "share_to_feed": "true"}
        if item.get("couverture"):
            data["cover_url"] = media_url(item["couverture"])
        cid = post(f"{IG}/media", **data)["id"]
        ig_wait(cid)
        return ig_publish(cid)
    raise MetaError(f"Type inconnu : {t}")


# ---------- Facebook ----------

def fb_video(endpoint, url, finish_extra):
    start = post(f"{PAGE}/{endpoint}", upload_phase="start")
    vid = start["video_id"]
    rupload(start["upload_url"], url)
    post(f"{PAGE}/{endpoint}", upload_phase="finish", video_id=vid, **finish_extra)
    return vid


def publish_facebook(item, urls):
    t, text = item["type"], item.get("texte_facebook", item.get("texte", ""))
    if t == "image":
        r = post(f"{PAGE}/photos", url=urls[0], message=text)
        return f"https://www.facebook.com/{r.get('post_id', r['id'])}"
    if t == "carrousel":
        if any(is_video(u) for u in urls):
            raise MetaError("Facebook n'accepte que des photos dans une publication multiple")
        data = {"message": text}
        for i, u in enumerate(urls):
            pid = post(f"{PAGE}/photos", url=u, published="false")["id"]
            data[f"attached_media[{i}]"] = '{"media_fbid":"%s"}' % pid
        r = post(f"{PAGE}/feed", **data)
        return f"https://www.facebook.com/{r['id']}"
    if t == "story":
        for u in urls:
            if is_video(u):
                fb_video("video_stories", u, {})
            else:
                pid = post(f"{PAGE}/photos", url=u, published="false")["id"]
                post(f"{PAGE}/photo_stories", photo_id=pid)
        return "story publiée"
    if t == "reel":
        vid = fb_video("video_reels", urls[0], {"video_state": "PUBLISHED", "description": text})
        return f"https://www.facebook.com/reel/{vid}"
    raise MetaError(f"Type inconnu : {t}")


PUBLISHERS = {"instagram": publish_instagram, "facebook": publish_facebook}


def main():
    if not TOKEN:
        open_issue("Robot : jeton Meta absent",
                   "**Cause :** le secret META_PAGE_TOKEN est vide ou absent.\n"
                   "**Impact :** aucune publication ne peut partir.\n"
                   "**Action :** préviens Claude.")
        sys.exit(1)

    plan = load_plan()
    current = now()
    max_tries = CONFIG["tentatives_max"]
    failed = []

    for item in plan.get("publications", []):
        if item.get("statut") != "programmé":
            continue
        try:
            when = parse_date(item["date"])
        except (KeyError, ValueError):
            item["statut"] = "échec"
            item["erreur"] = "Date illisible (format attendu : AAAA-MM-JJ HH:MM)"
            failed.append(item)
            continue
        if when > current:
            continue

        results = item.setdefault("resultats", {})
        late_h = (current - when).total_seconds() / 3600
        if late_h > CONFIG["retard_max_heures"]:
            for p in item.get("plateformes", []):
                if results.get(p, {}).get("statut") != "publié":
                    results[p] = {"statut": "échec",
                                  "erreur": f"Heure dépassée de {late_h:.0f} h : non publiée pour éviter un contenu périmé"}
            item["statut"] = "échec"
            failed.append(item)
            continue

        url_error = None
        try:
            if item.get("type") not in TYPES:
                raise MetaError(f"Type inconnu : {item.get('type')}")
            urls = [media_url(m) for m in item["medias"]]
            for u in urls:
                check_url(u)
        except (MetaError, KeyError) as e:
            url_error = scrub(e)

        for p in item.get("plateformes", []):
            prev = results.get(p, {})
            if prev.get("statut") == "publié":
                continue
            try:
                if url_error:
                    raise MetaError(url_error)
                link = PUBLISHERS[p](item, urls)
                results[p] = {"statut": "publié", "lien": link, "le": now().strftime(FMT)}
                print(f"Publié : {item['id']} sur {p}")
            except Exception as e:  # noqa: BLE001
                tries = prev.get("tentatives", 0) + 1
                results[p] = {"statut": "échec" if tries >= max_tries else "nouvel essai",
                              "erreur": scrub(e), "tentatives": tries}
                print(f"Erreur : {item['id']} sur {p} : {scrub(e)}")

        states = [results[p]["statut"] for p in item.get("plateformes", [])]
        if states and all(s == "publié" for s in states):
            item["statut"] = "publié"
        elif "échec" in states:
            item["statut"] = "échec"
            failed.append(item)

    save_plan(plan)

    for item in failed:
        lines = [f"**Publication :** {item.get('id')}", f"**Prévue le :** {item.get('date')}"]
        for p, r in item.get("resultats", {}).items():
            if r.get("statut") != "publié":
                lines.append(f"**{p.capitalize()} — cause :** {r.get('erreur')}")
                lines.append(f"**Impact :** cette publication n'est pas en ligne sur {p.capitalize()}. "
                             "Les autres publications continuent normalement.")
        if item.get("erreur"):
            lines.append(f"**Cause :** {item['erreur']}")
        lines.append("**Action :** transmets le titre de cette alerte à Claude.")
        open_issue(f"Échec de publication : {item.get('id')}", "\n\n".join(lines))


if __name__ == "__main__":
    main()
