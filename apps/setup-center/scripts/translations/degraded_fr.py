LANG = "fr"

EXTRA = {
 "degraded": {
  "bannerSummary": "{{count}} sous-système(s) dégradé(s) — cliquez pour réparer",
  "dialogTitle": "Sous-systèmes dégradés",
  "dialogDescription": "OpenKitsune a détecté que certains sous-systèmes ne peuvent pas ouvrir leur base de données. Vous pouvez isoler et recréer chacun (renommez le fichier .db correspondant ; une base vide sera recréée au prochain démarrage) — aucune autre donnée n'est touchée.",
  "loading": "Chargement…",
  "allHealthy": "Tous les sous-systèmes sont sains.",
  "reasonLabel": "motif",
  "sinceLabel": "depuis",
  "quarantineBtn": "Isoler + recréer",
  "quarantining": "Isolement…",
  "quarantined": "Isolé",
  "errorNoToken": "Échec de l'obtention du jeton de confirmation. Rechargez la page et réessayez.",
  "restartTitle": "Redémarrage requis",
  "restartTauri": "OpenKitsune arrêtera le processus backend actuel ; l'application de bureau le relancera automatiquement.",
  "restartStandalone": "Arrêtez le backend avec Ctrl+C dans votre terminal et relancez `openkitsune serve`.",
  "restartNow": "Redémarrer maintenant",
  "openMemoryRepair": "Ouvrir l'outil de réparation de mémoire",
  "wideImpactWarning": "L'isolement réinitialise agent.db — l'historique d'utilisation des tokens et les anciennes statistiques seront effacés.",
 }
}
