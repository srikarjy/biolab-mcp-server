#!/usr/bin/env bash
set -euo pipefail

# goreleaser post-build hook: signs one built binary via cosign keyless signing,
# using GitHub Actions' OIDC token (release job already grants id-token: write).
# Produces <binary>.bundle (signature + certificate + Rekor entry) alongside the binary.

artifact="$1"

cosign sign-blob \
  --yes \
  --bundle "${artifact}.bundle" \
  "$artifact"
