# Stable hostname for Kaggle / Colab

OmniVoice Studio can keep one permanent public hostname even though Kaggle or Colab creates a new runtime every session.

The current publishing backend uses a remotely-managed Cloudflare Tunnel:

```text
ChatGPT / Claude Code / MCP client / Browser
                    |
        https://omnivoice.example.com
                    |
          Cloudflare named tunnel
                    |
        Kaggle / Colab runtime :8000
                    |
              OmniVoice Studio
         /ui   /api/v1   /mcp
```

Cloudflare keeps the tunnel and public-hostname mapping. An ephemeral runtime reconnects as another connector for the same named tunnel.

## One-time Cloudflare setup

1. Add/manage your domain in Cloudflare.
2. Create a remotely-managed Tunnel, for example `omnivoice-studio`.
3. Add a Published Application route:

```text
Public hostname: omnivoice.example.com
Service:         http://localhost:8000
```

4. Copy the tunnel token from **Add a replica**.
5. Store that token in Kaggle/Colab secrets or another secret manager.

Do not put the token in git, notebooks committed to git, project state, MCP configuration, or shell history.

## Runtime environment

```bash
export CLOUDFLARE_TUNNEL_TOKEN="..."
export OMNIVOICE_PUBLIC_URL="https://omnivoice.example.com"
```

Studio writes the token to a temporary permission-`0600` file and supplies it to `cloudflared` using `--token-file`. The raw token is not placed in the child-process command line.

## Authentication for public deployment

Stable tunnel support and API authentication are both implemented.

Machine/API:

```bash
export OMNIVOICE_API_TOKEN="strong-secret"
export OMNIVOICE_API_TOKEN_SCOPES="omnivoice:read,omnivoice:generate,omnivoice:queue,omnivoice:mcp"
```

Gradio UI:

```bash
export OMNIVOICE_UI_USERNAME="studio"
export OMNIVOICE_UI_PASSWORD="strong-password"
```

For an external access layer that already protects `/ui`, Studio supports an explicit trusted external UI-auth boundary. Do not use that option unless the external layer is actually trusted and enforced.

Public deployment fails closed when required auth is missing, except when an explicit insecure test override is intentionally configured.

## Install cloudflared

Install `cloudflared` explicitly in the runtime or image and keep it on `PATH`, or pass its path with `--cloudflared`.

Studio deliberately does not download a network executable automatically.

## Start Studio + tunnel

```bash
omnivoice-studio serve \
  --workspace /kaggle/working/OmniVoiceStudio \
  --host 0.0.0.0 \
  --port 8000 \
  --tunnel \
  --public-url https://omnivoice.example.com
```

Public surfaces:

```text
https://omnivoice.example.com/ui
https://omnivoice.example.com/api/v1
https://omnivoice.example.com/mcp
https://omnivoice.example.com/health
https://omnivoice.example.com/docs
```

## MCP host/origin security

`--public-url` configures MCP host/origin allowlists for the stable hostname unless explicit values already exist.

Explicit configuration:

```bash
export OMNIVOICE_MCP_ALLOWED_HOSTS="omnivoice.example.com,omnivoice.example.com:*"
export OMNIVOICE_MCP_ALLOWED_ORIGINS="https://omnivoice.example.com"
```

Only delegate DNS-rebinding protection with:

```bash
export OMNIVOICE_MCP_TRUST_PROXY=1
```

when a trusted reverse proxy is deliberately enforcing the boundary.

## Kaggle secret example

```python
import os
from kaggle_secrets import UserSecretsClient

secrets = UserSecretsClient()

os.environ["CLOUDFLARE_TUNNEL_TOKEN"] = secrets.get_secret(
    "CLOUDFLARE_TUNNEL_TOKEN"
)
os.environ["OMNIVOICE_API_TOKEN"] = secrets.get_secret(
    "OMNIVOICE_API_TOKEN"
)
os.environ["OMNIVOICE_UI_PASSWORD"] = secrets.get_secret(
    "OMNIVOICE_UI_PASSWORD"
)
os.environ["OMNIVOICE_UI_USERNAME"] = "studio"
os.environ["OMNIVOICE_PUBLIC_URL"] = "https://omnivoice.example.com"
```

Do not print secret values.

## Client configuration

MCP clients can keep:

```text
https://omnivoice.example.com/mcp
```

When one Kaggle/Colab session disappears and another reconnects the same named tunnel, the client URL does not change.

If no worker is online, the hostname remains stable but the origin is unavailable. A future optional control plane/worker registry is planned to make worker availability and reconnect behavior more explicit.

## Security checklist

Before publishing:

- [ ] API bearer token configured.
- [ ] minimum required scopes configured.
- [ ] Gradio UI protected.
- [ ] tunnel token stored as a secret.
- [ ] public URL is correct.
- [ ] MCP allowed host/origin correct.
- [ ] no secret printed in notebook/log.
- [ ] `/health` works.
- [ ] authorized API request works.
- [ ] unauthorized request is rejected.
- [ ] MCP client can connect with the expected auth boundary.

See [ai-native-mcp.md](ai-native-mcp.md) and [project-studio-roadmap.md](project-studio-roadmap.md).
