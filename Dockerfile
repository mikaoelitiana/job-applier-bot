FROM python:3.12-slim

# Install system dependencies required by Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium only)
RUN python -m playwright install --with-deps chromium

# Copy source code
COPY src/ src/

# Assets are mounted at runtime via docker-compose volume, not baked into image
# (resume.pdf, profile.json, service_account.json contain personal data)

CMD ["python", "-m", "src.bot"]
