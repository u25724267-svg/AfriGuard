FROM python:3.11-slim

WORKDIR /app

# System deps for sentence-transformers and langdetect
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

# Create data directories
RUN mkdir -p data/seeds/legal data/seeds/custom data/processed \
    data/prompts data/candidates data/filtered data/releases

ENTRYPOINT ["afriguard"]
CMD ["--help"]
