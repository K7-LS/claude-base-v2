---
name: reference_officecli
description: OfficeCLI is a cold Foundation-managed reference for Office documents.
metadata:
  node_type: memory
---

# OfficeCLI

OfficeCLI is a shared Foundation-managed tool for Office documents. Keep this
base limited to this cold reference: it does not ship or activate OfficeCLI.

Load this reference only when the task explicitly concerns OfficeCLI or a
Foundation-managed Office-document workflow.

## Managed boundary

- Obtain the OfficeCLI binary, version and hash only from an accepted
  Foundation release.
- Let the Foundation installer own any binary placement and invocation.
- Do not add an OfficeCLI skill, plugin, MCP server, PATH entry or local
  binary installation to this base.
- Treat a missing accepted Foundation release as unavailable; do not substitute
  a direct download or an ad-hoc installation.
