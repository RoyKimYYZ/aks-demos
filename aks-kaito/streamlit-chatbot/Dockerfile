# syntax=docker/dockerfile:1

# Lightweight Python image with slim OS libraries for smaller image size and attack surface.
FROM python:3.13-slim
# These settings help make Python apps behave better in containers:
#
# - Disabling .pyc bytecode files:
#   In Docker images, writing compiled Python cache files (like __pycache__/*.pyc)
#   adds unnecessary disk writes and extra files that don’t help at runtime.
#   Keeping the image “cleaner” can make builds more reproducible and reduce clutter.
#
# - Unbuffering stdout/stderr:
#   By default, Python may buffer (delay) output, so logs appear late or in batches.
#   For containers, you usually want logs immediately so you can debug and monitor
#   with `docker logs`, Kubernetes logs, etc. Unbuffered output makes your app’s
#   print statements and error messages show up right away.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set working directory inside the container to /app (where we’ll copy our code)
WORKDIR /app

# System deps (certs, curl for uv install)
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

# Install uv (the Astral Universal Virtualenv tool)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Copy project files
COPY pyproject.toml README.md ./
COPY .streamlit/ ./.streamlit/
COPY app.py catalog.py kaito_openai_compat.py kaito_catalog.yaml ./

# Install runtime deps (and dev extra, since it also includes type stubs; harmless at runtime)
# Note: this does not require the project to be an importable package; it just installs deps.
RUN uv pip install --system "streamlit>=1.31" "requests>=2.31" "PyYAML>=6.0.1" \
  && uv pip install --system ruff mypy types-PyYAML types-requests \
  && python -m compileall /app

# Expose Streamlit default port 8501 so it can be mapped by Docker/Kubernetes
EXPOSE 8501

# BASE_URL_PATH is useful when hosting behind an ingress path prefix.
# If empty/unset, Streamlit serves at /.
ENV BASE_URL_PATH=""

# Command to run the app with Streamlit, binding to all interfaces 
CMD ["/bin/sh", "-lc", "streamlit run /app/app.py --server.address=0.0.0.0 --server.port=8501 ${BASE_URL_PATH:+--server.baseUrlPath=$BASE_URL_PATH}"]
