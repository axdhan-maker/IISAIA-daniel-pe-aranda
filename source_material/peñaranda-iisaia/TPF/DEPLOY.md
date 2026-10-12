# Despliegue

La app va en una imagen Docker: un solo contenedor que sirve la app de
jugadores en `/` y el panel de admin en `/admin`, en un único puerto. Funciona
en cualquier servicio que corra contenedores y ofrezca un disco persistente.
Esta guía usa **Fly.io**: no hace falta instalar Docker (la imagen se construye
en sus servidores), es barato y el certificado HTTPS de tu dominio es gratis.

## Lo que hay en la imagen

```
Caddy (puerto $PORT, 8080)
 ├── /admin/...  → admin.py   (Streamlit interno, 8502)
 └── /...        → app.py     (Streamlit interno, 8501)

/data (disco persistente)
 ├── app.db                    usuarios e interacciones
 ├── admin_credentials.json    credenciales del admin (las que definís vos)
 ├── cookie_secret             firma de las sesiones (se genera solo)
 └── wahapedia/                reglas, solo si no vinieron en la imagen
```

Las reglas entran en la imagen si `data/wahapedia/core.json` existe en tu
carpeta al desplegar (corré `python -m wahapedia sync` antes). Si no, el
contenedor las descarga al disco la primera vez que arranca: tarda ~30 min y
mientras tanto la app no responde.

## Costo aproximado

Una máquina compartida de 1 GB (~US$ 5,70/mes encendida todo el mes) más 1 GB
de disco (~US$ 0,15/mes). Con `fly.toml` la máquina se apaga sola sin
visitas y se paga solo el tiempo encendida; el primer acceso tras un rato
tarda 10–20 s en despertarla. A eso se suma el dominio propio
(~US$ 10/año en cualquier registrador) y el consumo de Azure.

## 1. Preparar

