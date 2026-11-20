# The hosted TaskFactory app: the form, the sample site and the generator.
# Pinned base image digest: sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    MPLCONFIGDIR=/tmp/mpl \
    TMPDIR=/tmp \
    TESSERACT_CMD=/usr/bin/tesseract

# Tesseract runs the OCR check; libglib2.0 and the DejaVu fonts are needed by
# OpenCV and matplotlib.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libglib2.0-0 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.12.5

WORKDIR /app

# Dependencies first, so a source change does not reinstall them. The project
# itself needs src/ at install time, so it is installed after the copy below.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY configs/ ./configs/
COPY site/ ./site/
COPY README.md ./
RUN uv sync --frozen --no-dev

EXPOSE 3000
CMD ["sh", "-c", "tf serve --host 0.0.0.0 --port ${PORT:-3000} --allow-remote"]
