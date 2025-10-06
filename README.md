# HTML to IMG Service

Microservicio Flask que renderiza contenido HTML a imágenes PNG/JPG utilizando **Playwright (Chromium)** y almacena los resultados en **MinIO/S3**. Ideal para generar miniaturas de newsletters, vistas previas de landing pages o assets reutilizables.

## Características
- Renderizado headless en Chromium a resolución configurable (1080x1350 por defecto).
- Compresión automática (convertido a JPEG optimizado) con Pillow.
- Subida a MinIO o cualquier servicio compatible con S3.
- Logs estructurados con `structlog` para facilitar observabilidad.
- Healthcheck (`/health`) y Docker multi-stage (imagen ligera).

## Stack tecnológico
- Python 3.11
- Flask 3
- Playwright + Chromium
- Pillow para compresión
- MinIO SDK oficial

## API
### `POST /render`
```json
{
  "html": "<html>..."  // Contenido HTML completo
}
```
**Respuesta**
```json
{
  "success": true,
  "url": "https://minio.example.com/bucket/image_xxx.jpg"
}
```
En caso de error se devuelve `{"error": "mensaje"}` con código 500.

### `GET /health`
Devuelve `{"status": "ok"}` cuando el servicio está disponible.

## Configuración
Cree un archivo `.env` basado en `.env.example`:
```
MINIO_ENDPOINT=play.min.io
MINIO_ACCESS_KEY=your-key
MINIO_SECRET_KEY=your-secret
MINIO_REGION=us-east-1
MINIO_SECURE=true
MINIO_BUCKET=html-snapshots
LOG_LEVEL=INFO
```

## Ejecución local
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py  # Flask se levanta en el puerto 3323 por defecto
```

## Docker
```bash
docker build -t htmltoimg-service .
docker run --rm -p 3323:3323 \
  -e MINIO_ENDPOINT=... \
  -e MINIO_ACCESS_KEY=... \
  -e MINIO_SECRET_KEY=... \
  -e MINIO_BUCKET=... \
  htmltoimg-service
```

## Buenas prácticas
- Asegúrese de que el bucket exista y tenga políticas de acceso apropiadas.
- Use HTTPS (`MINIO_SECURE=true`) cuando el endpoint lo permita.
- Limite el tamaño del HTML recibido (puede agregarse validación previa).

## Roadmap
- Parámetros opcionales en el request (`width`, `height`, `format`).
- Cache local de resultados (e.g. Redis) para HTML repetido.
- Firma de URLs con expiración segura.

## Licencia
Proyecto bajo licencia **MIT**.
