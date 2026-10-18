LANG = "fr"

EXTRA = {
 "setup": {
  "title": "Première visite — définissez un mot de passe d'accès",
  "intro": "Pour protéger vos données, définissez un mot de passe pour l'accès Web. Une fois défini, cet appareil et les appareils déjà connectés restent connectés ; les autres appareils de votre réseau devront saisir ce mot de passe pour accéder à l'API.",
  "password": "Nouveau mot de passe",
  "passwordPlaceholder": "Au moins 8 caractères, ni uniquement des chiffres ni uniquement des lettres",
  "confirm": "Confirmer le mot de passe",
  "confirmPlaceholder": "Saisissez à nouveau le nouveau mot de passe",
  "mismatch": "Les mots de passe ne correspondent pas",
  "submitting": "Enregistrement...",
  "submit": "Définir le mot de passe et continuer",
  "verifyFailed": "Le mot de passe a été enregistré, mais la vérification immédiate a échoué. Rechargez la page et connectez-vous avec le mot de passe que vous venez de choisir.",
  "errorTooShort": "Le mot de passe doit contenir au moins 8 caractères",
  "errorAllDigits": "Le mot de passe ne peut pas être uniquement des chiffres — ajoutez des lettres ou des symboles",
  "errorAllLetters": "Le mot de passe ne peut pas être uniquement des lettres — ajoutez des chiffres ou des symboles",
  "errorAlreadySet": "Un autre client vient de terminer la configuration. Rechargez la page et connectez-vous.",
  "errorGeneric": "Impossible d'enregistrer le mot de passe. Réessayez ou vérifiez les journaux du backend.",
  "faqTitle": "Questions fréquentes",
  "faqWhy": "Pourquoi dois-je définir un mot de passe ?",
  "faqWhyAns": "Les installations Headless Linux / Docker écoutent sur le réseau local par défaut. Sans mot de passe, n'importe quel appareil du même réseau pourrait appeler votre backend IA. Définir un mot de passe tient les appareils non autorisés à l'écart.",
  "faqForgot": "Que faire si j'oublie le mot de passe ?",
  "faqForgotAns": "Exécutez `openkitsune reset-password` sur le serveur (avec le backend arrêté ou redémarré ensuite). La prochaine visite vous ramènera à cette page.",
  "faqLocal": "Je l'utilise uniquement depuis cette machine : puis-je ignorer le mot de passe ?",
  "faqLocalAns": "Oui. Définissez `API_HOST=127.0.0.1` dans .env et redémarrez. Les connexions locales sont automatiquement exemptées de l'exigence de mot de passe.",
 }
}
