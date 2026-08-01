# Dockerfile for Go version. Runtime-only: goreleaser cross-compiles the static
# (CGO_ENABLED=0) binaries and hands them to this image as build-context files —
# rebuilding from source inside Docker would be redundant and, worse, would need
# the full go-biolab/ tree, which goreleaser's docker build context doesn't include.
FROM alpine:3.20

RUN apk add --no-cache ca-certificates

WORKDIR /app

COPY biolab /usr/local/bin/biolab
COPY biolab-server /usr/local/bin/biolab-server

# Create data directory for SQLite
RUN mkdir -p /data

# Environment
ENV BIOLAB_DB_PATH=/data/biolab.db

# Expose nothing - stdio MCP server
# Run as non-root
RUN adduser -D -u 1000 biolab
USER biolab

VOLUME ["/data"]

ENTRYPOINT ["biolab-server"]
