#!/usr/bin/env bash
set -euo pipefail

# goreleaser post-build hook: signs one built binary via cosign keyless signing,
# using GitHub Actions' OIDC token (release job already grants id-token: write).
# Produces <binary>.sig and <binary>.pem alongside the binary itself.

artifact="$1"

cosign sign-blob \
  --yes \
  --output-signature "${artifact}.sig" \
  --output-certificate "${artifact}.pem" \
  "$artifact"
