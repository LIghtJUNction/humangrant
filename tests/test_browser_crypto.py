"""Run the actual browser crypto module under Node WebCrypto, not a simulated browser UI."""
import json
import shutil
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_webcrypto_cross_language_vectors():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is unavailable; no browser compatibility claim can be made')
    program = r'''
import assert from "node:assert/strict";
import fs from "node:fs";
import {importIdentity, generateIdentity, signedHeaders, signHuman, parseMarkdown, b64u} from "./examples/web/webcrypto.js";
const v = JSON.parse(fs.readFileSync("tests/fixtures/signature.json","utf8"));
const key = await importIdentity({format:"humangrant-key-v1", public_key:v.public_key, private_key:b64u(new Uint8Array(Buffer.from(v.seed_hex,"hex")))});
const headers = await signedHeaders(key, v.method, v.origin+v.path, v.body_utf8, "anonymous", v.created_at, b64u(Uint8Array.from({length:24},(_,i)=>i)));
assert.deepEqual(headers,v.headers);
const generated = await generateIdentity();
assert.equal(generated.privateKey.extractable,false);
assert.equal(generated.publicKey.length,43);
await assert.rejects(importIdentity({format:"humangrant-key-v1",public_key:generated.publicKey,private_key:b64u(new Uint8Array(Buffer.from(v.seed_hex,"hex")))}));
const state = JSON.parse(fs.readFileSync("tests/fixtures/state.json","utf8"));
assert.deepEqual(parseMarkdown(fs.readFileSync("tests/fixtures/state.md","utf8")),state);
assert.throws(()=>parseMarkdown(fs.readFileSync("tests/fixtures/state.md","utf8")+'\nphase: "succeeded"\n'));
const challenge = JSON.stringify(["HumanGrant human authentication 0.1",v.origin,"req","session","nonce",Math.floor(Date.now()/1000)+120]);
const proof = await signHuman(key,challenge,v.origin,"req");
const publicKey = await crypto.subtle.importKey("raw",Buffer.from(v.public_key,"base64url"),"Ed25519",false,["verify"]);
assert(await crypto.subtle.verify("Ed25519",publicKey,Buffer.from(proof.signature,"base64"),new TextEncoder().encode(challenge)));
await assert.rejects(signHuman(key,challenge,"https://other.example.test","req"));
await assert.rejects(signHuman(key,challenge,v.origin,"other"));
console.log("WebCrypto: Python/JavaScript signature equality, real verification, scope and parser checks passed");
'''
    result = subprocess.run([node, '--input-type=module', '-e', program], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
