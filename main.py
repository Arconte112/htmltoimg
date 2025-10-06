import os
import tempfile
import logging
import structlog
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
from minio import Minio
from minio.error import S3Error
import uuid
from PIL import Image, ImageOps

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
            # Log available browsers for debugging
            logger.info("Available browsers", 
                       chromium_executable=p.chromium.executable_path if hasattr(p.chromium, 'executable_path') else "unknown")
            
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
            )
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
        logger.error("Failed to render HTML to image", error=str(e), html_file=html_file, 
                    error_type=type(e).__name__)
        raise
    finally:
        if os.path.exists(html_file):
            os.remove(html_file)
            logger.debug("Cleaned up temporary HTML file", html_file=html_file)
        
# Configuración de MinIO
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_REGION = os.getenv("MINIO_REGION", "us-east-1")
MINIO_SECURE = os.getenv("MINIO_SECURE", "true").lower() == "true"
BUCKET_NAME = os.getenv("MINIO_BUCKET")

MINIO_CLIENT = None
if MINIO_ENDPOINT and MINIO_ACCESS_KEY and MINIO_SECRET_KEY and BUCKET_NAME:
    MINIO_CLIENT = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        region=MINIO_REGION,
        secure=MINIO_SECURE,
    )
else:
    logger.warning("MinIO credentials are not fully configured; uploads will be disabled.")

def compress_image(image_path, quality=85, max_width=1920):
    """Compress image to reduce file size while maintaining quality"""
    logger.info("Starting image compression", image_path=image_path, quality=quality, max_width=max_width)
    
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary (for PNG with transparency)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            
            # Resize if image is too wide
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                logger.info("Image resized", original_width=img.width, new_width=max_width, new_height=new_height)
            
            # Create compressed output path
            compressed_path = image_path.replace('.png', '_compressed.jpg')
            
            # Save with compression
            img.save(compressed_path, 'JPEG', quality=quality, optimize=True)
            
            # Get file sizes for logging
            original_size = os.path.getsize(image_path)
            compressed_size = os.path.getsize(compressed_path)
            compression_ratio = (1 - compressed_size/original_size) * 100
            
            logger.info("Image compression completed", 
                       original_size=original_size, 
                       compressed_size=compressed_size,
                       compression_ratio=f"{compression_ratio:.1f}%",
                       compressed_path=compressed_path)
            
            return compressed_path
            
    except Exception as e:
        logger.error("Image compression failed", error=str(e), image_path=image_path)
        return image_path  # Return original path if compression fails

def upload_to_minio(image_path):
    """Upload image to MinIO and return the URL"""
    if MINIO_CLIENT is None or not BUCKET_NAME:
        raise RuntimeError("MinIO is not configured. Set MINIO_* environment variables to enable uploads.")

    # Compress image before upload
    compressed_path = compress_image(image_path)
    
    # Determine file extension and content type based on compressed image
    if compressed_path.endswith('.jpg'):
        filename = f"image_{uuid.uuid4()}.jpg"
        content_type = "image/jpeg"
    else:
        filename = f"image_{uuid.uuid4()}.png"
        content_type = "image/png"
    
    logger.info("Starting MinIO upload", filename=filename, image_path=compressed_path)
    
    try:
        # Upload compressed file
        MINIO_CLIENT.fput_object(
            BUCKET_NAME,
            filename,
            compressed_path,
            content_type=content_type
        )
        
        # Return the public URL
        if MINIO_ENDPOINT.startswith("http://") or MINIO_ENDPOINT.startswith("https://"):
            base_url = MINIO_ENDPOINT
        else:
            scheme = "https" if MINIO_SECURE else "http"
            base_url = f"{scheme}://{MINIO_ENDPOINT}"

        url = f"{base_url.rstrip('/')}/{BUCKET_NAME}/{filename}"
        logger.info("MinIO upload successful", filename=filename, url=url)
        
        # Clean up compressed file if it's different from original
        if compressed_path != image_path and os.path.exists(compressed_path):
            os.remove(compressed_path)
            logger.debug("Cleaned up compressed file", compressed_path=compressed_path)
            
        return url
    
    except S3Error as e:
        logger.error("MinIO upload failed", filename=filename, error=str(e))
        # Clean up compressed file on error
        if compressed_path != image_path and os.path.exists(compressed_path):
            os.remove(compressed_path)
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
    port = int(os.getenv("PORT", 3323))
    logger.info("Starting HTML to Image service", 
                host="0.0.0.0", port=port, bucket=BUCKET_NAME)
    app.run(host="0.0.0.0", port=port, debug=False)
