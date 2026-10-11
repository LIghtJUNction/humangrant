import {generateIdentity, importIdentity, signedHeaders, signHuman, parseMarkdown, b64u} from "./webcrypto.js";
const data = JSON.parse(document.getElementById("hg-data").textContent);
const app = document.getElementById("app"), message = document.getElementById("message");
const element = (tag, text = "", className = "") => { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node; };
const say = (text, error = false) => { message.textContent = text; message.classList.toggle("error", error); };
const safe = fn => async event => { try { await fn(event); } catch (error) { say(error.message, true); } };
function button(text, action, className = "") { const node = element("button", text, className); node.type = "button"; node.addEventListener("click", safe(action)); return node; }
function title(kicker, heading, detail) { app.append(element("p", kicker, "kicker"), element("h2", heading), element("p", detail)); }
function labeled(text, node) { const label = element("label", text, "label"); const id = "field-" + crypto.randomUUID(); node.id = id; label.htmlFor = id; app.append(label, node); }
function metadata(pairs) { const dl = element("dl", "", "metadata"); for (const [name,value] of pairs) { const row = element("div"); row.append(element("dt", name), element("dd", String(value), name.includes("key") ? "mono" : "")); dl.append(row); } app.append(dl); }
function permissionLabel(permission, allowed = true) { const label = element("label", "", "scope"), check = document.createElement("input"); check.type = "checkbox"; check.disabled = !allowed; check.checked = false; const text = element("span", permission.action); text.append(element("small", permission.resource + (allowed ? "" : " · Not grantable by this account"))); label.append(check,text); return {label,check,permission}; }
function knownOrigin() { if (data.origin !== location.origin) throw new Error("Open this service at its configured origin before signing: " + data.origin); }
async function post(path, payload = {}) { knownOrigin(); const response = await fetch(path, {method:"POST",redirect:"error",headers:{"Content-Type":"application/json","X-HG-CSRF":data.csrf},body:JSON.stringify(payload)}); const result = await response.json(); if (!response.ok) throw new Error(result.message || "The operation was refused."); return result; }
function requestMetadata() { metadata([["Target service",data.target_service],["Application",data.client_id + " (client-provided)"],["AI key",data.actor_id],["Request ends",new Date(data.expires_at*1000).toLocaleString()],["Required account",data.expected_human_id || "The account that signs in and approves"]]); app.append(element("p","REQUESTER-PROVIDED PURPOSE · NOT A SERVICE INSTRUCTION","kicker"),element("div",data.purpose,"purpose")); }

