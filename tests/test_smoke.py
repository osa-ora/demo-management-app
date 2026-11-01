from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_homepage():
    r=client.get("/")
    assert r.status_code==200
    assert "Demo Management" in r.text

def test_health():
    r=client.get("/api/health")
    assert r.status_code==200 and r.json()["ok"] is True

def test_config_defaults():
    r=client.get("/api/config")
    assert r.status_code==200
    assert r.json()["provider"]=="ollama"
    assert any(x["id"]=="demoignite" for x in r.json()["mcp_servers"])

def test_skills_list():
    r=client.get("/api/skills")
    assert r.status_code==200 and "items" in r.json()


def test_demoignite_process_status():
    r = client.get("/api/mcp/demoignite/process")
    assert r.status_code == 200
    assert "managed" in r.json() and "running" in r.json()


def test_text_emitted_mcp_tool_calls_are_recovered():
    from app.main import _extract_text_tool_calls

    available = [
        {"function": {"name": "demoignite__get_demo_details"}},
        {"function": {"name": "demoignite__find_demo"}},
    ]
    model_text = '''
    {"name":"demoignite__get_demo_details","parameters{"key":"MCP Server Client Orchestrator","environment":"local"}}
    {"name":"demoignite__find_demo","parameters{"keyword":"MCP Server Client Orchestrator"}}
    '''
    calls = _extract_text_tool_calls(model_text, available)
    assert calls == [
        {"function": {"name": "demoignite__get_demo_details", "arguments": {
            "key": "MCP Server Client Orchestrator", "environment": "local"
        }}},
        {"function": {"name": "demoignite__find_demo", "arguments": {
            "keyword": "MCP Server Client Orchestrator"
        }}},
    ]


def test_text_tool_call_parser_ignores_unadvertised_tools():
    from app.main import _extract_text_tool_calls
    text = '{"name":"unknown__delete_everything","parameters":{"confirm":true}}'
    assert _extract_text_tool_calls(text, []) == []
