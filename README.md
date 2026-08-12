# Generador de videos de mapas satelitales - Canal 79

Descarga las imágenes satelitales del Servicio Meteorológico Nacional (SMN) y arma
un video de **30 segundos exactos a 30 fps** con los dos satélites (ARG y CEN) en
un único archivo, listo para reproducir en vMix.

## Cómo funciona

```
API del SMN (lista de archivos)  ->  descarga de imágenes  ->  buffer en disco
                                                                    |
                            video final  <-  FFmpeg  <-  composición sobre el fondo
```

1. **Autenticación**: se pide un token al SMN con usuario y contraseña
   (`POST /v1/api-token/auth`). Si eso falla, se usa el servidor de tokens de
   Canal 79 como respaldo.
2. **Listado**: la API devuelve los nombres de archivo de cada grupo
   (`TOP_C13_ARG_ALTA` y `TOP_C13_CEN_ALTA`). La API **nunca** devuelve la imagen
   en sí, solo el nombre, así que los nombres nunca se inventan a mano.
3. **Descarga**: cada archivo se baja de `https://estaticos.smn.gob.ar/vmsr/satelite/`.
   Primero por HTTP directo; si Cloudflare bloquea, se reintenta con un navegador
   real (Playwright). Siempre se guardan los bytes originales del JPG.
4. **Buffer**: se mantienen las últimas 24 imágenes de cada satélite.
5. **Video**: cada imagen se compone centrada sobre `src/resources/background.jpg`
   y FFmpeg codifica todo en una sola pasada.

## Instalación

Requisitos: **Python 3.10+** y **FFmpeg** en el PATH.

```
install.bat
```

Crea el entorno virtual `.venv`, instala las dependencias e instala el navegador
de respaldo. Para verificar que quedó todo bien:

```
run.bat --check
```

## Uso

| Comando | Qué hace |
|---------|----------|
| `run.bat` | Arranca el servicio: genera el video y lo repite en los minutos configurados |
| `run.bat --once` | Genera un solo video y termina |
| `run.bat --no-download` | Usa las imágenes que ya están en el buffer |
| `run.bat --clear-buffer` | Vacía el buffer antes de empezar |
| `run.bat --check` | Valida la configuración y el entorno |

El video se escribe primero en un archivo temporal y recién al final se renombra
sobre el definitivo, así vMix nunca lee un archivo a medio escribir.

## Duración exacta

El video **siempre** dura `fps x durationSeconds` cuadros: 30 x 30 = **900 cuadros**.

Para llegar a esa cantidad se arma primero la secuencia lógica, igual que en la
versión original del programa:

- las 24 imágenes de cada satélite en orden cronológico,
- más la última imagen repetida 5 veces (`lastImageRepeats`),
- todo eso repetido `sequenceRepeats` veces, satélite por satélite.

Con los valores por defecto son `2 satélites x 1 pasada x (24 + 5) = 58` imágenes.
Los 900 cuadros se reparten entre esas 58 posiciones con aritmética de enteros
(cada una recibe 15 o 16 cuadros), de modo que la suma da exactamente 900 y no se
acumulan errores de redondeo. FFmpeg recibe esos 900 cuadros y los codifica a
30 fps constantes.

## Configuración (`configuration.json`)

### video

| Clave | Descripción |
|-------|-------------|
| `width`, `height` | Resolución de salida (deben ser pares) |
| `fps` | Cuadros por segundo del archivo final |
| `durationSeconds` | Duración exacta en segundos |
| `codec` | Códec de video (`libx264` recomendado para vMix) |
| `bitrate` | Calidad: más bitrate, más calidad y más peso |
| `preset` | Velocidad de codificación de x264 (`ultrafast` a `veryslow`) |
| `pixelFormat` | Formato de color (`yuv420p` para máxima compatibilidad) |
| `extension` | Extensión del archivo final |
| `threads` | Núcleos para FFmpeg (`0` = automático) |
| `background` | Imagen de fondo del video |
| `mapResizeRatio` | Qué porcentaje del cuadro ocupa el mapa |
| `mapFitMode` | `contain`: ajusta el mapa al cuadro y después aplica el ratio. `ratio`: escala el mapa por el ratio sobre su tamaño original |

### output

| Clave | Descripción |
|-------|-------------|
| `path` | Carpeta donde se guarda el video |
| `fileName` | Nombre del archivo, sin extensión |

### sequence

| Clave | Descripción |
|-------|-------------|
| `bufferSize` | Imágenes guardadas y mostradas por satélite |
| `sequenceRepeats` | Veces que se repite la secuencia de cada satélite |
| `lastImageRepeats` | Veces que se sostiene la última imagen de cada pasada |

### satellites

Lista ordenada de satélites; el orden es el que se ve en el video.
`name` es el nombre de la carpeta del buffer y `groupId` el identificador del SMN.

### smn

| Clave | Descripción |
|-------|-------------|
| `apiBaseUrl` | Base de la API del SMN |
| `staticBaseUrl` | Base del host donde viven las imágenes |
| `username`, `password` | Credenciales del SMN (se pueden reemplazar con las variables de entorno `SMN_USERNAME` y `SMN_PASSWORD`) |
| `tokenServerUrl` | Servidor de tokens de Canal 79, usado como respaldo |

### download

| Clave | Descripción |
|-------|-------------|
| `bufferDir` | Carpeta del buffer de imágenes |
| `requestTimeoutSeconds` | Tiempo máximo de espera por pedido |
| `maxRetries` | Intentos por imagen |
| `delayBetweenDownloadsSeconds` | Pausa entre descargas |
| `useBrowserFallback` | Usar el navegador cuando Cloudflare bloquea |
| `developerMode` | `true` muestra el navegador; `false` lo deja oculto |

### schedule

| Clave | Descripción |
|-------|-------------|
| `runOnStart` | Generar un video apenas arranca |
| `cronMinutes` | Minutos de cada hora en los que se regenera el video |

### logging

| Clave | Descripción |
|-------|-------------|
| `file` | Archivo de log (rota solo al llegar a 5 MB) |
| `level` | `DEBUG`, `INFO`, `WARNING` o `ERROR` |
| `emailOnError` | Enviar mail ante errores |
| `emailsFile` | Archivo con la lista de destinatarios |
| `smtpHost`, `smtpPort` | Servidor de correo saliente |
| `smtpUser`, `smtpPassword` | Credenciales del correo (mejor usar las variables de entorno `SMN_SMTP_USER` y `SMN_SMTP_PASSWORD`) |

## Problemas frecuentes

**El video no se genera y el log dice que no se pudo descargar ninguna imagen.**
Cloudflare está bloqueando la conexión. Verificá que Playwright esté instalado
(`install.bat`) y que `useBrowserFallback` esté en `true`.

**FFmpeg no se encuentra.** Instalalo y agregalo al PATH; `run.bat --check` lo avisa.

**El mapa se ve muy chico o muy grande.** Ajustá `mapResizeRatio`. Si el tamaño de
las imágenes del SMN cambia, `mapFitMode: "contain"` se adapta solo.