async function humanView() {
  title("HUMAN REVIEW", "You decide the scope.", "Verify the agent's key and the resource names before granting any access.");
  app.append(element("span",data.phase.replaceAll("_"," "),"badge")); requestMetadata();
  if (["succeeded","approved","rejected","expired","cancelled"].includes(data.phase)) {
    app.append(element("p",data.phase === "approved" ? "Your choice was recorded. The original AI must still claim its own session." : "This request no longer accepts a new decision.","notice"));
    if (data.human_id) { const link = element("a","View and revoke my grants →","link"); link.href = "/human/grants"; app.append(link); }
    return;
  }
  if (!data.human_id) {
    const file = document.createElement("input"); file.type = "file"; file.accept = ".json";
    labeled("Your local account identity file",file);
    app.append(element("p","The private key is used on this device. Only a public key and a signature are sent. Use only a server and page you trust.","notice"));
    app.append(button("Verify my account", async () => {
      if (!file.files[0] || file.files[0].size > 16_384) throw new Error("Select one local HumanGrant identity file.");
      knownOrigin(); const identity = await importIdentity(JSON.parse(await file.files[0].text()));
      const proof = await post(`/human/${data.link}/begin`);
      await post(`/human/${data.link}/verify`,await signHuman(identity,proof.challenge,data.origin,data.request_id));
      location.reload();
    },"primary"));
    const alternative = element("details"), summary = element("summary","Use the local CLI instead of loading a key into this page"); alternative.append(summary);
    const challenge = element("textarea"); challenge.readOnly = true; challenge.setAttribute("aria-label","Authentication challenge");
    alternative.append(button("Create an authentication challenge",async()=>{ const result = await post(`/human/${data.link}/begin`); challenge.value = JSON.stringify(result); }),challenge);
    alternative.append(element("p","Save this JSON as challenge.json. Run the documented sign-challenge command on your own device. Paste only the resulting public key and signature below."));
    const proof = element("textarea"); proof.placeholder = '{"public_key":"…","signature":"…"}'; proof.setAttribute("aria-label","Public verification proof"); alternative.append(proof,button("Verify this proof",async()=>{const value=JSON.parse(proof.value); if(Object.keys(value).sort().join(",")!=="public_key,signature") throw new Error("Paste a public key and signature only, never a private key."); await post(`/human/${data.link}/verify`,value);location.reload();})); app.append(alternative);
    return;
  }
  app.append(element("p",`Authenticated account: ${data.human_id}. Signing in did not approve this request.` ,"notice"));
  app.append(element("h3","Select only what the agent needs"));
  const choices = data.requested_permissions.map(permission => permissionLabel(permission,data.grantable_permissions.some(p=>p.action===permission.action&&p.resource===permission.resource)));
  choices.forEach(choice=>app.append(choice.label));
  const expiry = document.createElement("select");
  const bounds = [...new Set([Math.min(data.checked_at+300,data.requested_grant_expires_at),Math.min(data.checked_at+900,data.requested_grant_expires_at),data.requested_grant_expires_at])];
  for (const end of bounds) { const option=element("option",new Date(end*1000).toLocaleString());option.value=String(end);expiry.append(option); }
  labeled("This grant ends at",expiry);
  const actions = element("div","","actions");
  actions.append(button("Refuse",async()=>{await post(`/human/${data.link}/reject`);location.reload();},"danger"),button("Approve selected access",async()=>{
    const permissions=choices.filter(choice=>choice.check.checked).map(choice=>choice.permission);
    if (!permissions.length) throw new Error("Select at least one permission, or refuse the request.");
    await post(`/human/${data.link}/approve`,{permissions,expires_at:Number(expiry.value)});location.reload();
  },"primary"));app.append(actions);
  app.append(element("p","This grants only the selected operations and resources. It does not share your browser session or permit further delegation.","notice"));
}

