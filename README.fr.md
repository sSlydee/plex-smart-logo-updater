# Plex Smart Logo Updater

[![Tests](https://github.com/sSlydee/plex-smart-logo-updater/actions/workflows/tests.yml/badge.svg)](https://github.com/sSlydee/plex-smart-logo-updater/actions/workflows/tests.yml) [![Release](https://img.shields.io/github/v/release/sSlydee/plex-smart-logo-updater)](https://github.com/sSlydee/plex-smart-logo-updater/releases) [![Licence : MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Des logos Plex (ClearLogo) dans la langue de chaque bibliothèque, avec l'anglais en secours. Dans les bibliothèques françaises, le script remplace aussi les logos québécois que Plex choisit par erreur, et en option les affiches québécoises.**

🇬🇧 [English version](README.md)

> Le script, ses messages, ses logs et sa page de contrôle sont en anglais. Ce document les décrit en français.

![Page de contrôle : logos québécois (à gauche) remplacés par des logos français (à droite)](docs/review-quebec.png)

## Pourquoi

- **Beaucoup de titres n'ont pas de logo.** Plex ne pose un logo automatiquement que s'il en existe un dans la langue de la bibliothèque. Dans une bibliothèque française, allemande ou espagnole, un titre reste donc sans logo même quand un bon logo anglais existe. C'est très fréquent pour les animés et les films étrangers.
- **Les bibliothèques françaises reçoivent des logos québécois.** Plex ne distingue pas le français de France du français du Québec. *The Banker* peut se retrouver avec un logo « Le financier », et *Edge of Tomorrow* avec « Un jour sans lendemain ».
- **Même chose pour les affiches.** *Bad Boys 2* peut afficher « Mauvais garçons II », et *Land of Bad* « Territoire hostile ».

## Ce que fait le script

- **Il ajoute les logos manquants.** Pour un titre sans logo, le script demande à Plex le logo recommandé, d'abord dans la langue de la bibliothèque, puis en anglais. C'est le logo que Plex aurait choisi lui-même, et aucune clé TMDB n'est nécessaire.
- **Il remplace les logos québécois**, et en option les affiches québécoises. Il lit le texte de l'image (OCR) et le compare aux titres français, québécois et original.
- **Il ne touche à rien d'autre.** Un logo existant est gardé, sauf s'il est québécois. Les logos et affiches que vous avez choisis vous-même (champs verrouillés) ne sont jamais remplacés.
- **Il ne change rien sans votre accord.** Chaque lancement est une simulation par défaut. Une page de contrôle montre chaque changement (avant et après) pour que vous le validiez ou le refusiez. Chaque application peut être annulée.
- **Il peut tourner tout seul.** Il peut analyser vos bibliothèques à intervalle régulier (chaque jour ou chaque semaine), vérifier les nouveaux titres dès que Plex les ajoute (avec Tautulli), et vous envoyer une notification (Discord, Bark…) quand il y a quelque chose à valider.

Basé sur [relkai/plex-bulk-logo-updater](https://github.com/relkai/plex-bulk-logo-updater) (licence MIT).

## Sommaire

- [Démarrage rapide](#démarrage-rapide)
- [Installation pas à pas](#installation-pas-à-pas)
- [Utilisation au quotidien](#utilisation-au-quotidien) : simulation, contrôle, application, titres ignorés, annulation
- [Automatisation](#automatisation) : analyse automatique, notifications, Tautulli, Uptime Kuma
- [Référence](#référence) : assistant, réglages, options
- [Comment ça marche](#comment-ça-marche) : choix de la langue, détection du Québec, affiches
- [Logs](#logs)
- [Problèmes courants](#problèmes-courants) · [Bon à savoir](#bon-à-savoir) · [Tests](#tests)

## Démarrage rapide

Pour les habitués du terminal. Linux (ou macOS, ou WSL sous Windows), Python 3.8+ et git :

```bash
git clone https://github.com/sSlydee/plex-smart-logo-updater.git
cd plex-smart-logo-updater
./install.sh                                          # installe dans .venv, puis lance l'assistant
.venv/bin/python plex-smart-logo-updater.py --html    # simulation + page de contrôle
```

Suivez ensuite les étapes de l'[utilisation au quotidien](#utilisation-au-quotidien).

## Installation pas à pas

Vous débutez avec GitHub ou le terminal ? Ce guide vous amène de zéro à votre première simulation en une dizaine de minutes, passées pour l'essentiel à attendre les téléchargements.

### Ce qu'il vous faut

- **Une machine qui accède à votre serveur Plex** : le serveur Plex lui-même, une seedbox, un NAS, un VPS… Le script est testé sous Linux. macOS devrait fonctionner, et sous Windows il faut passer par [WSL](https://learn.microsoft.com/fr-fr/windows/wsl/install).
- **Python 3.8 ou plus récent** et **git**.
- **Votre token Plex** ([comment le trouver](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)).
- Environ **500 Mo d'espace disque** pour l'environnement Python. Le moteur OCR en est la plus grosse partie.

### 1. Ouvrir un terminal sur la machine

Si la machine est distante, connectez-vous en SSH. Sur votre ordinateur, ouvrez un terminal (PowerShell sous Windows, Terminal sous macOS/Linux) et tapez :

```bash
ssh votre_utilisateur@adresse_du_serveur
```

Vérifiez ensuite que Python et git sont installés :

```bash
python3 --version
git --version
```

Chaque commande doit afficher un numéro de version, et Python doit être en 3.8 ou plus. S'il en manque un, installez-le avec le gestionnaire de paquets de votre système (sous Debian/Ubuntu : `sudo apt install python3 python3-venv git`) ou demandez à votre hébergeur.

### 2. Télécharger le projet

Cloner le dépôt télécharge le projet et conserve le lien avec GitHub, ce qui permet de le mettre à jour plus tard en une seule commande :

```bash
cd ~
git clone https://github.com/sSlydee/plex-smart-logo-updater.git
cd plex-smart-logo-updater
```

### 3. Installer

```bash
./install.sh
```

L'installateur crée un environnement Python dédié dans le dossier `.venv`, donc rien n'est installé sur le système. Il télécharge les dépendances (quelques minutes), puis lance l'assistant de configuration.

### 4. Répondre à l'assistant

Appuyez sur Entrée pour garder la valeur affichée entre `[crochets]`.

1. **Adresse du serveur Plex** : l'adresse **locale** du serveur, avec son port.
   - Le script tourne sur le serveur Plex lui-même : `http://127.0.0.1:32400`.
   - Plex tourne dans Docker sur la même machine : souvent `http://172.17.0.1:32400`.
   - Une autre machine du réseau : `http://192.168.x.x:32400`.

   Évitez un nom de domaine public derrière un reverse proxy. Le script envoie beaucoup de requêtes, et Fail2Ban ou CrowdSec pourraient le bloquer.
2. **Token Plex** : collez-le. Rien ne s'affiche pendant que vous collez, c'est normal. L'assistant teste la connexion tout de suite.
3. **Bibliothèques** : les numéros des bibliothèques à traiter, séparés par des virgules (ex. `1,3,4`), ou `all`.
4. **Langue des logos** : gardez `auto` (la langue de chaque bibliothèque, puis l'anglais). L'assistant demande ensuite s'il faut aussi remplacer les [affiches québécoises](#affiches-québécoises).
5. **Notifications** : facultatives. Répondez `n` pour ne pas ajouter de webhook, puis laissez vide l'URL Uptime Kuma.
6. **Analyse automatique** : Entrée programme une simulation chaque semaine. Choisissez `never` (tapez `1`) si vous préférez commencer à la main ; vous pourrez l'ajouter plus tard.

Vos réponses sont enregistrées dans `config.env`, un fichier lisible par vous seul.

### 5. Première simulation

```bash
.venv/bin/python plex-smart-logo-updater.py --html
```

Rien n'est modifié dans Plex. La première analyse prend du temps (environ 7 minutes pour 300 films) parce qu'elle lit les logos. Les suivantes utilisent un cache et vont bien plus vite. À la fin, le résumé indique ce qui changerait et où se trouve la page de contrôle.

> Lancez toujours le script avec `.venv/bin/python`, pas `python3` : les dépendances ne sont installées que dans `.venv`.

### Mettre à jour

```bash
cd ~/plex-smart-logo-updater
git pull
./install.sh --no-config
```

`git pull` télécharge la nouvelle version, et `./install.sh --no-config` met à jour les dépendances sans reposer les questions de configuration. Vos réglages, logs et cache sont conservés. Les nouveautés sont dans [CHANGELOG.md](CHANGELOG.md).

### Désinstaller

```bash
cd ~/plex-smart-logo-updater
.venv/bin/python configure.py --cron       # choisissez "never" pour retirer l'analyse automatique
.venv/bin/python configure.py --tautulli   # file Tautulli, si activée : choisissez "off"
cd ~
rm -rf plex-smart-logo-updater
```

Si vous avez installé le hook Tautulli, supprimez aussi son agent Script dans Tautulli. Les logos et affiches déjà posés dans Plex restent en place. Pour remettre les précédents, [annulez](#annuler-une-application) vos applications avant de supprimer le dossier.

## Utilisation au quotidien

Chaque changement passe par trois étapes : une **simulation** qui génère une page de contrôle, votre **contrôle**, puis l'**application** de ce que vous avez validé.

### 1. Simulation

```bash
.venv/bin/python plex-smart-logo-updater.py --html
```

Chaque lancement crée un dossier dans `logs/`, nommé d'après la date et le mode (`2026-09-23_18h20m05_simulation` pour une simulation). Avec `--html`, la page de contrôle `review.html` y est générée.

### 2. Contrôle

Ouvrez `review.html` dans votre navigateur. C'est un fichier unique et autonome : les images sont intégrées, et il ne contient ni l'adresse de votre serveur ni votre token.

![Page de contrôle avec tous les changements](docs/review-all.png)

- Chaque changement montre l'image actuelle et la nouvelle.
- Tout est **validé** par défaut : cliquez sur **Reject** pour les changements que vous ne voulez pas.
- Des filtres permettent de commencer par les cas douteux (« Not verified », « Original title », « Posters »…).
- Vos choix sont gardés dans le navigateur si vous fermez la page.
- Quand vous avez fini, cliquez sur **Export choices.json**.

Si le script tourne sur une machine distante, récupérez les fichiers avec un client SFTP (même adresse et même identifiant que pour SSH) : [WinSCP](https://winscp.net/) ou [FileZilla](https://filezilla-project.org/) sous Windows, [Cyberduck](https://cyberduck.io/) ou FileZilla sous macOS, ou votre gestionnaire de fichiers (`sftp://votre_utilisateur@adresse_du_serveur`) sous Linux. Depuis un terminal sur votre ordinateur :

```bash
scp votre_utilisateur@adresse_du_serveur:plex-smart-logo-updater/logs/<dossier>/review.html .
scp choices.json votre_utilisateur@adresse_du_serveur:plex-smart-logo-updater/logs/<dossier>/
```

### 3. Application

Déposez `choices.json` dans le dossier de la simulation, puis :

```bash
.venv/bin/python plex-smart-logo-updater.py --apply --choices logs/<dossier de la simulation>/choices.json
```

Seuls les changements validés sont appliqués, et ceux que vous avez refusés vont dans les [titres ignorés](#titres-ignorés). Si Plex a modifié un titre depuis la simulation, le titre n'est pas touché et reçoit le tag `[RECHECK]` : relancez une simulation.

Pour tout appliquer sans passer par la page de contrôle, lancez `--apply` sans `--choices`. Ce n'est pas recommandé.

### Titres ignorés

Certains titres doivent rester tels quels : un changement que vous avez refusé, ou un logo retiré volontairement. Sans la liste des titres ignorés, l'analyse automatique les proposerait à nouveau et vous notifierait à chaque fois.

- **Les refus sont retenus.** Quand vous appliquez avec `--choices`, chaque changement refusé rejoint les titres ignorés et n'est plus proposé. Refuser une affiche n'ignore que l'affiche : le logo du titre reste vérifié.
- **Ajoutez un titre à la main** pour que le script n'y touche plus du tout :

  ```bash
  .venv/bin/python plex-smart-logo-updater.py --ignore "Films/Edge of Tomorrow"
  ```

  Le titre peut être donné sous la forme `Bibliothèque/Titre`, `Titre`, `Titre (année)` ou un ratingKey Plex. Si plusieurs titres correspondent, le script les liste pour que vous précisiez.
- **Retirez un titre** avec `--unignore "Edge of Tomorrow"`, et **affichez la liste** avec `--list-ignored`.

La liste est enregistrée dans `ignored.json`, à côté du script.

### Annuler une application

Chaque application enregistre l'état précédent dans `undo.json`, dans son dossier de logs. Pour tout remettre comme avant :

```bash
.venv/bin/python plex-smart-logo-updater.py --undo logs/<dossier de l'application>            # simulation
.venv/bin/python plex-smart-logo-updater.py --undo logs/<dossier de l'application> --apply    # restauration
```

- Chaque logo ou affiche retrouve son image précédente, avec son verrouillage d'origine. Un titre qui n'avait pas de logo redevient sans logo.
- Une image modifiée depuis l'application, par vous ou par Plex, n'est pas touchée.

## Automatisation

### Analyse automatique

L'assistant peut programmer une analyse automatique avec cron (quotidienne ou hebdomadaire). Elle fait une **simulation** avec la page de contrôle et les notifications. **Rien n'est jamais appliqué automatiquement** : quand il y a quelque chose à valider, vous recevez une notification, vous contrôlez la page, puis vous appliquez avec `--choices`.

La sortie va dans `logs/cron.log` (gardé sous 5 Mo). L'assistant ne gère que ses propres lignes de crontab, repérées par `# plex-smart-logo-updater`. Pour changer la fréquence : `.venv/bin/python configure.py --cron`.

### Notifications

Avec `--notify` (inclus dans l'analyse automatique), le script envoie un résumé **uniquement quand il y a quelque chose à faire** : des changements à valider, des titres à traiter à la main, ou des erreurs. Un titre à traiter à la main n'est signalé qu'une fois. Pour les changements qui attendent encore votre validation, chaque analyse complète envoie un rappel.

`NOTIFY_URLS` peut contenir plusieurs webhooks, séparés par des virgules. Le type est deviné d'après l'adresse, ou forcé avec un préfixe :

| Service | Exemple dans `NOTIFY_URLS` |
|---|---|
| Discord | `https://discord.com/api/webhooks/…` |
| Bark (serveur officiel) | `https://api.day.app/<votre clé>` |
| Bark (auto-hébergé) | `bark:https://mon-serveur-bark.example/<votre clé>` |
| Webhook générique (POST JSON avec `title`, `message`, `text`) | `json:https://example.org/hook` |

Les adresses des webhooks ne sont jamais écrites dans les logs. Pour les changer : `.venv/bin/python configure.py --notifications`.

### Nouveaux titres tout de suite, avec Tautulli

Avec [Tautulli](https://tautulli.com/), les nouveaux films et séries sont vérifiés quelques minutes après leur ajout dans Plex, au lieu d'attendre la prochaine analyse automatique.

Dans Tautulli, allez dans **Settings > Notification Agents > Add a new notification agent > Script** :

| Réglage | Valeur |
|---|---|
| Script Folder | le dossier du projet (celui qui contient `tautulli-hook.sh`) |
| Script File | `tautulli-hook.sh` |
| Triggers | **Recently Added** |
| Arguments > Recently Added | `{rating_key}` |

Le hook ajoute le nouveau titre à une file d'attente. Si c'est possible, il traite ensuite la file immédiatement (simulation, page de contrôle, notification), avec la sortie dans `logs/tautulli.log`.

**Tautulli dans un conteneur** (fréquent sur les seedbox, par exemple avec les images linuxserver) : le conteneur voit le dossier du projet mais ne peut en général pas lancer son environnement Python. Deux choses changent :

- Dans Tautulli, le Script Folder est le chemin **tel que le conteneur le voit**, souvent `/home/<utilisateur>/...`.
- Sur la machine, activez le traitement de la file avec `.venv/bin/python configure.py --tautulli`. Une tâche cron traite alors la file toutes les 5 minutes, et ne fait rien quand elle est vide.

Quelques précisions :

- Un épisode ou une saison compte comme sa série. Les titres hors de `PLEX_LIBRARIES` ne sont pas traités.
- Une saison importée épisode par épisode ne vous inonde pas : chaque changement en attente n'est notifié qu'une fois. L'analyse automatique envoie quand même un rappel tant qu'un changement attend votre validation.
- Les lancements simultanés s'attendent les uns les autres.
- Si Plex n'a pas encore récupéré les images d'un titre au moment de la vérification, l'analyse automatique suivante le rattrape.

Pour traiter des titres à la main : `--rating-key 12345`, ou `--process-queue` pour la file d'attente.

### Surveillance avec Uptime Kuma

Avec `HEALTHCHECK_URL`, chaque lancement envoie un signal à un service de surveillance. Il indique **up** quand tout s'est bien passé, et **down** avec la raison en cas d'échec (token refusé, serveur injoignable, plantage). Si l'analyse automatique s'arrête complètement (cron cassé, machine éteinte…), l'absence de signal vous prévient.

Dans [Uptime Kuma](https://github.com/louislam/uptime-kuma), allez dans **Add New Monitor > Push**. Copiez l'URL de push dans `HEALTHCHECK_URL`, ou donnez-la à `configure.py --notifications`. Réglez ensuite le **heartbeat interval** un peu au-dessus de la fréquence de votre cron, par exemple 8 jours (691200 s) pour une analyse hebdomadaire. Une URL [healthchecks.io](https://healthchecks.io/) fonctionne aussi.

## Référence

### Assistant de configuration

`configure.py` écrit `config.env`. Vous pouvez le relancer à tout moment : les valeurs actuelles sont proposées par défaut, appuyez sur Entrée pour les garder.

```bash
.venv/bin/python configure.py
```

Pour refaire une seule étape :

| Commande | Effet |
|---|---|
| `configure.py --token` | Change **uniquement le token** : il est demandé, testé, puis enregistré |
| `configure.py --server` | Adresse du serveur et token |
| `configure.py --libraries` | Bibliothèques à traiter |
| `configure.py --language` | Langue des logos et affiches québécoises |
| `configure.py --notifications` | Webhooks et Uptime Kuma |
| `configure.py --cron` | Analyse automatique |
| `configure.py --tautulli` | Traitement de la file pour Tautulli dans un conteneur |

Un nouveau token n'est enregistré que si Plex l'accepte. **Si votre token change**, le script s'arrête avec « Plex token rejected: change it with: .venv/bin/python configure.py --token », et envoie aussi ce message en notification quand il est lancé avec `--notify`.

### Réglages (`config.env`)

L'assistant écrit ce fichier et le rend lisible par vous seul, parce qu'il contient votre token. Vous pouvez aussi l'écrire à la main à partir de `config.env.example`.

| Variable | Rôle | Défaut / exemple |
|---|---|---|
| `PLEX_URL` | Adresse **locale** du serveur Plex | `http://192.168.1.100:32400` |
| `PLEX_TOKEN` | Votre token Plex | |
| `PLEX_LIBRARIES` | Bibliothèques à traiter, séparées par des virgules | `Films,Séries TV,Animés` |
| `PLEX_LANGUAGES` | Langues par ordre de préférence. `auto` : la langue de chaque bibliothèque, puis l'anglais | `auto`, ou par exemple `fr-FR,en-US` pour toutes les bibliothèques |
| `PLEX_POSTERS` | `yes` : remplace aussi les [affiches québécoises](#affiches-québécoises) | `no` |
| `NOTIFY_URLS` | [Webhooks](#notifications) pour `--notify`, séparés par des virgules | |
| `HEALTHCHECK_URL` | URL de push [Uptime Kuma](#surveillance-avec-uptime-kuma) | |
| `PLEX_LOGS_DIR` | Dossier des logs | `logs/` à côté du script |
| `PLEX_LOGS_KEEP` | Nombre de dossiers de simulation gardés. Les dossiers d'application (avec `undo.json`) sont toujours gardés | `100` |
| `PLEX_OCR_CACHE` | Cache de l'OCR | `.cache-ocr.json` à côté du script |
| `PLEX_IGNORE_FILE` | Liste des titres ignorés | `ignored.json` à côté du script |

Une variable donnée au lancement est prioritaire sur `config.env`. Par exemple, pour ne traiter qu'une bibliothèque :

```bash
PLEX_LIBRARIES="Films" .venv/bin/python plex-smart-logo-updater.py
```

### Options

| Option | Effet |
|---|---|
| *(aucune)* | Simulation : rien n'est modifié |
| `--html` | Génère la page de contrôle `review.html` |
| `--apply` | Applique les changements |
| `--choices FICHIER` | Avec `--apply` : n'applique que les changements validés dans la page de contrôle |
| `--posters` | Remplace aussi les [affiches québécoises](#affiches-québécoises) (comme `PLEX_POSTERS=yes`) |
| `--fix-locked-quebec` | Remplace aussi les logos et affiches **verrouillés** détectés comme québécois |
| `--notify` | Envoie une notification quand il y a quelque chose à faire |
| `--quiet` | N'affiche que le résumé (le détail reste dans les logs) |
| `--rating-key CLÉ` | Ne traite que ces titres (ratingKey Plex) |
| `--process-queue` | Traite les titres mis en file par le hook Tautulli |
| `--ignore TITRE` / `--unignore TITRE` / `--list-ignored` | Gère les [titres ignorés](#titres-ignorés) |
| `--undo DOSSIER` | [Annule](#annuler-une-application) une application (simulation sauf avec `--apply`) |
| `--replace` | Remplace aussi les logos posés par Plex qui diffèrent de sa recommandation actuelle |
| `--replace --include-locked` | Remplace aussi les logos choisis à la main (déconseillé) |

`--help` liste toutes les options.

Attention avec `--replace` : sur TMDB, un logo « français » est parfois la version québécoise, et l'OCR ne la repère pas toujours. C'est pourquoi, par défaut, le script ne remplace que les logos détectés comme québécois.

Pendant une application, le script attend 2 s après chaque changement et 10 s tous les 10 changements, pour ménager le serveur. Les erreurs temporaires (429, 5xx) sont réessayées jusqu'à 4 fois.

## Comment ça marche

### Choix du logo

Pour chaque titre **sans logo**, le script demande au service de métadonnées de Plex (`metadata.provider.plex.tv`, avec votre token) le logo qu'il recommande : d'abord dans la langue de la bibliothèque, puis en anglais. Il cherche ce logo parmi ceux que propose votre serveur (même adresse, ou image identique) et le sélectionne. Il ne le télécharge depuis Internet que si votre serveur ne l'a pas.

Un titre qui a déjà un logo le garde, sauf si ce logo est québécois. Un champ verrouillé *sans* logo reçoit une proposition comme n'importe quel titre sans logo. Pour le laisser vide, refusez la proposition : le titre rejoint alors les titres ignorés.

### Détection des logos québécois

Cette détection ne concerne que les bibliothèques françaises. Quand les titres français (fr-FR) et québécois (fr-CA) donnés par Plex diffèrent, le script **lit le texte du logo** (OCR) et le compare aux titres français, québécois et original.

- **Un logo québécois posé par Plex est remplacé** par le meilleur logo non québécois : le plus proche du titre français complet, sinon du titre original. À ressemblance égale, il préfère, dans l'ordre : un logo sans texte en plus (noms d'acteurs, slogans ; « Marvel Studios », « Disney »… sont acceptés), un logo du même style que celui remplacé (coloré ou blanc), celui que Plex recommande, puis le plus grand.
- **Un logo québécois n'est jamais ajouté.** Si Plex en recommande un, le script en cherche un autre.
- Quand le titre français diffère du titre original et que le choix de Plex n'est pas clairement français, le script cherche un logo au titre français (ex. « HAPPY BIRTHDEAD » plutôt que « HAPPY DEATH DAY »). Quand la France garde le titre original, le choix de Plex est conservé.
- Quand le Québec garde le titre original (*Black Box Diaries*), un logo portant ce titre n'est **pas** considéré comme québécois.
- S'il n'existe **que** des logos québécois, le titre reçoit le tag `[CHECK]` : choisissez-en un à la main.
- Un logo québécois **verrouillé** est signalé, et n'est remplacé qu'avec `--fix-locked-quebec`.

La détection est volontairement prudente : un logo existant n'est remplacé que s'il est clairement lu comme québécois. Trois **mentions spéciales** signalent les logos posés avec moins de certitude, et la page de contrôle a un filtre pour chacune :

| Mention | Signification |
|---|---|
| `[FRENCH INFERRED]` (français déduit) | Le titre français est lu sur le logo, et les mots propres au titre québécois en sont absents (ex. « PUSH », alors que le Québec dit « Push : La division »). Très probablement correct. |
| `[ORIGINAL TITLE]` (titre original) | Le logo porte le titre original, ni français ni québécois (ex. « HAPPY DEATH DAY » pour *Happy Birthdead*). |
| `[NOT VERIFIED]` (non vérifié) | L'OCR n'a pas pu lire le logo (police très stylisée, lettres espacées…). Il est posé quand même, comme Plex l'aurait fait : **à contrôler**. |

Les lectures OCR sont gardées en cache (`.cache-ocr.json`) : une nouvelle analyse ne lit que les nouvelles images.

### Affiches québécoises

Cette vérification est facultative : activez-la avec `--posters`, ou `PLEX_POSTERS=yes` (l'assistant pose la question). Elle fonctionne comme la détection des logos, dans les bibliothèques françaises, pour les titres dont le titre québécois diffère :

- L'affiche actuelle est lue. Si c'est une **affiche québécoise**, le script en cherche une au titre français, sinon au titre original, parmi les 30 premières affiches proposées par Plex. À ressemblance égale, le script préfère celle que Plex recommande, puis la première dans l'ordre de Plex.
- **Les autres affiches ne sont jamais touchées.** Une affiche sans texte, ou dont le titre est illisible, n'est jamais choisie, faute de pouvoir la vérifier.
- Si aucune affiche ne convient, le titre est signalé pour que vous le traitiez à la main. Une affiche québécoise **verrouillée** est signalée, et n'est remplacée qu'avec `--fix-locked-quebec`.
- Les affiches passent par la même page de contrôle que les logos (avec un filtre « Posters »), et utilisent les mêmes notifications, la même liste de titres ignorés et la même annulation.

## Logs

Chaque lancement crée un dossier dans `logs/`, nommé d'après la date, l'heure et le mode : `simulation`, ou `application` pour un lancement avec `--apply`.

```
logs/
└── 2026-09-23_18h20m05_simulation/
    ├── _summary.txt       ← tableau par bibliothèque et totaux
    ├── Films.txt          ← détail titre par titre, puis un résumé
    ├── Séries TV.txt
    ├── review.html        ← avec --html
    └── undo.json          ← avec --apply
```

Chaque fichier commence par un en-tête (date, mode, règles, légende) et se termine par un résumé (durée, compteurs et titres concernés). Dans le détail, chaque titre se termine par un tag :

| Tag | Signification |
|---|---|
| `[TO ADD]` / `[ADDED]` | Pas encore de logo : un logo sera / a été posé |
| `[TO REPLACE]` / `[REPLACED]` | L'image actuelle (logo ou affiche) sera / a été remplacée (québécoise, ou `--replace`) |
| `[OK]` | Déjà le bon logo (seulement avec `--replace`) |
| `[KEPT]` | Un logo est déjà posé : laissé tel quel |
| `[LOCKED]` | Image choisie à la main (champ verrouillé) : laissée telle quelle |
| `[NONE]` | Plex ne recommande aucun logo, dans aucune langue : à choisir à la main |
| `[CHECK]` | Image québécoise, sans remplacement satisfaisant : à faire à la main |
| `[REJECTED]` | Avec `--choices` : refusé dans la page de contrôle |
| `[RECHECK]` | Avec `--choices` : l'image prévue a changé depuis la simulation |
| `[NOT REVIEWED]` | Avec `--choices` : absent du fichier de choix (nouveau depuis la simulation) |
| `[IGNORED]` | Dans les titres ignorés |
| `[ERROR]` | Erreur (le message suit) |

Un titre sans logo, complété avec la recommandation anglaise :

```
[1/3] BNA (2020)
  Current logo     : none
  Plex search      : French: none | English: found
  Recommended logo : English, 618x239 px
  Found on Plex    : candidate #3 of 7 (tmdb), same URL
  ==> [TO ADD] English logo 618x239 px
```

Un logo québécois remplacé :

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

L'OCR ne lit pas toujours parfaitement (« TRAIT » au lieu de « TRAIN »), mais la comparaison tolère ces petites erreurs.

## Problèmes courants

| Problème | Solution |
|---|---|
| `Permission denied` en lançant `./install.sh` | Lancez `bash install.sh` à la place. |
| `Python 3.8 or later is required` | Installez un Python plus récent, ou lancez `PYTHON=python3.11 ./install.sh` si plusieurs versions sont installées. |
| `No module named ...` | Lancez le script avec `.venv/bin/python`, pas `python3`. |
| L'installateur s'arrête avec `The dependencies do not load correctly` | Supprimez le dossier `.venv` et relancez `./install.sh`. Si le problème persiste, ouvrez une issue avec la sortie complète. |
| `Plex token rejected` | Votre token a changé : `.venv/bin/python configure.py --token`. |
| `Cannot connect to the Plex server` | Vérifiez l'adresse et le port. Depuis la machine, `curl http://adresse:32400/identity` doit répondre. |
| `Libraries not found` | Les noms doivent correspondre exactement à Plex : `.venv/bin/python configure.py --libraries`. |
| Un nouveau titre n'est pas traité par le hook Tautulli | Vérifiez que sa bibliothèque est dans `PLEX_LIBRARIES`, et lisez `logs/tautulli.log`. Avec Tautulli dans un conteneur, lancez `configure.py --tautulli`. |

## Bon à savoir

- Une image choisie par le script devient **verrouillée**, comme un choix manuel : Plex ne la remplace pas lors d'une actualisation, et les analyses suivantes n'y touchent plus.
- Rien n'est supprimé : l'ancien logo ou l'ancienne affiche reste disponible dans Plex (*Modifier > Logo* ou *Affiche*).
- Seules les images principales des films et séries sont traitées, pas celles des saisons ou des épisodes.
- L'installateur remplace OpenCV 5, installé avec le moteur OCR, par une version plus ancienne, parce qu'OpenCV 5 plante au chargement sur certaines machines.
- `config.env`, `ignored.json`, `logs/`, `.venv/` et `.cache-ocr.json` ne doivent pas être publiés (ils sont dans `.gitignore`) : ils contiennent votre token ou la liste de vos titres.

## Tests

Les tests sont construits à partir de cas réels (*Edge of Tomorrow*, *Bullet Train*, *The Banker*, *Captain America*, *Avatar*…). Ils couvrent la détection québécoise, les affiches, les notifications, les titres ignorés et l'assistant, et fonctionnent sans serveur Plex ni moteur OCR :

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests
```

GitHub Actions les lance à chaque push (Python 3.8 et 3.12).

## Crédits

- Inspiré de [relkai/plex-bulk-logo-updater](https://github.com/relkai/plex-bulk-logo-updater).
- Développé avec l'aide d'un assistant IA (Claude), puis relu et testé sur une vraie bibliothèque Plex.

## Licence

MIT, voir [LICENSE](LICENSE).
