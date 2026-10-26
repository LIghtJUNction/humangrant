#!/usr/bin/env python3
"""Exercise the real Rust server over public HTTP. No fake server, fake login, or real mail."""
from __future__ import annotations
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from jsonschema import Draft202012Validator
import http.cookiejar
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'clients'))
sys.path.insert(0,str(ROOT/'examples'))
from humangrant import Client, Identity, NoRedirect, ProtocolError, b64u, compact, sign_challenge, signature_material
from setup_demo import setup


class DataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reading=False
        self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('id')=='hg-data': self.reading=True
    def handle_data(self,data):
        if self.reading: self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='script': self.reading=False


class Human:
    def __init__(self,origin,key):
        self.origin,self.key=origin,key
        self.jar=http.cookiejar.CookieJar()
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),NoRedirect())
        self.csrf=''
    def request(self,method,path,body=None,*,csrf=None):
        headers={'Content-Type':'application/json','Origin':self.origin,'X-HG-CSRF':self.csrf if csrf is None else csrf}
        request=urllib.request.Request(self.origin+path,data=None if method=='GET' else compact(body or {}),headers=headers,method=method)
        try:
            response=self.opener.open(request,timeout=5)
        except urllib.error.HTTPError as error:
            response=error
        with response:
            data=response.read()
            assert response.headers.get('Cache-Control')=='no-store'
            content_type=response.headers.get_content_type()
            parsed=json.loads(data) if content_type=='application/json' else data.decode()
            return response.status,parsed
    def open(self,path):
        status,html=self.request('GET',path)
        assert status==200
        parser=DataParser();parser.feed(html)
        self.page=json.loads(''.join(parser.parts))
        self.csrf=self.page['csrf']
        return self.page
    def authenticate(self,path):
        status,data=self.request('POST',path+'/begin')
        assert status==200
        proof=sign_challenge(self.key,self.origin,data['challenge'])
        status,data=self.request('POST',path+'/verify',proof)
        if status==200: self.csrf=data['csrf']
        return status,data
    def approve(self,path,expires):
        return self.request('POST',path+'/approve',{'permissions':[{'action':'notes.read','resource':'alice-note'}],'expires_at':expires})


def expect_error(call,status,code=None):
    try: call()
    except ProtocolError as error:
        assert error.status==status,(error.status,status)
        if code: assert error.code==code,(error.code,code)
        return
    raise AssertionError('Expected request to be refused')


def create(client,expected='alice'):
    return client.request('POST','/v1/requests',{'client_id':'example-cli','target_service':'notes',
        'purpose':'Public HTTP test: read only','expected_human_id':expected,
        'requested_permissions':[{'action':'notes.read','resource':'alice-note'},{'action':'notes.write','resource':'alice-note'}]})