1. Crear una cuenta en [fly.io](https://fly.io) (pide tarjeta).
2. Instalar la CLI (PowerShell):
   ```powershell
   iwr https://fly.io/install.ps1 -useb | iex
   ```
   y abrir una terminal nueva.
3. Ingresar: `fly auth login`.

## 2. Crear la app

Desde la carpeta del proyecto (`source_material/peñaranda-iisaia/TPF/` en el repo):

```bash
fly launch --no-deploy --copy-config
```

Toma la configuración de `fly.toml`. Si el nombre `rules-companion-40k` está
ocupado, elegí otro: la app queda en `https://<nombre>.fly.dev`. Si no creó el
disco, crealo:

```bash
fly volumes create rules_companion_data --region iad --size 1
```

## 3. Cargar los secretos

Una sola vez (se guardan cifrados en Fly, nunca en el repo). Reemplazá
`<nombre>` por el de tu app:

```bash
fly secrets set \
  AZURE_FOUNDRY_URL="https://<recurso>.services.ai.azure.com/openai/v1/responses" \
  AZURE_FOUNDRY_API_KEY="..." \
  AUTH0_DOMAIN="dev-xxxx.us.auth0.com" \
  AUTH0_CLIENT_ID="..." \
  AUTH0_CLIENT_SECRET="..." \
  PUBLIC_URL="https://<nombre>.fly.dev"
```

| Variable | Obligatoria | Qué es |
|----------|-------------|--------|
| `AZURE_FOUNDRY_URL`, `AZURE_FOUNDRY_API_KEY` | sí | endpoint y clave del modelo |
| `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET` | sí | los de tu aplicación en Auth0 |
| `PUBLIC_URL` | sí | la dirección pública, sin barra final |
| `AZURE_FOUNDRY_MODEL`, `AZURE_FOUNDRY_REASONING_EFFORT` | no | por defecto `gpt-5.6-luna` y `medium` |
| `PRICE_INPUT_PER_1M`, `PRICE_CACHED_INPUT_PER_1M`, `PRICE_OUTPUT_PER_1M` | no | precios para el panel (USD por millón de tokens) |
| `AUTH_COOKIE_SECRET` | no | si falta, se genera y se guarda en el disco |

## 4. Avisarle a Auth0 la dirección nueva

En Auth0, tu aplicación → *Settings*. Agregá la dirección pública a las que ya
tenés, separadas por coma (así sigue andando también en local):

- **Allowed Callback URLs**: `http://localhost:8501/oauth2callback, https://<nombre>.fly.dev/oauth2callback`
- **Allowed Logout URLs**: `http://localhost:8501, https://<nombre>.fly.dev`

Guardar.

## 5. Desplegar

```bash
fly deploy --remote-only --ha=false
```

`--remote-only` construye la imagen en los servidores de Fly (no hace falta
Docker local) y `--ha=false` deja una sola máquina: con SQLite en un disco no
tiene sentido una segunda (Fly crea dos por defecto). La primera vez tarda
unos minutos. Si falla con `no such host`, es la red local resolviendo mal un
nombre: volvé a correrlo. Después:

- La app: `https://<nombre>.fly.dev`
- El panel: `https://<nombre>.fly.dev/admin`

**Primer ingreso al panel:** usuario `4dmin`, contraseña `pa$$temporal`. El
panel te obliga a definir un usuario y una contraseña propios en ese momento;
las temporales dejan de valer y las nuevas quedan en el disco, así que
sobreviven a reinicios y a nuevos `fly deploy`. Hacelo apenas despliegues:
hasta entonces cualquiera que conozca las temporales puede entrar.

## 6. Dominio propio

1. Comprá un dominio en cualquier registrador (Cloudflare, Namecheap, Porkbun...).
2. Pedile el certificado a Fly:
   ```bash
   fly certs add reglas.midominio.com
   ```
   El comando muestra los registros DNS a crear (normalmente un `CNAME` de
   `reglas` hacia `<nombre>.fly.dev`). Crealos en el panel DNS del registrador.
   Si usás Cloudflare, dejá el registro en "DNS only" (nube gris).
3. Esperá a que `fly certs show reglas.midominio.com` diga que el certificado
   está emitido (minutos).
4. Actualizá la dirección pública y Auth0:
   ```bash
   fly secrets set PUBLIC_URL="https://reglas.midominio.com"
   ```
   y agregá `https://reglas.midominio.com/oauth2callback` y
   `https://reglas.midominio.com` en Auth0 como en el paso 4.

## Mantenimiento

| Para | Comando |
|------|---------|
| Ver los logs | `fly logs` |
| Publicar cambios de código o reglas nuevas | `fly deploy --remote-only --ha=false` (desde la carpeta del proyecto, con las reglas ya sincronizadas en local) |
| Reiniciar | `fly apps restart` |
| Ver los backups del disco (Fly toma uno por día) | `fly volumes snapshots list rules_companion_data` |
| Que no se apague nunca (responde al instante, cuesta el mes completo) | `min_machines_running = 1` en `fly.toml` y `fly deploy` |

## Probar la imagen en tu máquina (opcional)

Con Docker Desktop instalado, desde la carpeta del proyecto:

```bash
docker build -t rules-companion .
docker run --rm -p 8080:8080 -v rules_companion_data:/data --env-file .env \
  -e AUTH0_DOMAIN=... -e AUTH0_CLIENT_ID=... -e AUTH0_CLIENT_SECRET=... \
  -e PUBLIC_URL=http://localhost:8080 rules-companion
```

y abrir `http://localhost:8080` (agregando `http://localhost:8080/oauth2callback`
en Auth0).

## Otros servicios

La imagen no depende de Fly: necesita un disco persistente montado en `/data`,
las variables de la tabla y que el servicio le pase el puerto en `PORT` (o
exponga el 8080). Railway y Render, por ejemplo, la corren tal cual
construyéndola desde el repositorio (carpeta raíz `source_material/peñaranda-iisaia/TPF/`); en ese caso las
reglas no vienen en la imagen (no están en el repo) y se descargan al disco
en el primer arranque.
