"""Fonctions communes du robot LaCannette."""
import datetime as dt
import json
import os
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
    CONFIG = json.load(f)

TOKEN = os.environ.get("META_PAGE_TOKEN", "").strip()
GRAPH = f"https://graph.facebook.com/{CONFIG['graph_version']}"
TZ = ZoneInfo(CONFIG["fuseau"])
PAGE = CONFIG["facebook_page_id"]
IG = CONFIG["instagram_id"]
FMT = "%Y-%m-%d %H:%M"


class MetaError(Exception):
    pass


def scrub(text):
    """Retire le jeton de tout message avant affichage ou alerte."""
    text = str(text)
    return text.replace(TOKEN, "***") if TOKEN else text


def _check(r):
    try:
        data = r.json()
    except ValueError:
        data = {"error": {"message": r.text[:300]}}
    if r.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        err = data.get("error", {}) if isinstance(data, dict) else {}
        msg = err.get("message", "erreur inconnue") if isinstance(err, dict) else str(err)
        code = err.get("code") if isinstance(err, dict) else None
        raise MetaError(scrub(f"{msg} (code {code}, HTTP {r.status_code})"))
    return data


def get(path, **params):
    params["access_token"] = TOKEN
    try:
        return _check(requests.get(f"{GRAPH}/{path}", params=params, timeout=60))
    except requests.RequestException as e:
        raise MetaError(scrub(f"Meta injoignable : {e}"))


def post(path, **data):
    data["access_token"] = TOKEN
    try:
        return _check(requests.post(f"{GRAPH}/{path}", data=data, timeout=180))
    except requests.RequestException as e:
        raise MetaError(scrub(f"Meta injoignable : {e}"))


def rupload(upload_url, file_url):
    """Envoie une vidéo hébergée vers les serveurs vidéo de Facebook."""
    try:
        r = requests.post(upload_url, headers={"Authorization": f"OAuth {TOKEN}",
                                               "file_url": file_url}, timeout=300)
    except requests.RequestException as e:
        raise MetaError(scrub(f"Envoi vidéo impossible : {e}"))
    return _check(r)


def now():
    return dt.datetime.now(TZ)


def parse_date(text):
    return dt.datetime.strptime(text, FMT).replace(tzinfo=TZ)


def media_url(path):
    return CONFIG["media_base_url"].rstrip("/") + "/" + quote(path.lstrip("/"))


def is_video(path):
    return path.lower().endswith((".mp4", ".mov"))


def load_plan():
    with open(os.path.join(ROOT, "plan.json"), encoding="utf-8") as f:
        return json.load(f)


def save_plan(plan):
    with open(os.path.join(ROOT, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_report(name, text):
    path = os.path.join(ROOT, "rapports", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(scrub(text))


def open_issue(title, body):
    """Crée une alerte GitHub assignée au propriétaire (e-mail automatique)."""
    gh = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    body = scrub(body)
    print(f"ALERTE : {title}\n{body}")
    if not gh or not repo:
        return
    owner = repo.split("/")[0]
    h = {"Authorization": f"Bearer {gh}", "Accept": "application/vnd.github+json"}
    base = f"https://api.github.com/repos/{repo}/issues"
    try:
        r = requests.get(base, headers=h, params={"state": "open", "per_page": 100}, timeout=30)
        if r.ok and any(i.get("title") == title for i in r.json()):
            return
        requests.post(base, headers=h, timeout=30,
                      json={"title": title, "body": body, "assignees": [owner]})
    except requests.RequestException as e:
        print(f"Impossible de créer l'alerte : {e}")