def run(binary: Path) -> int:
    if not binary.is_file():
        print('UNEXECUTED: Rust binary is missing. Run cargo build; no substitute server will be used.',file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix='humangrant-http-') as directory:
        folder=Path(directory)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        config=setup(folder/'state',port)
        origin=f'http://127.0.0.1:{port}'
        log_path=folder/'server.log'
        ai_key=Identity.load(folder/'state/ai.key.json')
        alice_key=Identity.load(folder/'state/alice.key.json')
        bob_key=Identity.load(folder/'state/bob.key.json')
        client=Client(origin,ai_key,local=True)
        wrong=Client(origin,Identity.generate(),local=True)
        issued_tokens=[]
        checks=[]
        with log_path.open('wb') as log:
            process=subprocess.Popen([str(binary),'serve',str(config)],stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+10
                while True:
                    if process.poll() is not None: raise RuntimeError('Rust server exited before readiness')
                    try:
                        with urllib.request.urlopen(origin+'/',timeout=1) as response:
                            assert response.status==200
                            assert response.headers.get_content_type()=='application/json'
                            assert response.headers.get('Cache-Control')=='no-store'
                            discovery=json.load(response)
                        break
                    except (OSError,urllib.error.URLError):
                        if time.monotonic()>=deadline: raise RuntimeError('Rust server did not become ready')
                        time.sleep(0.05)
                assert discovery=={
                    'protocol_version':'HumanGrant Protocol 0.1 Draft',
                    'origin':origin,'request_endpoint':origin+'/v1/requests',
                    'session_endpoint':origin+'/v1/session','specification_url':origin+'/spec/v0.1.md',
                    'openapi_url':origin+'/openapi.yaml','schema_url':origin+'/schemas/protocol.json',
                    'agent_ui':False,
                }
                schema=json.loads((ROOT/'schemas/protocol.json').read_text())
                Draft202012Validator({'$ref':'#/$defs/Discovery','$defs':schema['$defs']},
                    format_checker=Draft202012Validator.FORMAT_CHECKER).validate(discovery)
                with urllib.request.urlopen(origin+'/.well-known/humangrant.json',timeout=5) as response:
                    assert response.headers.get_content_type()=='application/json'
                    assert response.headers.get('Cache-Control')=='no-store'
                    assert response.headers.get('Set-Cookie') is None
                    assert json.load(response)==discovery
                for field in ('specification_url','openapi_url','schema_url'):
                    with urllib.request.urlopen(discovery[field],timeout=5) as response:
                        assert response.status==200
                checks.append('default headless JSON discovery and public contract documents')
                state=create(client);request=state['request_id'];path=urllib.parse.urlsplit(state['human_authorization_url']).path
                human=Human(origin,alice_key)
                assert human.open(path)['phase']=='waiting_human'
                assert human.open(path)['human_id'] is None
                assert human.request('GET',path+'/approve')[0]==404
                assert human.request('POST',path+'/begin',csrf='wrong')[0]==403
                expect_error(lambda:wrong.request('GET',f'/v1/requests/{request}/status.md',markdown=True),404)
                expect_error(lambda:wrong.request('POST',f'/v1/requests/{request}/claim'),404)
                assert human.authenticate(path)[0]==200
                expect_error(lambda:client.request('POST',f'/v1/requests/{request}/claim'),409)
                expect_error(lambda:client.request('GET','/v1/notes/alice-note'),403)
                assert human.approve(path,int(time.time())+300)[0]==200
                assert human.approve(path,int(time.time())+300)[0]==409
                issued=client.request('POST',f'/v1/requests/{request}/claim');token=issued['access_token'];issued_tokens.append(token)
                expect_error(lambda:client.request('POST',f'/v1/requests/{request}/claim'),409,'credential_already_issued')
                read=client.request('GET','/v1/notes/alice-note',token=token)
                assert read['context']['actor']['kind']=='ai' and read['context']['grantor_id']=='alice'
                expect_error(lambda:client.request('PUT','/v1/notes/alice-note',{'content':'blocked'},token=token),403)
                for resource in ['alice-other-note','bob-note']:
                    expect_error(lambda r=resource:client.request('GET','/v1/notes/'+r,token=token),403)
                expect_error(lambda:wrong.request('GET','/v1/session',token=token),401)
                link_token=path.rsplit('/',1)[1]
                expect_error(lambda:client.request('GET','/v1/session',token=link_token),401)
                actual=client.state(request)
                structured=client.request('GET',f'/v1/requests/{request}')
                actual.pop('checked_at');structured.pop('checked_at');assert actual==structured
                assert 'access_token' not in actual and 'private_key' not in json.dumps(actual)
                headers,_=signature_material(ai_key,'GET',origin+'/v1/session',b'',token)
                def same_signed_request():
                    request=urllib.request.Request(origin+'/v1/session',headers=headers,method='GET')
                    try:
                        with urllib.request.urlopen(request,timeout=5) as response: return response.status
                    except urllib.error.HTTPError as error: return error.code
                assert same_signed_request()==200 and same_signed_request()==401
                grants=human.open('/human/grants')['grants'];assert len(grants)==1
                assert human.request('POST',f"/human/grants/{issued['grant_id']}/revoke")[0]==200
                expect_error(lambda:client.request('GET','/v1/notes/alice-note',token=token),401)
                assert client.state(request)['grant_status']=='revoked'
                checks.append('forwarded link + real human proof + narrowed scope + replay + revoke')

                state=create(client);request=state['request_id'];path=urllib.parse.urlsplit(state['human_authorization_url']).path
                invitation={'email':'local-recipient@example.invalid','idempotency_key':'mail-once'}
                first=client.request('POST',f'/v1/requests/{request}/email',invitation)
                assert first==client.request('POST',f'/v1/requests/{request}/email',invitation)
                assert first['email_request_status']=='accepted'
                spooled=list((folder/'state/outbox').glob('*.eml'));assert len(spooled)==1
                message=spooled[0].read_text();assert state['human_authorization_url'] in message
                assert 'HumanGrant permission request' in message and 'notes.read' in message
                mail_human=human
                reviewed=mail_human.open(path)
                assert reviewed['human_id']=='alice' and reviewed['phase']=='waiting_human'
                assert client.state(request)['phase']=='waiting_human'
                expect_error(lambda:client.request('POST',f'/v1/requests/{request}/claim'),409)
                assert mail_human.approve(path,int(time.time())+300)[0]==200
                issued=client.request('POST',f'/v1/requests/{request}/claim');issued_tokens.append(issued['access_token'])
                assert client.request('GET','/v1/notes/alice-note',token=issued['access_token'])['context']['grantor_id']=='alice'
                checks.append('local .eml invitation + existing login without reauthentication + explicit consent + restricted read')

                state=create(client);request=state['request_id'];path=urllib.parse.urlsplit(state['human_authorization_url']).path
                mismatch=Human(origin,bob_key);mismatch.open(path)
                status,error=mismatch.authenticate(path);assert status==403 and error['error']=='expected_human_mismatch'
                client.request('POST',f'/v1/requests/{request}/cancel')
                assert client.state(request)['phase']=='cancelled'
                expect_error(lambda:client.request('POST',f'/v1/requests/{request}/claim'),409)
                checks.append('expected human mismatch + cancellation')

                state=create(client);request=state['request_id'];path=urllib.parse.urlsplit(state['human_authorization_url']).path
                rejector=Human(origin,alice_key);rejector.open(path);assert rejector.authenticate(path)[0]==200
                assert rejector.request('POST',path+'/reject')[0]==200
                assert client.state(request)['phase']=='rejected'
                expect_error(lambda:client.request('POST',f'/v1/requests/{request}/claim'),409)
                checks.append('authenticated refusal is terminal')

                state=create(client);request=state['request_id'];path=urllib.parse.urlsplit(state['human_authorization_url']).path
                approver=Human(origin,alice_key);approver.open(path);assert approver.authenticate(path)[0]==200
                assert approver.approve(path,int(time.time())+300)[0]==200
                def claim():
                    fresh=Client(origin,ai_key,local=True)
                    try:
                        data=fresh.request('POST',f'/v1/requests/{request}/claim');return 200,data
                    except ProtocolError as error:return error.status,{}
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results=list(executor.map(lambda _:claim(),range(2)))
                assert sorted(status for status,_ in results)==[200,409]
                issued_tokens.extend(data['access_token'] for status,data in results if status==200)
                checks.append('concurrent HTTP claims issue exactly once')
            finally:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        logs=log_path.read_text()
        for secret in issued_tokens+[ai_key.sign(b'probe'),alice_key.sign(b'probe'),'local-recipient@example.invalid','hg_browser=']:
            assert secret not in logs
        checks.append('server log contains no issued credentials, cookies or recipient address')
        print(json.dumps({'public_http':'passed','checks':checks,'real_mail_sent':False},indent=2))
    return 0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',type=Path,default=ROOT/'target/debug/humangrant')
    args=parser.parse_args()
    sys.exit(run(args.binary.resolve()))
