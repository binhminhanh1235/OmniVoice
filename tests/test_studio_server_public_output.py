from types import SimpleNamespace

from omnivoice.cli.studio_server import _announce_endpoints, _endpoint_lines
from omnivoice.tunnel import parse_public_url


def _args():
    return SimpleNamespace(host="0.0.0.0", port=8000)


def test_endpoint_lines_include_clickable_public_studio_urls():
    public = parse_public_url("https://demo.trycloudflare.com")

    lines = _endpoint_lines(_args(), public)

    assert "Studio UI: http://0.0.0.0:8000/ui" in lines
    assert "PUBLIC STUDIO UI: https://demo.trycloudflare.com/ui" in lines
    assert "Public REST API: https://demo.trycloudflare.com/api/v1" in lines
    assert "Public OpenAPI: https://demo.trycloudflare.com/docs" in lines
    assert "Public MCP: https://demo.trycloudflare.com/mcp" in lines
    assert "Public Health: https://demo.trycloudflare.com/health" in lines


def test_announce_endpoints_uses_stdout_even_when_logger_is_silent(capsys):
    public = parse_public_url("https://demo.trycloudflare.com")

    _announce_endpoints(_args(), public)

    output = capsys.readouterr().out
    assert "OmniVoice Studio endpoints" in output
    assert "PUBLIC STUDIO UI: https://demo.trycloudflare.com/ui" in output
    assert "Public OpenAPI: https://demo.trycloudflare.com/docs" in output
