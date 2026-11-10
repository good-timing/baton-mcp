FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
# Dependencies before the source, so a source-only change keeps this layer.
# `--locked` fails the build when uv.lock and pyproject.toml disagree.
RUN uv export --locked --no-emit-project --no-hashes -o /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt
COPY README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

FROM python:3.11-slim

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# A numeric id, so a runtime that requires non-root (Kubernetes runAsNonRoot)
# can verify it.
RUN useradd --system --create-home --uid 10001 app
USER 10001

ENV PORT=8080
# Cloud Run sends any request to any instance, and a deploy replaces them all.
ENV FASTMCP_STATELESS_HTTP=true
# Otherwise every cold start asks PyPI for a newer fastmcp.
ENV FASTMCP_CHECK_FOR_UPDATES=off
EXPOSE 8080

CMD ["baton-mcp"]
