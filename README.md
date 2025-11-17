# HTML to Image API with Catbox Upload

This API service converts HTML content to an image and uploads it to catbox.moe, returning the URL of the uploaded image.

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Install Playwright browsers:
   ```
   python -m playwright install chromium
   ```

3. Run the server:
   ```
   python main.py
   ```

The server will start on port 8000.

## API Usage

### Endpoint: `/render`

**Method:** POST

**Content-Type:** application/json

**Request Body:**
```json
{
  "html": "<html>Your HTML content here</html>"
}
```

**Response:**
```json
{
  "url": "https://catbox.moe/c/example.png"
}
```

**Error Response:**
```json
{
  "error": "Error message"
}
```

## Example

```bash
curl -X POST http://localhost:8000/render \
  -H "Content-Type: application/json" \
  -d '{"html":"<html><body><h1>Hello World</h1></body></html>"}'
```

Response:
```json
{
  "url": "https://catbox.moe/c/abcdef.png"
}
