# Escáner de arbitraje (USDT/CLP y PAXG)

Registra cada 15 min el spread neto de:
1. **USDT/CLP en Buda** vs dólar de mercado (Yahoo `CLP=X`, respaldo: dólar observado).
2. **PAXG** vs oro (futuro COMEX `GC=F`) y entre Kraken y Coinbase.

No ejecuta operaciones. Guarda todo en `data/spreads.csv` y alerta por mail (Gmail)
cuando el spread neto supera el umbral durante 2 lecturas seguidas.

## Puesta en marcha
1. Sube estos archivos a un repo nuevo.
2. Gmail: activa la verificación en 2 pasos en tu cuenta de Google y crea una
   contraseña de aplicación (Cuenta de Google → Seguridad → Contraseñas de
   aplicaciones). Son 16 caracteres; no uses tu clave normal.
3. En el repo: Settings → Secrets and variables → Actions → agrega
   `GMAIL_USER` (tu correo) y `GMAIL_APP_PASSWORD`. Opcional: `MAIL_TO` si
   quieres recibir las alertas en otra dirección.
4. Pestaña Actions → "Escáner de arbitraje" → Run workflow para probar.
   La tabla de resultados aparece en el resumen de cada ejecución.

## Ajustes
Umbral, comisiones y exchanges están en `config.py`. Las comisiones son
aproximadas: ajústalas a tu cuenta real antes de interpretar el spread neto.
