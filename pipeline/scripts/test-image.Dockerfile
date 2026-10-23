# The pipeline's test image: uv's Python image plus the OpenMP runtime LightGBM needs.
# GitHub's runners have libgomp1 already; the slim image doesn't.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
