# plex-smart-logo-updater

**Des logos Plex (ClearLogo) mieux choisis : en français d'abord, une langue de repli, et pas de logos québécois.**

L'interface du script (messages, logs, page de contrôle, assistant) est en anglais. Cette page en décrit le fonctionnement en français.

🇬🇧 [English version](README.md)

Script Python qui ajoute automatiquement un **logo de qualité, en français de préférence**, aux films et séries de Plex qui n'en ont pas. Il remplace aussi les **logos québécois** que Plex pose par erreur.

Le repli de langue fonctionne pour toutes les langues de bibliothèque (par exemple `PLEX_LANGUAGES=de-DE,en-US` pour une bibliothèque allemande : logo allemand d'abord, sinon anglais). La détection des logos québécois ne concerne que les bibliothèques en français.

Basé sur [relkai/plex-bulk-logo-updater](https://github.com/relkai/plex-bulk-logo-updater) (licence MIT).

![Page de contrôle : logos québécois (à gauche) remplacés par des logos français (à droite)](docs/review-quebec.png)

## Le problème

Plex ne pose un logo automatiquement **que s'il en existe un dans la langue de la bibliothèque**. Dans une bibliothèque en français, un titre sans logo français reste donc sans logo, même si de bons logos en anglais existent. C'est très fréquent pour les animes.

Autre piège : **Plex ne distingue pas le français de France du français du Québec.** Il peut poser un logo québécois dans une bibliothèque française. Le titre affiché est alors « The Banker » alors que le logo indique « Le financier » ; de même, « Edge of Tomorrow » peut s'afficher avec le logo « Un jour sans lendemain ».

Le script d'origine se contentait de prendre le premier logo de la liste. Ce logo peut être en chinois ou en japonais, ou de mauvaise qualité.

## Ce que fait `plex-smart-logo-updater.py`

Pour chaque titre des bibliothèques choisies :

1. **Il ne touche jamais à un logo choisi à la main** (verrouillé), sauf avec `--fix-locked-quebec` s'il est québécois. Il ne touche pas non plus aux logos posés par Plex, **sauf s'ils sont québécois**.
2. **Pour les titres sans logo, il demande à Plex le logo qu'il recommande**, en français d'abord, puis en anglais s'il n'y en a pas. C'est exactement le logo que Plex aurait choisi lui-même. Le script interroge pour cela le service de métadonnées de Plex (`metadata.provider.plex.tv`) avec ton token Plex, sans clé TMDB.
3. **Il retrouve ce logo parmi ceux proposés par ton serveur** (même URL ou image identique au pixel près) et le sélectionne. Il ne l'ajoute depuis Internet que s'il ne le trouve pas.

Par défaut, le script fait une **simulation** : il affiche ce qu'il ferait sans rien modifier.

### Détection des logos québécois

Pour chaque titre, le script compare le titre français (fr-FR) et le titre québécois (fr-CA) donnés par Plex. S'ils diffèrent, il **lit le texte du logo** par reconnaissance de caractères (OCR, module `quebec.py`) et le compare aux titres français, québécois et original :

- **Un logo québécois posé par Plex est remplacé** par le meilleur logo non québécois : celui dont le texte est le plus proche du **titre français complet**, sinon du titre original. À ressemblance égale, le script préfère, dans l'ordre :
  1. un logo **sans texte en trop** (noms d'acteurs, slogans ; « Marvel Studios », « Disney »… sont tolérés) ;
  2. un logo du **même style** que le logo remplacé (en couleur ou blanc) ;
  3. celui que Plex recommande ;
  4. le plus grand.
- Quand le titre français diffère du titre original et que le logo recommandé par Plex n'est pas clairement français (logo anglais, illisible…), le script cherche un logo au titre français parmi les autres (ex. « HAPPY BIRTHDEAD » plutôt que « HAPPY DEATH DAY »). Si le titre est le même en France et en version originale, le choix de Plex est gardé.
- **Un logo québécois n'est jamais ajouté.** Si Plex recommande un logo québécois, le script cherche un autre logo parmi ceux proposés.
- S'il n'existe **que** des logos québécois, le titre est marqué `[CHECK]` : à faire à la main.
- Un logo **verrouillé** qui semble québécois est signalé dans les logs. Il n'est remplacé qu'avec `--fix-locked-quebec`.
- Quand le Québec garde le titre original (« Black Box Diaries »), un logo à ce titre n'est **pas** considéré comme québécois.

La détection est volontairement prudente : un logo déjà en place n'est remplacé que s'il est clairement lu comme québécois.

Trois **mentions spéciales** signalent les logos posés avec moins de certitude :

| Mention | Signification |
|---|---|
| `[FRENCH INFERRED]` (français déduit) | Le titre français est lu sur le logo et les mots propres au titre québécois en sont absents (ex. « PUSH », alors que le Québec dit « Push : La division »). Très probablement correct. |
| `[ORIGINAL TITLE]` (titre original) | Le logo porte le titre original, ni français ni québécois (ex. « HAPPY DEATH DAY » pour *Happy Birthdead*). |
| `[NOT VERIFIED]` (non vérifié) | L'OCR n'a pas pu lire le logo (police trop stylisée, lettres espacées…). Le logo est posé quand même, comme Plex l'aurait fait : **à contrôler**. |

Les lectures OCR sont gardées dans un cache (`.cache-ocr.json`) : une relance ne relit que les nouveaux logos.

## Installation

Python 3.8 ou plus récent est nécessaire.

```bash
git clone https://github.com/sSlydee/plex-smart-logo-updater.git
cd plex-smart-logo-updater
./install.sh
```

`install.sh` crée un environnement Python dédié (`.venv`), installe les dépendances (`requirements.txt`), puis lance l'**assistant de configuration**.

L'installateur remplace OpenCV 5, installé avec l'OCR, par une version plus ancienne : sur certaines machines, OpenCV 5 plante au chargement.

## Configuration

L'assistant pose quelques questions (en anglais) et écrit `config.env` à côté du script :

1. l'adresse du serveur Plex et ton token, avec un **test de connexion** ;
2. les bibliothèques à traiter, choisies dans la **liste de ton serveur** ;
3. la langue des logos (français, sinon anglais, par défaut) ;
4. les notifications (Discord, Bark, webhook générique), avec **un message de test** ;
5. l'**analyse automatique** dans cron : tous les jours, une fois par semaine ou jamais.

Pour modifier la configuration plus tard, relance l'assistant. Les valeurs actuelles sont proposées : Entrée pour les garder.

```bash
.venv/bin/python configure.py
```

Pour ne refaire qu'une étape :

| Commande | Effet |
|---|---|
| `configure.py --token` | Change **seulement le token** : il est demandé, testé, puis enregistré |
| `configure.py --token <nouveau token>` | Même chose sans question (mais le token reste dans l'historique du terminal) |
| `configure.py --server` | Adresse du serveur et token |
| `configure.py --libraries` | Choix des bibliothèques |
| `configure.py --language` | Langue des logos |
| `configure.py --notifications` | Webhooks |
| `configure.py --cron` | Analyse automatique |

Un nouveau token n'est enregistré que si la connexion à Plex réussit avec lui.

**Si ton token change**, le script le détecte : il s'arrête avec le message « Plex token rejected: change it with: .venv/bin/python configure.py --token ». Avec `--notify`, comme lors d'une analyse automatique, ce message t'est aussi envoyé par notification.

`config.env` contient ton token : l'assistant le rend lisible par toi seul. Tu peux aussi l'écrire à la main à partir de `config.env.example`.

| Variable | Rôle | Exemple |
|---|---|---|
| `PLEX_URL` | Adresse **locale** du serveur Plex | `http://192.168.1.100:32400` |
| `PLEX_TOKEN` | Ton token Plex ([comment le trouver](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)) | `xxxxxxxxxxxxxxxxxxxx` |
| `PLEX_LIBRARIES` | Bibliothèques à traiter, séparées par des virgules | `Films,Séries TV,Animations Japonaise` |
| `PLEX_LANGUAGES` | Langues par ordre de préférence (facultatif) | `fr-FR,en-US` (par défaut) |
| `NOTIFY_URLS` | Webhooks pour `--notify`, séparés par des virgules (facultatif) | voir [Notifications](#notifications) |
| `PLEX_LOGS_DIR` | Dossier des logs (facultatif) | `logs/` à côté du script (par défaut) |
| `PLEX_OCR_CACHE` | Cache des lectures OCR (facultatif) | `.cache-ocr.json` à côté du script (par défaut) |
| `PLEX_LOGS_KEEP` | Nombre de dossiers de simulation gardés ; les plus anciens sont supprimés, ceux des applications (avec `undo.json`) sont toujours gardés (facultatif) | `100` (par défaut) |

Une variable d'environnement définie au lancement a priorité sur `config.env`, par exemple pour traiter une seule bibliothèque :

```bash
PLEX_LIBRARIES="Films" .venv/bin/python plex-smart-logo-updater.py
```

Utilise l'adresse IP locale plutôt qu'un nom de domaine public. Un reverse proxy protégé par Fail2Ban ou CrowdSec pourrait bloquer le script à cause du nombre de requêtes.

### Notifications

Avec `--notify`, le script envoie un résumé **seulement s'il y a quelque chose à faire** : des changements à valider, des titres à faire à la main ou des erreurs. `NOTIFY_URLS` peut contenir plusieurs webhooks. Le type est deviné d'après l'adresse, ou forcé par un préfixe :

| Service | Exemple dans `NOTIFY_URLS` |
|---|---|
| Discord | `https://discord.com/api/webhooks/…` |
| Bark (serveur officiel) | `https://api.day.app/<ta clé>` |
| Bark (auto-hébergé) | `bark:https://mon-serveur-bark.fr/<ta clé>` |
| Webhook générique (POST JSON `title`, `message`, `text`) | `json:https://exemple.org/hook` |

Les adresses des webhooks ne sont jamais recopiées dans les logs.

### Analyse automatique

Si tu l'as activée dans l'assistant, cron lance régulièrement une **simulation** avec la page de contrôle et les notifications (`--html --notify --quiet`). **Rien n'est jamais appliqué automatiquement** : quand des titres sont à valider, tu reçois une notification, tu contrôles la page, puis tu lances l'application avec `--choices`. La sortie de chaque lancement automatique est ajoutée à `logs/cron.log` (limité à 5 Mo).

L'assistant gère une seule ligne de ta crontab, marquée `# plex-smart-logo-updater`, et ne touche pas aux autres.

## Utilisation

| Option | Effet |
|---|---|
| *(aucune)* | Simulation : rien n'est modifié |
| `--apply` | Applique les changements |
| `--html` | Génère la page de contrôle `review.html` (voir plus bas) |
| `--choices FICHIER` | Avec `--apply` : n'applique que les changements validés dans la page de contrôle |
| `--fix-locked-quebec` | Remplace aussi les logos **verrouillés** détectés comme québécois |
| `--notify` | Envoie un résumé aux webhooks de `NOTIFY_URLS` s'il y a quelque chose à faire |
| `--quiet` | N'affiche que le résumé (le détail reste dans les logs) |
| `--undo DOSSIER` | Annule une application (simulation, sauf avec `--apply`) |
| `--replace` | Remplace aussi les logos posés par Plex s'ils diffèrent de sa recommandation actuelle |
| `--replace --include-locked` | Remplace aussi les logos choisis à la main (à éviter) |

`.venv/bin/python plex-smart-logo-updater.py --help` rappelle toutes les options.

Attention avec `--replace` : sur TMDB, un logo « français » peut être la version québécoise, et l'OCR n'arrive pas toujours à le repérer. Par défaut, le script ne remplace donc que les logos détectés comme québécois.

En mode `--apply`, le script fait une pause de 2 s après chaque logo et de 10 s tous les 10 logos, pour ménager le serveur. En cas d'erreur passagère (429 ou 5xx), il réessaie automatiquement jusqu'à 4 fois.

### Méthode recommandée : simulation, contrôle, application

**1. Simulation avec page de contrôle :**

```bash
.venv/bin/python plex-smart-logo-updater.py --html
```

Le script crée `review.html` dans le dossier de logs de la simulation.

![Page de contrôle avec tous les changements](docs/review-all.png)

**2. Contrôle sur ton PC :** télécharge `review.html` (SFTP, gestionnaire de fichiers web…) et ouvre-le dans ton navigateur. C'est un fichier autonome : les images sont incluses, il ne contient ni lien vers ton serveur ni token.

- Chaque changement s'affiche avec l'ancien et le nouveau logo.
- Tout est **validé** par défaut : clique sur **Reject** pour ceux que tu ne veux pas.
- Les filtres permettent de commencer par les cas douteux (« Not verified », « Original title »…).
- Tes choix sont gardés dans le navigateur si tu fermes la page.
- Clique sur **Export choices.json**.

**3. Application :** copie `choices.json` sur la seedbox, dans le dossier de la simulation, puis :

```bash
.venv/bin/python plex-smart-logo-updater.py --apply --choices logs/<dossier de la simulation>/choices.json
```

Seuls les changements validés sont appliqués. Un titre refusé est marqué `[REJECTED]`. Si le logo prévu a changé depuis la simulation, le titre est marqué `[RECHECK]` et n'est pas modifié.

### Annuler une application

Chaque application enregistre l'état d'avant dans `undo.json`, dans son dossier de logs. Pour tout remettre comme avant :

```bash
.venv/bin/python plex-smart-logo-updater.py --undo logs/<dossier de l'application>            # simulation
.venv/bin/python plex-smart-logo-updater.py --undo logs/<dossier de l'application> --apply    # restauration
```

- Un titre qui n'avait pas de logo le perd à nouveau.
- Un titre qui avait un logo retrouve l'ancien, avec son verrou d'origine.
- Un logo modifié depuis l'application (par toi ou par Plex) n'est pas touché.

## Logs

Chaque lancement crée un dossier dans `logs/`, nommé avec la date, l'heure et le mode :

```
logs/
└── 2026-09-23_18h20m05_simulation/
    ├── _summary.txt       ← tableau par bibliothèque + totaux
    ├── Films.txt          ← détail titre par titre + résumé
    ├── Séries TV.txt
    ├── review.html        ← avec --html
    └── undo.json          ← en mode --apply
```

Chaque fichier commence par un en-tête : date, mode, règle appliquée et légende. Il se termine par un résumé : durée, décompte et liste des titres concernés.

Dans le détail, chaque titre se termine par une étiquette :

| Étiquette | Signification |
|---|---|
| `[TO ADD]` / `[ADDED]` | Aucun logo actuellement, un logo va être / a été posé |
| `[TO REPLACE]` / `[REPLACED]` | Le logo actuel va être / a été remplacé (logo québécois, ou avec `--replace`) |
| `[OK]` | Déjà le bon logo, rien à faire (uniquement avec `--replace`) |
| `[KEPT]` | Un logo est déjà en place : ignoré |
| `[LOCKED]` | Logo choisi à la main : ignoré |
| `[NONE]` | Plex ne recommande aucun logo dans les langues demandées : ignoré |
| `[CHECK]` | Seul un logo québécois est disponible : à faire à la main |
| `[REJECTED]` | Avec `--choices` : refusé dans la page de contrôle |
| `[RECHECK]` | Avec `--choices` : le logo prévu a changé depuis la simulation |
| `[NOT REVIEWED]` | Avec `--choices` : titre absent du fichier de choix (nouveau depuis la simulation) |
| `[ERROR]` | Erreur (le message est indiqué) |

Mentions possibles après l'étiquette : `[FRENCH INFERRED]`, `[ORIGINAL TITLE]` et `[NOT VERIFIED]` (voir plus haut).

Exemple :

```
[1/3] BNA (2020)
  Current logo     : none
  Plex search      : French: none | English: found
  Recommended logo : English, 618x239 px
  Image link       : https://metadata-static.plex.tv/...png
  Found on Plex    : candidate #3 of 7 (tmdb), same URL
  ==> [TO ADD] English logo 618x239 px
```

Exemple de logo québécois remplacé :

```
[52/303] Bullet Train (2022)
  Current logo     : #8 of 18 (tmdb), set automatically by Plex
  Titles           : France "Bullet Train" | Quebec "Train à grande vitesse" | original "Bullet Train"
  Logo reads       : "TRAIN A C GRANDE VITESSE" -> Quebec
  Plex search      : French: found
  Recommended reads: "TRAIN A C GRANDE VITESSE" -> Quebec
  OCR choice       : candidate #4 of 18 (tmdb), "BULLET TRAIT" -> French
  ==> [TO REPLACE] logo "BULLET TRAIT" (French), instead of #8 (Quebec)
```

L'OCR ne lit pas toujours parfaitement (ici « TRAIT » au lieu de « TRAIN »), mais la comparaison tolère ces petites erreurs.

La première simulation est plus longue sur les bibliothèques de films (environ 7 minutes pour 300 films), à cause de la lecture des logos. Les suivantes profitent du cache.

## Bon à savoir

- Un logo sélectionné par le script devient **verrouillé**, comme un choix manuel. Plex ne le remplacera donc plus lors des actualisations, et le script l'ignorera lors des lancements suivants.
- Rien n'est supprimé : l'ancien logo reste disponible dans Plex (*Modifier > Logo*).
- Seul le logo principal du film ou de la série est traité, pas ceux des saisons ou des épisodes.
- Pour les titres marqués `[NONE]` ou `[CHECK]`, il faut choisir un logo à la main dans Plex ou en importer un.
- `config.env`, les dossiers `logs/`, `.venv/` et le cache `.cache-ocr.json` ne sont pas à publier (voir `.gitignore`) : ils contiennent ton token ou la liste de tes titres.

## Tests

La détection des logos québécois et les notifications sont couvertes par des tests construits à partir de cas réels (Edge of Tomorrow, Bullet Train, Captain America, Avatar…). Ils ne nécessitent ni serveur Plex ni moteur OCR :

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests
```

GitHub Actions les lance à chaque envoi de code (Python 3.8 et 3.12).

## Licence

MIT, voir [LICENSE](LICENSE).
