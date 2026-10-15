"""Exercise the real UI module with a small DOM fixture; this is not a browser certification."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('account,expected', [(None, 'alice'), ('alice', 'alice'), ('bob', 'alice')])
def test_existing_login_view_does_not_start_authentication_or_approve(account, expected):
    import json
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node unavailable')
    program = r'''
import assert from 'node:assert/strict';
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.textContent=''; this.classList={toggle(){}}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  setAttribute() {}
  addEventListener() {}
}
const data=JSON.parse(process.argv[1]);
const app=new Element('main');
const message=new Element('aside');
globalThis.location={origin:data.origin};
globalThis.document={
  getElementById: id=>id==='hg-data'?{textContent:JSON.stringify(data)}:id==='app'?app:message,
  createElement: tag=>new Element(tag),
};
globalThis.fetch=()=>{throw new Error('Rendering must not send a request');};
await import('./examples/web/ui.js');
const all=[];function walk(e){all.push(e);for(const c of e.children||[])walk(c);}walk(app);
const labels=all.filter(e=>e.tag==='button').map(e=>e.textContent);
assert.equal(message.textContent,'');
assert.equal(labels.includes('Verify my account'), !data.human_id);
assert.equal(labels.includes('Approve selected access'), data.human_id===data.expected_human_id);
assert.equal(labels.includes('Refuse'), data.human_id===data.expected_human_id);
for(const e of all.filter(e=>e.type==='checkbox'))assert.equal(e.checked,false);
'''
    data = dict(view='human', origin='https://auth.example.test', human_id=account,
                expected_human_id=expected, phase='waiting_human', target_service='notes',
                client_id='example-cli', actor_id='actor', expires_at=1800, checked_at=0,
                requested_grant_expires_at=1800, purpose='Read a note',
                requested_permissions=[dict(action='notes.read',resource='alice-note')],
                grantable_permissions=[dict(action='notes.read',resource='alice-note')])
    result=subprocess.run([node,'--input-type=module','-e',program,json.dumps(data)],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
