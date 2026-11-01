"""Test de connexion, contrôle du calendrier, inventaire Instagram, échéance Meta."""
import datetime as dt
import os
import sys

from common import (CONFIG, IG, PAGE, ROOT, TOKEN, FMT, MetaError, get, now,
                    parse_date, is_video, load_plan, write_report, open_issue)

TYPES = ("image", "carrousel", "story", "reel")


def check_plan():
    errors = []
    try:
        plan = load_plan()
    except Exception as e:  # noqa: BLE001
        return [f"plan.json illisible : {e}"], 0
    items = plan.get("publications", [])
    ids = set()
    todo = 0
    for it in items:
        name = it.get("id", "sans identifiant")
        if name in ids:
            errors.append(f"{name} : identifiant en double")
        ids.add(name)
        if it.get("statut") != "programmé":
            continue
        todo += 1
        try:
            parse_date(it.get("date", ""))
        except ValueError:
            errors.append(f"{name} : date illisible (AAAA-MM-JJ HH:MM)")
        t = it.get("type")
        if t not in TYPES:
            errors.append(f"{name} : type inconnu « {t} »")
        medias = it.get("medias", [])
        if not medias:
            errors.append(f"{name} : aucun média")
        for m in medias:
            if not os.path.exists(os.path.join(ROOT, m)):
                errors.append(f"{name} : fichier absent du dépôt ({m})")
            if not is_video(m) and not m.lower().endswith((".jpg", ".jpeg")):
                errors.append(f"{name} : {m} doit être en JPEG")
        if t == "carrousel" and not 2 <= len(medias) <= 10:
            errors.append(f"{name} : un carrousel contient 2 à 10 médias")
        if t == "reel" and not (medias and is_video(medias[0])):
            errors.append(f"{name} : un Reel doit être une vidéo MP4 ou MOV")
        if len(it.get("texte", "")) > 2200:
            errors.append(f"{name} : texte trop long pour Instagram (2 200 caractères max)")
        for p in it.get("plateformes", []):
            if p not in ("instagram", "facebook"):
                errors.append(f"{name} : plateforme inconnue « {p} »")
    return errors, todo


def main():
    lines = [f"# État du robot — {now().strftime('%d/%m/%Y %H:%M')}", ""]
    problems = []

    if not TOKEN:
        problems.append("Le secret META_PAGE_TOKEN est absent.")
    else:
        try:
            me = get("me", fields="id,name")
            ok = me.get("id") == PAGE
            lines.append(f"- Connexion Facebook : {'Vérifié' if ok else 'À vérifier'} ({me.get('name', '').strip()})")
            if not ok:
                problems.append("Le jeton ne correspond pas à la page LaCannette.")
        except MetaError as e:
            lines.append("- Connexion Facebook : ÉCHEC")
            problems.append(f"Connexion Facebook refusée : {e}")

        try:
            ig = get(IG, fields="username,followers_count,media_count")
            lines.append(f"- Instagram : Vérifié (@{ig.get('username')} — "
                         f"{ig.get('followers_count')} abonnés, {ig.get('media_count')} publications)")
        except MetaError as e:
            lines.append("- Instagram : ÉCHEC")
            problems.append(f"Connexion Instagram refusée : {e}")
            ig = None

        try:
            q = get(f"{IG}/content_publishing_limit", fields="quota_usage,config")["data"][0]
            total = q.get("config", {}).get("quota_total", "?")
            lines.append(f"- Quota Instagram (24 h) : {q.get('quota_usage', 0)} / {total}")
        except (MetaError, KeyError, IndexError):
            lines.append("- Quota Instagram (24 h) : non lisible")

        expiry, source = None, "estimation"
        try:
            d = get("debug_token", input_token=TOKEN)["data"]
            if d.get("data_access_expires_at"):
                expiry = dt.datetime.fromtimestamp(d["data_access_expires_at"], dt.timezone.utc).date()
                source = "Meta"
            if d.get("is_valid") is False:
                problems.append("Meta indique que le jeton n'est plus valide.")
        except (MetaError, KeyError):
            pass
        if expiry is None:
            expiry = dt.date.fromisoformat(CONFIG["acces_donnees_estime"])
        days = (expiry - now().date()).days
        lines.append(f"- Accès aux données Meta : jusqu'au {expiry.strftime('%d/%m/%Y')} "
                     f"(dans {days} jours, source : {source})")
        if days <= CONFIG["alerte_jours_avant_expiration"]:
            open_issue(f"Renouveler l'accès Meta avant le {expiry.strftime('%d/%m/%Y')}",
                       f"**Échéance :** {expiry.strftime('%d/%m/%Y')} (dans {days} jours).\n\n"
                       "**Impact si rien n'est fait :** les publications automatiques peuvent s'arrêter.\n\n"
                       "**Action :** demande à Claude la procédure de renouvellement (2 minutes).")

        if ig:
            try:
                media = get(f"{IG}/media", fields="timestamp,media_type,permalink,caption", limit=25).get("data", [])
                inv = ["# Inventaire Instagram (25 dernières publications)", "",
                       "| Date | Type | Lien | Début du texte |", "|---|---|---|---|"]
                for m in media:
                    cap = (m.get("caption") or "").replace("\n", " ").replace("|", "/")[:60]
                    inv.append(f"| {m.get('timestamp', '')[:10]} | {m.get('media_type')} | "
                               f"[ouvrir]({m.get('permalink')}) | {cap} |")
                write_report("inventaire-instagram.md", "\n".join(inv) + "\n")
            except MetaError as e:
                lines.append(f"- Inventaire Instagram : non lisible ({e})")

    errors, todo = check_plan()
    lines.append(f"- Calendrier : {todo} publication(s) programmée(s), "
                 f"{'Vérifié' if not errors else str(len(errors)) + ' point(s) À vérifier'}")
    lines += [f"  - {e}" for e in errors]
    if errors:
        problems.append("Calendrier : " + " ; ".join(errors))

    write_report("etat.md", "\n".join(lines) + "\n")
    print("\n".join(lines))

    if problems:
        open_issue("Test de connexion : problème détecté",
                   "\n\n".join(f"**Cause :** {p}" for p in problems) +
                   "\n\n**Impact :** les publications concernées risquent de ne pas partir.\n\n"
                   "**Action :** transmets le titre de cette alerte à Claude.")
        sys.exit(1)


if __name__ == "__main__":
    main()
