"""Validate the published wire schemas and canonical examples without a network."""
import copy
import json
from pathlib import Path
import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT/'schemas/protocol.json').read_text())


def validate(name, value):
    Draft202012Validator({'$ref':f'#/$defs/{name}', '$defs':SCHEMA['$defs']}).validate(value)


def test_schema_itself_valid():
    Draft202012Validator.check_schema(SCHEMA)


def test_state_fixture_valid():
    validate('State',json.loads((ROOT/'tests/fixtures/state.json').read_text()))


def test_create_fixture_valid():
    vector = json.loads((ROOT/'tests/fixtures/signature.json').read_text())
    validate('CreateRequest',json.loads(vector['body_utf8']))


@pytest.mark.parametrize('permission', [
    {'action':'notes.read','resource':'../other'},
    {'action':'notes.read','resource':'*'},
    {'action':'notes.read','resource':'x','admin':True},
    {'action':'','resource':'x'},
    {'action':'notes.read','resource':''},
])
def test_bad_permission_schema(permission):
    with pytest.raises(Exception):
        validate('Permission',permission)


def test_unknown_create_fields_rejected():
    vector = json.loads((ROOT/'tests/fixtures/signature.json').read_text())
    value = json.loads(vector['body_utf8'])
    value['user_id'] = 'admin'
    with pytest.raises(Exception):
        validate('CreateRequest',value)


def test_openapi_has_all_required_public_paths():
    api = yaml.safe_load((ROOT/'openapi.yaml').read_text())
    assert api['openapi']=='3.1.0'
    assert {'/v1/requests','/v1/requests/{id}/status.md','/v1/requests/{id}',
        '/v1/requests/{id}/claim','/v1/requests/{id}/cancel',
        '/v1/requests/{id}/email','/human/{link}','/human/{link}/begin',
        '/human/{link}/verify','/human/{link}/approve','/human/{link}/reject',
        '/v1/session','/v1/human/grants','/v1/human/grants/{id}/revoke',
        '/v1/notes/{id}'}.issubset(api['paths'])
    content = api['paths']['/v1/requests/{id}/status.md']['get']['responses']['200']['content']
    assert 'text/markdown' in content


def test_one_state_mapping_source_contains_three_visible_states():
    mapping = json.loads((ROOT/'spec/states.json').read_text())
    assert mapping['waiting_human']['status_text']=='等待人类中'
    assert mapping['awaiting_consent']['status_text']=='人类登录中'
    assert mapping['succeeded']['status_text']=='登录成功'
    assert {k for k,v in mapping.items() if v['terminal']}=={'succeeded','rejected','expired','cancelled'}


def test_no_python_reference_server_substitution():
    # The client's language-independent tests are not an implementation of Rust's HTTP handlers.
    assert not (ROOT/'examples/server.py').exists()
    assert 'include_str!("sql/' in (ROOT/'src/requests.rs').read_text()
