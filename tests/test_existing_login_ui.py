"""Exercise the shipped UI module; rendering must never start or approve a login."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import assert from 'node:assert/strict';
class Element {
  constructor(tag) {
    this.tag=tag; this.children=[]; this.textContent=''; this.listeners={};
    this.classList={toggle(){}};
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  setAttribute() {}
  addEventListener(name,fn) { this.listeners[name]=fn; }
}
const data=JSON.parse(process.argv[1]);
const app=new Element('main'), message=new Element('aside');
const calls=[];
let reloads=0;
globalThis.location={origin:data.origin,reload(){reloads++;}};
globalThis.document={
  getElementById: id=>id==='hg-data'?{textContent:JSON.stringify(data)}:id==='app'?app:message,
  createElement: tag=>new Element(tag),
  createTextNode: text=>Object.assign(new Element('#text'),{textContent:text}),
};
globalThis.fetch=async(path,options)=>{
  calls.push({path,options});
  return {ok:true,json:async()=>({status:'approved'})};
};
await import('./examples/web/ui.js');
const all=[];
function walk(e){all.push(e);for(const child of e.children||[])walk(child);}
walk(app);
const buttons=all.filter(e=>e.tag==='button');
const labels=buttons.map(e=>e.textContent);
const boxes=all.filter(e=>e.type==='checkbox');
assert.equal(message.textContent,'');
assert.equal(calls.length,0,'Rendering must not create, authenticate, or approve a request');
assert.equal(reloads,0);
'''


def run_ui(data, assertions):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node unavailable')
    result = subprocess.run(
        [node, '--input-type=module', '-e', HARNESS + assertions, json.dumps(data)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def human_data(account='alice', phase='waiting_human'):
    return dict(
        view='human', origin='https://auth.example.test', human_id=account,
        expected_human_id='alice', phase=phase, target_service='notes',
        client_id='example-cli', actor_id='actor', request_id='request', link='link', csrf='csrf',
        expires_at=1800, checked_at=0, requested_grant_expires_at=1800, purpose='Read a note',
        requested_permissions=[dict(action='notes.read', resource='alice-note'),
                               dict(action='notes.read', resource='bob-note')],
        grantable_permissions=[dict(action='notes.read', resource='alice-note')],
    )


@pytest.mark.parametrize('account', [None, 'alice', 'bob'])
def test_existing_login_view_never_automatically_authenticates_or_approves(account):
    run_ui(human_data(account), r'''
assert.equal(labels.includes('Verify account'), !data.human_id);
assert.equal(labels.includes('Sign in for agent'), data.human_id===data.expected_human_id);
assert.equal(labels.includes('Decline'), data.human_id===data.expected_human_id);
if(data.human_id===data.expected_human_id){
  assert.equal(boxes[0].checked,true);
  assert.equal(boxes[0].disabled,false);
  assert.equal(boxes[1].checked,false);
  assert.equal(boxes[1].disabled,true);
}
''')


def test_home_has_no_interactive_login_entry():
    run_ui(dict(view='home', origin='https://auth.example.test'), r'''
assert.equal(buttons.length,0);
assert.equal(all.filter(e=>['input','form','textarea','select','a'].includes(e.tag)).length,0);
''')
    html = (ROOT / 'examples/web/index.html').read_text()
    assert 'rel="humangrant" type="application/json" href="/.well-known/humangrant.json"' in html
    assert 'rel="alternate" type="text/markdown" href="/agent.md"' in html
    assert '<button' not in html


@pytest.mark.parametrize('phase', ['approved', 'succeeded', 'rejected', 'expired', 'cancelled'])
def test_finished_requests_have_no_sign_in_controls(phase):
    run_ui(human_data(phase=phase), r'''
assert.equal(buttons.length,0);
assert.equal(boxes.length,0);
''')


def test_invalid_link_has_no_controls():
    run_ui(dict(view='invalid', origin='https://auth.example.test'), r'''
assert.equal(buttons.length,0);
assert.equal(boxes.length,0);
assert(all.some(e=>e.textContent==='This link is unavailable.'));
''')


def test_only_explicit_click_submits_the_available_scope_and_csrf():
    run_ui(human_data(), r'''
// A disabled permission must stay excluded even if local DOM state is changed.
boxes[1].checked=true;
await buttons.find(e=>e.textContent==='Sign in for agent').listeners.click();
assert.equal(calls.length,1);
assert.equal(calls[0].path,'/human/link/approve');
assert.equal(calls[0].options.method,'POST');
assert.equal(calls[0].options.headers['X-HG-CSRF'],'csrf');
assert.deepEqual(JSON.parse(calls[0].options.body),{
  permissions:[{action:'notes.read',resource:'alice-note'}],expires_at:1800,
});
assert.equal(reloads,1);
''')


def test_empty_selection_does_not_send_approval():
    run_ui(human_data(), r'''
boxes[0].checked=false;
await buttons.find(e=>e.textContent==='Sign in for agent').listeners.click();
assert.equal(calls.length,0);
assert.equal(reloads,0);
assert.equal(message.textContent,'Choose at least one permission, or decline this request.');
''')


def test_decline_never_calls_approval():
    run_ui(human_data(), r'''
await buttons.find(e=>e.textContent==='Decline').listeners.click();
assert.equal(calls.length,1);
assert.equal(calls[0].path,'/human/link/reject');
assert.deepEqual(JSON.parse(calls[0].options.body),{});
assert.equal(reloads,1);
''')
