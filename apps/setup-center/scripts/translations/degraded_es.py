LANG = "es"

EXTRA = {
 "degraded": {
  "bannerSummary": "{{count}} subsistema(s) degradados — haz clic para reparar",
  "dialogTitle": "Subsistemas degradados",
  "dialogDescription": "OpenKitsune detectó que algunos subsistemas no pueden abrir su base de datos. Puedes aislar y reconstruir cada uno (renombra el archivo .db correspondiente; se recreará vacío en el próximo arranque) — no se toca ningún otro dato.",
  "loading": "Cargando…",
  "allHealthy": "Todos los subsistemas están saludables.",
  "reasonLabel": "motivo",
  "sinceLabel": "desde",
  "quarantineBtn": "Aislar + recrear",
  "quarantining": "Aislando…",
  "quarantined": "Aislado",
  "errorNoToken": "No se pudo obtener el token de confirmación. Recarga la página e inténtalo de nuevo.",
  "restartTitle": "Reinicio requerido",
  "restartTauri": "OpenKitsune detendrá el proceso backend actual; la app de escritorio lo reiniciará automáticamente.",
  "restartStandalone": "Detén el backend con Ctrl+C en tu terminal y vuelve a ejecutar `openkitsune serve`.",
  "restartNow": "Reiniciar ahora",
  "openMemoryRepair": "Abrir herramienta de reparación de memoria",
  "wideImpactWarning": "Aislar esto restablece agent.db: se borrará el historial de uso de tokens y las estadísticas antiguas.",
 }
}
