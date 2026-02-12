FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better Docker layer caching)
COPY requirements.txt .

# Install CPU-only PyTorch first (before sentence-transformers)
# This prevents sentence-transformers from pulling in CUDA dependencies
RUN pip install --no-cache-dir --default-timeout=1000 \
    torch --index-url https://download.pytorch.org/whl/cpu

# Install Python dependencies with increased timeout
RUN pip install --no-cache-dir --default-timeout=1000 -r requirements.txt

# Copy application code
COPY . .

# Create directories for data and charts
RUN mkdir -p /app/data /app/charts

# Expose port
EXPOSE 8000

# Set default environment variables (can be overridden)
ENV DATA_DIR=/app/data
ENV CHART_DIR=/app/charts
ENV PYTHONUNBUFFERED=1

# Run application with production settings
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
