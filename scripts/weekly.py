"""Rapport hebdomadaire : publié, échecs, à venir, compte Instagram."""
import datetime as dt

from common import IG, TOKEN, FMT, MetaError, get, now, parse_date, load_plan, write_report, open_issue


def main():
    today = now()
    week_ago, week_next = today - dt.timedelta(days=7), today + dt.timedelta(days=7)
    done, failed, upcoming = [], [], []
    for it in load_plan().get("publications", []):
        try:
            when = parse_date(it["date"])
        except (KeyError, ValueError):
            continue
        label = f"{when.strftime('%d/%m %H:%M')} — {it.get('id')} ({it.get('type')})"
        if it.get("statut") == "publié" and week_ago <= when <= today:
            done.append(label)
        elif it.get("statut") == "échec" and week_ago <= when <= today:
            failed.append(label)
        elif it.get("statut") == "programmé" and today < when <= week_next:
            upcoming.append(label)

    account = "non lisible"
    if TOKEN:
        try:
            ig = get(IG, fields="followers_count,media_count")
            account = f"{ig.get('followers_count')} abonnés, {ig.get('media_count')} publications"
        except MetaError:
            pass

    def block(title, rows):
        return [f"## {title} ({len(rows)})"] + ([f"- {r}" for r in rows] or ["- Aucune"]) + [""]

    text = [f"# Rapport hebdomadaire — {today.strftime('%d/%m/%Y')}", "",
            f"**Instagram :** {account}", ""]
    text += block("Publié cette semaine", done)
    text += block("Échecs", failed)
    text += block("Prévu les 7 prochains jours", upcoming)
    body = "\n".join(text)
    write_report(f"hebdo/{today.strftime('%Y-%m-%d')}.md", body + "\n")
    open_issue(f"Rapport hebdomadaire du {today.strftime('%d/%m/%Y')}", body)


if __name__ == "__main__":
    main()
