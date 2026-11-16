# Arbitraje y side income

Repositorio personal con bots que corren en GitHub Actions. No ejecutan operaciones: miden, registran y avisan por mail.

## Estructura

| Carpeta | Qué hace | Workflow | Estado |
|---|---|---|---|
| `viajes/` | Escáner de arbitraje "con viaje" (comprar en A, transferir, vender en B): Buda vs CryptoMKT (referencia) y Buda vs exchanges extranjeros vía USDT. Historial en `viajes/data/viajes.csv`. | `viajes.yml` (cada 15 min) | Activo |
| `nichos/` | Análisis de exports de eRank para elegir productos de Etsy. Se sube un CSV a `nichos/erank/` y llega el ranking por mail. | `erank.yml` (al subir archivos) | Activo |
| `nichos/nichos.py` | Investigación vía API de Etsy | `nichos.yml` | Pausado (API no aprobada) |
| `backtest/` | Backtests de trading (momentum cripto y tendencia BTC). Ninguna estrategia pasó los criterios. | `backtest.yml`, `backtest_btc.yml` (manuales) | Archivo |
| — | Recordatorio con el CSV de viajes adjunto | `recordatorio.yml` (27-nov-2026) | Programado |

## Configuración

Secrets del repo (Settings → Secrets and variables → Actions):
- `GMAIL_USER`, `GMAIL_APP_PASSWORD` (contraseña de aplicación de Google), `MAIL_TO` (opcional)
- `ETSY_KEYSTRING`, `ETSY_SHARED_SECRET` (solo para `nichos.yml`)

Los parámetros del escáner (umbrales, comisiones, tiempos de traslado) están en `viajes/config_viajes.py`.
Costos medidos en prueba real (nov 2026): margen de compra en CryptoMKT ~2,3% sobre su precio de referencia;
Buda 0,5% al vender; retiros a banco $0 en ambas; traslado de BCH ~30 min normal (85 min con red lenta).

## Cómo leer las alertas

- **🚚 Viaje … neto X%**: precios ejecutables y costos incluidos.
- **👀 Revisar a mano … neto estimado X%**: usa el precio de referencia de CryptoMKT; confirma el precio real en la app antes de mover plata.