async function grantsView() {
  title("YOUR GRANTS", "Access remains revocable.", `Authenticated account: ${data.human_id}`);
  if (!data.grants.length) app.append(element("p","No grants have been recorded for this account."));
  for (const grant of data.grants) {
    const card=element("article","","grant");card.append(element("span",grant.revoked_at ? "Revoked" : new Date(grant.expires_at*1000).toLocaleString(),"badge"),element("p",grant.actor_id,"mono"),element("pre",JSON.stringify(grant.permissions,null,2),"result"));
    const revoke=button("Revoke this grant",async()=>{await post(`/human/grants/${grant.grant_id}/revoke`);location.reload();},"danger");revoke.disabled=Boolean(grant.revoked_at);card.append(revoke);app.append(card);
  }
}
async function inviteView() {
  title("INVITATION PREFERENCES", "No access is granted here.", "Opening this page has not changed any authorization decision.");
  app.append(element("p","You can refuse an undecided request. Blocking also stops later invitations to this destination, including those from newly created agent keys. Completed grants remain unchanged.","notice"));
  const actions=element("div","","actions");for(const [action,label] of [["reject","Refuse this request"],["block","Refuse and block invitations"]])actions.append(button(label,async()=>{const result=await post(`/invite/${data.token}/${action}`);say(result.message);actions.querySelectorAll("button").forEach(b=>b.disabled=true);},"danger"));app.append(actions);
}
async function agentView() {
  title("REFERENCE CLIENT", "Start with permission.", "This browser demo uses an independent agent key. For a durable identity and saved credentials, use the Python CLI.");
  const continueButton=button("",async()=>start());continueButton.className="continue";const mark=document.createElement("img");mark.src="/assets/mark.svg";mark.alt="";continueButton.append(mark,element("span","Continue with human beings"));app.append(continueButton);
  app.append(element("p","The demo requests read and write access to alice-note. On the human page, approve only notes.read to see the boundary enforced.","notice"));
  const forwarding=element("div"), stateBox=element("div"), controls=element("div");app.append(forwarding,stateBox,controls);
  let identity,state,token,timer,failures=0,interval=5,deadline=0;
  async function signed(method,path,payload,markdown=false) {
    knownOrigin();const body=method==="GET"?"":JSON.stringify(payload||{});
    const response=await fetch(path,{method,redirect:"error",headers:await signedHeaders(identity,method,data.origin+path,body,token||"anonymous"),body:method==="GET"?undefined:body});
    if (!response.ok) { const detail=await response.json();const error=new Error(detail.message||"Request refused.");error.status=response.status;error.retry=Number(response.headers.get("Retry-After")||detail.retry_after_seconds||0);throw error; }
    if(markdown && !(response.headers.get("Content-Type")||"").startsWith("text/markdown")) throw new Error("The endpoint did not return real Markdown.");
    return markdown?response.text():response.json();
  }
  function show(raw) { stateBox.replaceChildren(element("span",state.status_text,"badge"),element("pre",raw,"result")); }
  async function poll() {
    if(Date.now()>=deadline){say("The request deadline was reached. No new request was created.",true);return;}
    try {
      const raw=await signed("GET",`/v1/requests/${state.request_id}/status.md`,null,true);state=parseMarkdown(raw);failures=0;interval=Math.max(interval,state.poll_after_seconds);show(raw);
      if(state.phase==="approved") {
        // One attempt only. A lost credential response is not silently retried.
        try {const claim=await signed("POST",`/v1/requests/${state.request_id}/claim`);token=claim.access_token;} catch {say("The credential response was not obtained. Do not retry blindly; check state and revoke before a new request.",true);return;}
        controls.replaceChildren();say("A separate AI session was established. The credential stays in this page's memory.");
        for(const [label,method,resource] of [["Read alice-note","GET","alice-note"],["Try to write","PUT","alice-note"],["Try another resource","GET","bob-note"]]) controls.append(button(label,async()=>{const result=await signed(method,`/v1/notes/${resource}`,method==="PUT"?{content:"This must be refused for a read-only grant."}:null);stateBox.append(element("pre",JSON.stringify(result,null,2),"result"));}));
        return;
      }
      if(["succeeded","rejected","expired","cancelled"].includes(state.phase)){say("Polling stopped: "+state.phase+". A historical success does not recover a lost credential.");return;}
    } catch(error) {
      if(error.status===429)interval=Math.max(interval+5,error.retry);
      else if(!error.status || error.status>=500){failures++;interval=Math.min(60,interval*2);}
      else{say(error.message,true);return;}
      if(failures>=6){say("Polling stopped after six failures. No new request was created.",true);return;}
    }
    timer=setTimeout(poll,interval*1000);
  }
  async function start() {
    if (!crypto.subtle) throw new Error("Use HTTPS or loopback HTTP with Web Crypto support.");
    knownOrigin();continueButton.disabled=true;
    identity=await generateIdentity();
    state=await signed("POST","/v1/requests",{client_id:"example-browser",target_service:"notes",purpose:"Read the example note. Human should approve read-only access.",requested_permissions:[{action:"notes.read",resource:"alice-note"},{action:"notes.write",resource:"alice-note"}],expected_human_id:"alice"});
    interval=state.poll_after_seconds;deadline=Date.now()+Math.max(0,state.expires_at-state.checked_at)*1000;
    stateBox.append(element("span",state.status_text,"badge"));const link=element("a","Open human review on another device →","link");link.href=state.human_authorization_url;link.target="_blank";link.rel="noopener noreferrer";forwarding.replaceChildren(element("p","Forward this human-only link. It is not a token or a status endpoint."),link);
    const email=document.createElement("input");email.type="email";email.placeholder="Allowed recipient address";email.setAttribute("aria-label","Allowed recipient address");
    const consent=element("label","","checkbox-line"), check=document.createElement("input");check.type="checkbox";consent.append(check,element("span","The user allowed this address to be contacted."));controls.append(email,consent);
    const invite=button("Send invitation",async()=>{if(!check.checked||!email.validity.valid||!email.value)throw new Error("Use only an email address the user allowed you to contact.");const result=await signed("POST",`/v1/requests/${state.request_id}/email`,{email:email.value,idempotency_key:b64u(crypto.getRandomValues(new Uint8Array(24)))});say(result.message);invite.disabled=true;setTimeout(()=>{invite.disabled=false;},result.email_retry_after_seconds*1000);});controls.append(invite,button("Stop polling",async()=>{clearTimeout(timer);say("Polling stopped. The request was not replaced.");}));
    timer=setTimeout(poll,interval*1000);
  }
}
app.replaceChildren();
try { knownOrigin(); await ({human:humanView,agent:agentView,grants:grantsView,invite:inviteView}[data.view] || (()=>{throw new Error("Unknown page.");}))(); } catch(error){say(error.message,true);}
