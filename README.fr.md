# plex smart logo updater

**Des logos Plex (ClearLogo) mieux choisis : le bon logo dans la langue de chaque bibliothèque, l'anglais en secours, et pas de logos québécois dans les bibliothèques françaises.**

L'interface du script (messages, logs, page de contrôle, assistant) est en anglais. Cette page en décrit le fonctionnement en français.

🇬🇧 [English version](README.md)

Script Python qui donne à tes films et séries Plex un **logo de qualité dans la langue de leur bibliothèque**, y compris aux nombreux titres que Plex laisse sans logo. Pour les bibliothèques en français, il repère et remplace aussi les **logos québécois** que Plex pose parfois par erreur.

Chaque changement est d'abord prévisualisé : simulation, page de contrôle pour valider ou refuser chaque logo, et journal d'annulation.

Basé sur [relkai/plex-bulk-logo-updater](https://github.com/relkai/plex-bulk-logo-updater) (licence MIT).

![Page de contrôle : logos québécois (à gauche) remplacés par des logos français (à droite)](docs/review-quebec.png)

## Le problème

Plex ne pose un logo automatiquement **que s'il en existe un dans la langue de la bibliothèque**. Dans une bibliothèque en français, en allemand ou en espagnol, un titre sans logo dans cette langue reste donc sans logo, même s'il en existe un bon en anglais. C'est très fréquent pour les animes et les films étrangers.

Les bibliothèques en français ont un second piège : **Plex ne distingue pas le français de France du français du Québec.** Il peut poser un logo québécois dans une bibliothèque française. Le titre affiché est alors « The Banker » alors que le logo indique « Le financier » ; de même, « Edge of Tomorrow » peut s'afficher avec le logo « Un jour sans lendemain ».

Le script d'origine se contentait de prendre le premier logo de la liste, qui peut être dans la mauvaise langue ou de mauvaise qualité.

Par défaut, chaque bibliothèque utilise **sa propre langue** (celle réglée dans Plex), puis l'anglais : une bibliothèque en français reçoit des logos français, une bibliothèque allemande des logos allemands, une bibliothèque anglaise des logos anglais.

## Ce que fait `plex-smart-logo-updater.py`

Pour chaque titre des bibliothèques choisies :

1. **Il ne touche jamais à un logo choisi à la main** (verrouillé), sauf avec `--fix-locked-quebec` s'il est québécois. Il ne touche pas non plus aux logos posés par Plex, **sauf s'ils sont québécois**.
2. **Pour les titres sans logo, il demande à Plex le logo qu'il recommande**, dans la langue de la bibliothèque d'abord, puis en anglais s'il n'y en a pas. C'est exactement le logo que Plex aurait choisi lui-même. Le script interroge pour cela le service de métadonnées de Plex (`metadata.provider.plex.tv`) avec ton token Plex, sans clé TMDB.
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

Tu débutes avec GitHub ou la ligne de commande ? Ce guide pas à pas t'emmène de zéro jusqu'à ta première simulation. Compte une dizaine de minutes, surtout pour les téléchargements.

### Ce qu'il te faut

- **Une machine Linux qui accède à ton serveur Plex** : le serveur Plex lui-même, une seedbox, un NAS, un VPS… Testé sous Linux ; macOS devrait fonctionner ; sous Windows, utilise [WSL](https://learn.microsoft.com/fr-fr/windows/wsl/install).
- **Python 3.8 ou plus récent** et **git**.
- **Ton token Plex** ([comment le trouver](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)).
- Environ **500 Mo d'espace libre** pour l'environnement Python (le moteur OCR en est la plus grosse partie).

### Étape 1 — Ouvrir un terminal sur la machine

Si la machine est distante (seedbox, NAS, VPS), connecte-toi en SSH depuis ton ordinateur : ouvre un terminal (PowerShell sous Windows, Terminal sous macOS/Linux) et tape :

```bash
ssh ton_utilisateur@adresse_du_serveur
```

Vérifie ensuite que Python et git sont installés :

```bash
python3 --version
git --version
```

Chaque commande doit afficher un numéro de version (Python doit être en 3.8 ou plus). S'il en manque un, installe-le avec le gestionnaire de paquets de ton système (par exemple `sudo apt install python3 python3-venv git` sous Debian/Ubuntu) ou demande à ton hébergeur.

### Étape 2 — Télécharger le projet (« cloner » le dépôt)

Place-toi dans le dossier où tu veux l'installer (ton dossier personnel convient très bien), puis clone le dépôt. Cloner télécharge le projet et garde le lien avec GitHub, ce qui permet de le mettre à jour plus tard en une commande.

```bash
cd ~
git clone https://github.com/sSlydee/plex-smart-logo-updater.git
cd plex-smart-logo-updater
```

Tu as maintenant un dossier `plex-smart-logo-updater` qui contient les scripts.

### Étape 3 — Installer

```bash
./install.sh
```

L'installateur crée un environnement Python dédié dans le dossier `.venv` (rien n'est installé sur le reste du système), télécharge les dépendances (quelques minutes), puis lance l'**assistant de configuration**.

L'installateur remplace OpenCV 5, installé avec l'OCR, par une version plus ancienne : sur certaines machines, OpenCV 5 plante au chargement.

### Étape 4 — Répondre à l'assistant

L'assistant pose cinq questions (en anglais) ; appuie sur Entrée pour accepter la valeur affichée entre `[crochets]`.

1. **Adresse du serveur Plex** : l'adresse **locale** du serveur, avec son port.
   - Le script tourne sur le serveur Plex lui-même : `http://127.0.0.1:32400`.
   - Plex tourne dans Docker sur la même machine : souvent `http://172.17.0.1:32400`.
   - Une autre machine de ton réseau : `http://192.168.x.x:32400`.

   Évite un nom de domaine public derrière un reverse proxy : le nombre de requêtes pourrait te faire bloquer par Fail2Ban ou CrowdSec.
2. **Token Plex** : colle-le (rien ne s'affiche pendant que tu le colles, c'est normal). L'assistant teste la connexion tout de suite.
3. **Bibliothèques** : tape les numéros des bibliothèques à traiter, séparés par des virgules (par exemple `1,3,4`), ou `all`.
4. **Langue des logos** : garde `auto` (la langue de chaque bibliothèque, puis l'anglais), sauf raison particulière.
5. **Notifications** et **analyse automatique** : facultatives, tu peux répondre `n` / `never` maintenant et y revenir plus tard (voir [Configuration](#configuration)).

Tes réponses sont enregistrées dans `config.env`, lisible par toi seul.

### Étape 5 — Première simulation

```bash
.venv/bin/python plex-smart-logo-updater.py --html
```

Rien n'est modifié dans Plex. Le premier lancement est plus long (environ 7 minutes pour 300 films), car il lit les logos ; les suivants utilisent un cache. À la fin, le résumé indique ce qui changerait et où se trouve la page de contrôle (`review.html`).

Suis ensuite la [méthode recommandée](#méthode-recommandée--simulation-contrôle-application) pour contrôler et appliquer les changements.

> Lance toujours le script avec `.venv/bin/python`, pas `python3` : les dépendances ne sont installées que dans `.venv`.

### Récupérer les fichiers d'une machine distante

Pour ouvrir `review.html` sur ton ordinateur et renvoyer `choices.json`, utilise un client SFTP avec la même adresse et les mêmes identifiants qu'en SSH :

- **Windows** : [WinSCP](https://winscp.net/) ou [FileZilla](https://filezilla-project.org/)
- **macOS** : [Cyberduck](https://cyberduck.io/) ou FileZilla
- **Linux** : ton gestionnaire de fichiers (`sftp://ton_utilisateur@adresse_du_serveur`) ou FileZilla

Ou depuis un terminal sur ton ordinateur :

```bash
scp ton_utilisateur@adresse_du_serveur:plex-smart-logo-updater/logs/<dossier>/review.html .
scp choices.json ton_utilisateur@adresse_du_serveur:plex-smart-logo-updater/logs/<dossier>/
```

### Mettre à jour

```bash
cd ~/plex-smart-logo-updater
git pull
./install.sh --no-config
```

`git pull` télécharge la nouvelle version depuis GitHub ; `./install.sh --no-config` met à jour les dépendances sans reposer les questions de l'assistant. Ton `config.env`, tes logs et le cache sont conservés. Voir [CHANGELOG.md](CHANGELOG.md) pour les nouveautés.

### Désinstaller

```bash
cd ~/plex-smart-logo-updater
.venv/bin/python configure.py --cron     # choisir "never" pour retirer l'analyse automatique
cd ~
rm -rf plex-smart-logo-updater
```

Les logos déjà posés dans Plex restent en place. Pour remettre d'abord les anciens logos, utilise [`--undo`](#annuler-une-application) sur tes dossiers d'application.

### Problèmes courants

| Problème | Solution |
|---|---|
| `Permission denied` en lançant `./install.sh` | Lance plutôt `bash install.sh`. |
| `Python 3.8 or later is required` | Installe un Python plus récent, ou lance `PYTHON=python3.11 ./install.sh` si plusieurs versions sont installées. |
| `No module named ...` | Lance le script avec `.venv/bin/python`, pas `python3`. |
| `Plex token rejected` | Ton token a changé : `.venv/bin/python configure.py --token`. |
| `Cannot connect to the Plex server` | Vérifie l'adresse et le port ; depuis la machine, `curl http://adresse:32400/identity` doit répondre. |
| `Libraries not found` | Les noms dans `PLEX_LIBRARIES` doivent correspondre exactement à Plex : `.venv/bin/python configure.py --libraries`. |
| L'installateur s'arrête avec `The dependencies do not load correctly` | Supprime le dossier `.venv` et relance `./install.sh` ; si ça persiste, ouvre une issue avec la sortie complète. |

## Configuration

L'assistant de configuration (étape 4 ci-dessus) écrit `config.env` à côté du script. Il couvre :

1. l'adresse du serveur Plex et ton token, avec un **test de connexion** ;
2. les bibliothèques à traiter, choisies dans la **liste de ton serveur** ;
3. la langue des logos (par défaut, la langue de chaque bibliothèque, puis l'anglais) ;
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
| `PLEX_LANGUAGES` | Langues par ordre de préférence (facultatif). `auto` : la langue de chaque bibliothèque, puis l'anglais | `auto` (par défaut), ou par exemple `fr-FR,en-US` pour toutes les bibliothèques |
| `NOTIFY_URLS` | Webhooks pour `--notify`, séparés par des virgules (facultatif) | voir [Notifications](#notifications) |
| `PLEX_LOGS_DIR` | Dossier des logs (facultatif) | `logs/` à côté du script (par défaut) |
| `PLEX_OCR_CACHE` | Cache des lectures OCR (facultatif) | `.cache-ocr.json` à côté du script (par défaut) |
| `PLEX_IGNORE_FILE` | Liste des titres ignorés (facultatif) | `ignored.json` à côté du script (par défaut) |
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
| `--ignore TITRE` | Ne plus jamais toucher à ce titre (voir [Titres ignorés](#titres-ignorés)) |
| `--unignore TITRE` | Retire un titre de la liste des titres ignorés |
| `--list-ignored` | Affiche la liste des titres ignorés |
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

Seuls les changements validés sont appliqués. Un titre refusé est marqué `[REJECTED]` et ajouté aux [titres ignorés](#titres-ignorés). Si le logo prévu a changé depuis la simulation, le titre est marqué `[RECHECK]` et n'est pas modifié.

### Titres ignorés

Certains titres doivent rester tels quels : un changement que tu as refusé dans la page de contrôle, ou un logo que tu as retiré volontairement. Sans liste de titres ignorés, l'analyse hebdomadaire les reproposerait et te notifierait à chaque fois.

- **Les refus sont retenus** : quand tu appliques avec `--choices`, chaque titre refusé est ajouté à la liste et n'est plus proposé.
- **Ajouter un titre à la main** :

  ```bash
  .venv/bin/python plex-smart-logo-updater.py --ignore "Films/Edge of Tomorrow"
  ```

  Le titre peut s'écrire `Bibliothèque/Titre`, `Titre`, `Titre (année)` ou avec son ratingKey Plex. Si plusieurs titres correspondent, le script les liste pour que tu précises.
- **Retirer un titre** avec `--unignore "Edge of Tomorrow"`, et afficher la liste avec `--list-ignored`.

Les titres ignorés apparaissent dans les logs avec l'étiquette `[IGNORED]`. La liste est dans `ignored.json`, à côté du script (non publié).

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
| `[IGNORED]` | Dans la liste des titres ignorés : ignoré |
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
- `config.env`, `ignored.json`, les dossiers `logs/`, `.venv/` et le cache `.cache-ocr.json` ne sont pas à publier (voir `.gitignore`) : ils contiennent ton token ou la liste de tes titres.

## Tests

La détection des logos québécois et les notifications sont couvertes par des tests construits à partir de cas réels (Edge of Tomorrow, Bullet Train, Captain America, Avatar…). Ils ne nécessitent ni serveur Plex ni moteur OCR :

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests
```

GitHub Actions les lance à chaque envoi de code (Python 3.8 et 3.12).

## Crédits

- Inspiré de [relkai/plex-bulk-logo-updater](https://github.com/relkai/plex-bulk-logo-updater).
- Développé avec l'aide d'un assistant IA (Claude), puis relu et testé sur une vraie bibliothèque Plex.

## Licence

MIT, voir [LICENSE](LICENSE).
