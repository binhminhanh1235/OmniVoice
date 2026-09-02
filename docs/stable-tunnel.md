# Stable hostname for Kaggle / Colab

OmniVoice Studio can keep one permanent public hostname even though Kaggle or Colab creates a new runtime every session.

The initial publishing backend uses a remotely-managed Cloudflare Tunnel:

```text
ChatGPT / Claude Code / Antigravity / Browser
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

Cloudflare stores the tunnel and public hostname mapping. The ephemeral runtime only reconnects as a new connector replica using the same tunnel token.

## One-time Cloudflare setup

1. Add/manage your domain in Cloudflare.
2. In Cloudflare Dashboard, create a remotely-managed Tunnel, for example `omnivoice-studio`.
3. Add a Published Application route:

```text
Public hostname: omnivoice.example.com
Service:         http://localhost:8000
```

4. Copy the tunnel token from **Add a replica**.
5. Store that token as a private Kaggle/Colab secret. Never place it in the notebook, git repository, project files, or MCP config.

Once the route exists, DNS and hostname stay stable even when the Kaggle connector goes offline and later reconnects.

## Runtime secrets

Studio reads the tunnel token from:

```text
CLOUDFLARE_TUNNEL_TOKEN
```

The public URL can be supplied by CLI or environment:

```text
OMNIVOICE_PUBLIC_URL=https://omnivoice.example.com
```

The token is written to a temporary permission-`0600` file and supplied to `cloudflared` with `--token-file`. The raw token is not placed in the child-process command line.

## Install cloudflared in an ephemeral notebook

Install the current Cloudflare binary in a setup cell or image before launching Studio. For example on Linux amd64, place the `cloudflared` executable somewhere on `PATH` and make it executable.

Studio deliberately does not download network executables by itself. Keeping installation separate makes the trust boundary visible and easier to audit.

## Start Studio + named tunnel

```bash
omnivoice-studio serve \
  --workspace /kaggle/working/OmniVoiceStudio \
  --host 0.0.0.0 \
  --port 8000 \
  --tunnel \
  --public-url https://omnivoice.example.com
```

The same process exposes:

```text
https://omnivoice.example.com/ui
https://omnivoice.example.com/api/v1
https://omnivoice.example.com/mcp
https://omnivoice.example.com/health
```

`--public-url` also configures the MCP DNS-rebinding host/origin allowlist before the MCP ASGI app is built.

## Kaggle secret example

Use Kaggle Secrets to retrieve the token inside the notebook, then put it in the process environment only for the runtime:

```python
import os
from kaggle_secrets import UserSecretsClient

secrets = UserSecretsClient()
os.environ["CLOUDFLARE_TUNNEL_TOKEN"] = secrets.get_secret(
    "CLOUDFLARE_TUNNEL_TOKEN"
)
os.environ["OMNIVOICE_PUBLIC_URL"] = "https://omnivoice.example.com"
```

Do not print either environment variable.

## Client configuration

Once the fixed hostname is running, AI clients can keep one MCP URL permanently:

```text
https://omnivoice.example.com/mcp
```

Kaggle session A can disappear and session B can reconnect the same named tunnel. ChatGPT, Claude Code, and Antigravity do not need a new OmniVoice MCP URL.

When the Kaggle runtime is offline, the fixed hostname remains the configured address but the origin is unavailable. A later Control Plane can make this state more graceful without changing the client URL.

## Security boundary

A tunnel token lets a connector run that tunnel, so treat it as a secret. Rotate it if exposed.

MCP mutation authentication is a separate milestone. Until bearer-token/scoped API authentication is implemented, do not publish mutation-capable `/mcp` to an unrestricted audience merely because the tunnel hostname is stable.

For a private deployment, Cloudflare Access can also be placed in front of the hostname, but compatibility with individual MCP clients must be tested before making Access interactive login part of the required path.
