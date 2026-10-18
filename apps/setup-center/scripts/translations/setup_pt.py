LANG = "pt"

EXTRA = {
 "setup": {
  "title": "Primeira visita — defina uma senha de acesso",
  "intro": "Para proteger seus dados, defina uma senha para o acesso Web. Depois de definida, este dispositivo e os dispositivos já conectados permanecem conectados; outros dispositivos da sua rede precisarão desta senha para acessar a API.",
  "password": "Nova senha",
  "passwordPlaceholder": "Pelo menos 8 caracteres, nem só dígitos nem só letras",
  "confirm": "Confirmar senha",
  "confirmPlaceholder": "Digite novamente a nova senha",
  "mismatch": "As senhas não coincidem",
  "submitting": "Salvando...",
  "submit": "Definir senha e continuar",
  "verifyFailed": "A senha foi salva, mas a verificação imediata falhou. Recarregue a página e entre com a senha que acabou de escolher.",
  "errorTooShort": "A senha deve ter pelo menos 8 caracteres",
  "errorAllDigits": "A senha não pode ser apenas dígitos — adicione letras ou símbolos",
  "errorAllLetters": "A senha não pode ser apenas letras — adicione dígitos ou símbolos",
  "errorAlreadySet": "Outro cliente acabou de concluir a configuração. Recarregue a página e entre.",
  "errorGeneric": "Não foi possível salvar a senha. Tente novamente ou verifique os logs do backend.",
  "faqTitle": "Perguntas frequentes",
  "faqWhy": "Por que preciso definir uma senha?",
  "faqWhyAns": "As instalações Headless Linux / Docker escutam na LAN por padrão. Sem senha, qualquer dispositivo na mesma rede poderia chamar seu backend de IA. Definir uma senha mantém os dispositivos não autorizados de fora.",
  "faqForgot": "E se eu esquecer a senha?",
  "faqForgotAns": "Execute `openkitsune reset-password` no servidor (com o backend parado ou reiniciado depois). A próxima visita voltará a esta página.",
  "faqLocal": "Só uso nesta máquina — posso dispensar a senha?",
  "faqLocalAns": "Sim. Defina `API_HOST=127.0.0.1` no .env e reinicie. As conexões locais ficam automaticamente isentas da exigência de senha.",
 }
}
