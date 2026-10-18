LANG = "es"

EXTRA = {
 "setup": {
  "title": "Primera visita — establece una contraseña de acceso",
  "intro": "Para proteger tus datos, establece una contraseña para el acceso Web. Una vez configurada, este equipo y los dispositivos ya iniciados pueden usarla directamente; otros dispositivos de tu red necesitarán esta contraseña para acceder.",
  "password": "Nueva contraseña",
  "passwordPlaceholder": "Al menos 8 caracteres, no solo dígitos ni solo letras",
  "confirm": "Confirmar contraseña",
  "confirmPlaceholder": "Vuelve a introducir la nueva contraseña",
  "mismatch": "Las contraseñas no coinciden",
  "submitting": "Guardando...",
  "submit": "Establecer contraseña y continuar",
  "verifyFailed": "La contraseña se guardó, pero la verificación inmediata falló. Recarga la página e inicia sesión con la contraseña que acabas de elegir.",
  "errorTooShort": "La contraseña debe tener al menos 8 caracteres",
  "errorAllDigits": "La contraseña no puede ser solo dígitos: añade letras o símbolos",
  "errorAllLetters": "La contraseña no puede ser solo letras: añade dígitos o símbolos",
  "errorAlreadySet": "Otro cliente acaba de completar la configuración. Recarga la página e inicia sesión.",
  "errorGeneric": "No se pudo guardar la contraseña. Reintenta o revisa los registros del backend.",
  "faqTitle": "Preguntas frecuentes",
  "faqWhy": "¿Por qué necesito establecer una contraseña?",
  "faqWhyAns": "Las instalaciones Headless Linux / Docker escuchan en la LAN por defecto. Sin contraseña, cualquier dispositivo de la misma red podría llamar a tu backend de IA. Establecer una contraseña mantiene fuera a los dispositivos no autorizados.",
  "faqForgot": "¿Qué pasa si olvido la contraseña?",
  "faqForgotAns": "Ejecuta `openkitsune reset-password` en el servidor (con el backend detenido o reiniciado después). La próxima visita volverá a esta página.",
  "faqLocal": "Solo lo uso desde esta máquina: ¿puedo omitir la contraseña?",
  "faqLocalAns": "Sí. Configura `API_HOST=127.0.0.1` en .env y reinicia. Las conexiones locales quedan automáticamente exentas del requisito de contraseña.",
 }
}
