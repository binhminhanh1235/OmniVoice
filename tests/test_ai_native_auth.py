from omnivoice.auth import GENERATE_SCOPE, READ_SCOPE, required_scope_for_request


def test_ai_native_generation_routes_use_generate_scope():
    assert required_scope_for_request("POST", "/api/v1/audio/generate") == GENERATE_SCOPE
    assert required_scope_for_request("POST", "/api/v1/audio/preview") == GENERATE_SCOPE
    assert (
        required_scope_for_request(
            "POST",
            "/api/v1/projects/video-a/sections/S01/regenerate",
        )
        == GENERATE_SCOPE
    )
    assert (
        required_scope_for_request(
            "POST",
            "/api/v1/projects/video-a/sections/S01/chunks/B01-C01/regenerate",
        )
        == GENERATE_SCOPE
    )


def test_ai_native_read_routes_keep_read_scope():
    assert required_scope_for_request("GET", "/api/v1/artifacts") == READ_SCOPE
    assert required_scope_for_request("GET", "/api/v1/jobs/job_123/wait") == READ_SCOPE
