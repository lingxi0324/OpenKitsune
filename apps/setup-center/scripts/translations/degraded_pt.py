LANG = "pt"

EXTRA = {
 "degraded": {
  "bannerSummary": "{{count}} subsistema(s) degradado(s) — clique para reparar",
  "dialogTitle": "Subsistemas degradados",
  "dialogDescription": "O OpenKitsune detectou que alguns subsistemas não conseguem abrir seu banco de dados. Você pode isolar e recriar cada um (renomeie o arquivo .db correspondente; um banco vazio será recriado na próxima inicialização) — nenhum outro dado é tocado.",
  "loading": "Carregando…",
  "allHealthy": "Todos os subsistemas estão saudáveis.",
  "reasonLabel": "motivo",
  "sinceLabel": "desde",
  "quarantineBtn": "Isolar + recriar",
  "quarantining": "Isolando…",
  "quarantined": "Isolado",
  "errorNoToken": "Falha ao obter o token de confirmação. Recarregue a página e tente novamente.",
  "restartTitle": "Reinicialização necessária",
  "restartTauri": "O OpenKitsune interromperá o processo atual do backend; o aplicativo de desktop o reiniciará automaticamente.",
  "restartStandalone": "Pare o backend com Ctrl+C no terminal e execute `openkitsune serve` novamente.",
  "restartNow": "Reiniciar agora",
  "openMemoryRepair": "Abrir ferramenta de reparo de memória",
  "wideImpactWarning": "Isolar isso redefine agent.db — o histórico de uso de tokens e as estatísticas antigas serão apagados.",
 }
}
