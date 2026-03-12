# Use the official browser-use image which bundles Chromium + Playwright
FROM python:3.12-slim

# Install system dependencies required by Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium only)
RUN playwright install chromium && playwright install-deps chromium

# Copy source code
COPY src/ src/

# Assets are mounted at runtime via docker-compose volume, not baked into image
# (resume.pdf, profile.json, service_account.json contain personal data)

CMD ["python", "-m", "src.bot"]
