# Dockerfile for Go version
FROM golang:1.23-alpine AS builder

# Install build dependencies
RUN apk add --no-cache gcc musl-dev sqlite-dev

WORKDIR /app

# Copy go mod files first for caching
COPY go-biolab/go.mod go-biolab/go.sum ./
RUN go mod download

# Copy source
COPY go-biolab/ ./

# Build both binaries
RUN CGO_ENABLED=1 go build -o biolab ./cmd/cli
RUN CGO_ENABLED=1 go build -o biolab-server ./cmd/server

# Final stage
FROM alpine:3.20

# Install runtime dependencies
RUN apk add --no-cache sqlite-libs ca-certificates

WORKDIR /app

# Copy binaries
COPY --from=builder /app/biolab /usr/local/bin/biolab
COPY --from=builder /app/biolab-server /usr/local/bin/biolab-server

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