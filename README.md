# lacannette-social

Robot de publication LaCannette — Instagram et Facebook.

## Comment ça marche

- `plan.json` : le calendrier. Le robot publie chaque élément au statut **programmé** à l'heure prévue (heure de Paris).
- `contenu/` : les images et vidéos, rangées par mois puis par publication.
- `rapports/etat.md` : l'état du robot (connexion, quota, échéance Meta, calendrier).
- `rapports/hebdo/` : les rapports hebdomadaires.

## Statuts

- **programmé** : en attente de son heure.
- **publié** : en ligne, avec le lien.
- **nouvel essai** : erreur passagère, le robot réessaie au passage suivant (3 essais).
- **échec** : non publié. Une alerte GitHub t'est envoyée par e-mail.

## À savoir

- Le robot passe toutes les 15 minutes. GitHub peut retarder ce passage : compter 15 à 30 minutes d'écart.
- Ce dépôt est public : images et textes à venir sont visibles. Le jeton Meta reste secret.
- Les stories à la une ne sont pas gérées par l'API : elles s'épinglent à la main.
