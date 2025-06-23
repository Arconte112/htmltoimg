import os
import tempfile
import logging
import structlog
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
from minio import Minio
from minio.error import S3Error
import uuid

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="ISO"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level), format="%(message)s")

logger = structlog.get_logger()

app = Flask(__name__)
# app.debug = True  # Disabled to prevent Playwright conflicts

def render_html_to_image(html_content: str, output_path: str):
    logger.info("Starting HTML to image rendering", output_path=output_path)
    
    with tempfile.NamedTemporaryFile("w+", suffix=".html", delete=False, encoding="utf-8") as tmp_html:
        tmp_html.write(html_content)
        tmp_html.flush()
        html_file = tmp_html.name

    try:
        logger.info("Launching browser", html_file=html_file)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1080, "height": 1350},
                device_scale_factor=2
            )
            page = context.new_page()
            page.goto(f"file://{html_file}", wait_until="networkidle")
            page.wait_for_timeout(2000)  # Wait 2 seconds for images to load
            page.screenshot(path=output_path, full_page=False)
            browser.close()
            logger.info("Screenshot completed successfully", output_path=output_path)
    except Exception as e:
        logger.error("Failed to render HTML to image", error=str(e), html_file=html_file)
        raise
    finally:
        if os.path.exists(html_file):
            os.remove(html_file)
            logger.debug("Cleaned up temporary HTML file", html_file=html_file)
        
# Configuración de MinIO
MINIO_CLIENT = Minio(
    "minio-nwo004cws40gwwkcs8008oog.automatadr.com",
    access_key="I9BKXRAMi9Pui8XmEyhm",
    secret_key="7ATtXmegPRlQjyFMnK49b0My65jWzbJNxSuGnoR2",
    region="us-east-1",
    secure=True
)
BUCKET_NAME = "antiguaordenimagenes"

def upload_to_minio(image_path):
    """Upload image to MinIO and return the URL"""
    filename = f"image_{uuid.uuid4()}.png"
    logger.info("Starting MinIO upload", filename=filename, image_path=image_path)
    
    try:
        # Upload file
        MINIO_CLIENT.fput_object(
            BUCKET_NAME,
            filename,
            image_path,
            content_type="image/png"
        )
        
        # Return the public URL
        url = f"https://minio-nwo004cws40gwwkcs8008oog.automatadr.com/{BUCKET_NAME}/{filename}"
        logger.info("MinIO upload successful", filename=filename, url=url)
        return url
    
    except S3Error as e:
        logger.error("MinIO upload failed", filename=filename, error=str(e))
        raise Exception(f"MinIO upload failed: {e}")

@app.route("/render", methods=["POST"])
def render():
    request_id = str(uuid.uuid4())[:8]
    logger.info("Received render request", request_id=request_id, 
                content_type=request.content_type)
    
    if not request.is_json:
        logger.warning("Invalid request - not JSON", request_id=request_id)
        return jsonify({"error": "Se requiere JSON con clave 'html'"}), 400
    
    data = request.get_json()
    if "html" not in data:
        logger.warning("Invalid request - missing html key", request_id=request_id)
        return jsonify({"error": "Falta la clave 'html' en el JSON"}), 400

    html_content = data["html"]
    html_length = len(html_content)
    output_path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    
    logger.info("Processing render request", request_id=request_id, 
                html_length=html_length, output_path=output_path)

    try:
        render_html_to_image(html_content, output_path)
        image_url = upload_to_minio(output_path)
        logger.info("Render request completed successfully", request_id=request_id, 
                    image_url=image_url)
        return jsonify({
            "success": True,
            "url": image_url
        })
    except Exception as e:
        logger.error("Render request failed", request_id=request_id, error=str(e))
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)
            logger.debug("Cleaned up output file", request_id=request_id, 
                        output_path=output_path)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "service": "htmltoimg"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8002))
    logger.info("Starting HTML to Image service", 
                host="0.0.0.0", port=port, bucket=BUCKET_NAME)
    app.run(host="0.0.0.0", port=port)
