import {importIdentity, signHuman} from "./webcrypto.js";

const data = JSON.parse(document.getElementById("hg-data").textContent);
const app = document.getElementById("app"), message = document.getElementById("message");
let fieldNumber = 0;
const element = (tag, text = "", className = "") => {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
};
const say = (text, error = false) => {
  message.textContent = text;
  message.classList.toggle("error", error);
};
function button(text, action, className = "") {
  const node = element("button", text, className);
  node.type = "button";
  node.addEventListener("click", async () => {
    node.disabled = true;
    node.setAttribute("aria-busy", "true");
    say("");
    try { await action(); } catch (error) { say(error.message, true); }
    finally { node.disabled = false; node.setAttribute("aria-busy", "false"); }
  });
  return node;
}
function title(kicker, heading, detail) {
  app.append(element("p", kicker, "eyebrow"), element("h1", heading), element("p", detail, "lead"));
}
function knownOrigin() {
  if (data.origin !== location.origin) throw new Error("Open this link at " + data.origin + " to continue.");
}
async function post(path, payload = {}) {
  knownOrigin();
  const response = await fetch(path, {
    method: "POST", credentials: "same-origin", redirect: "error",
    headers: {"Content-Type": "application/json", "X-HG-CSRF": data.csrf},
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || "This request could not be completed. Please reopen the link.");
  return result;
}
const date = timestamp => new Date(timestamp * 1000).toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"});
function metadata(pairs) {
  const list = element("dl");
  for (const [name, value] of pairs) {
    const row = element("div");
    row.append(element("dt", name), element("dd", String(value)));
    list.append(row);
  }
  return list;
}
function requestDetails() {
  const disclosure = element("details"), body = element("div", "", "details-content");
  disclosure.append(element("summary", "Request details"));
  body.append(metadata([
    ["Agent public-key fingerprint", data.actor_id],
    ["Request", data.request_id],
    ["Link expires", date(data.expires_at)],
    ["Account", data.expected_human_id || "The account you choose to sign in with"],
  ]));
  disclosure.append(body);
  app.append(disclosure);
}
function requestContext() {
  const context = element("div", "", "context");
  context.append(metadata([["Agent", data.client_id], ["Service", data.target_service]]));
  context.append(element("p", "Agent name supplied by the requester.", "unverified"));
  context.append(element("span", "Reason supplied by the agent", "purpose-label"), element("p", data.purpose, "purpose"));
  app.append(context);
}
function homeView() {
  app.className = "panel landing";
  app.append(element("p", "A HUMAN STEP", "eyebrow"));
  const heading = element("h1", "Sign in for");
  heading.append(document.createElement("br"), document.createTextNode("your agent."));
  app.append(heading, element("p", "Your agent sends a link. You sign in and confirm. It picks up where it left off.", "lead"));
  const hint = element("p", "", "handoff-line");
  const dot = element("span", "", "dot");
  dot.setAttribute("aria-hidden", "true");
  hint.append(dot, element("span", "Start from the link in your conversation."));
  app.append(hint);
}
function terminalView(phase) {
  const states = {
    approved: ["✓", "Sign-in confirmed.", "Your agent can now finish signing in. You can return to your conversation."],
    succeeded: ["✓", "You're all set.", "Your agent has signed in and can continue. You can close this page."],
    rejected: ["–", "Request declined.", "No access was granted. You can return to your conversation."],
    expired: ["↗", "This link has expired.", "Ask your agent for a new sign-in link, then open it here."],
    cancelled: ["–", "Request cancelled.", "This sign-in request is no longer active. You can close this page."],
    invalid: ["↗", "This link is unavailable.", "Open the complete sign-in link from your conversation, or ask your agent for a new one."],
  };
  const [mark, heading, detail] = states[phase];
  app.className = "panel terminal";
  const icon = element("span", mark, "status-mark" + (["approved", "succeeded"].includes(phase) ? "" : " neutral"));
  icon.setAttribute("aria-hidden", "true");
  app.append(icon);
  title("HUMANGRANT", heading, detail);
  if (data.client_id) {
    app.append(element("p", `${data.client_id} · ${new URL(data.origin).host}`, "note"));
    requestDetails();
  }
}
function localAuthentication() {
  const file = document.createElement("input");
  file.type = "file";
  file.accept = ".json";
  file.id = "identity-" + ++fieldNumber;
  const label = element("label", "Local account identity", "label");
  label.htmlFor = file.id;
  app.append(label, file, element("p", "Choose your account's identity file. The private key stays on this device; only the public key and signature are sent.", "note"));
  const actions = element("div", "", "actions");
  actions.append(button("Verify account", async () => {
    if (!file.files[0] || file.files[0].size > 16_384) throw new Error("Choose a local HumanGrant identity file to continue.");
    knownOrigin();
    const identity = await importIdentity(JSON.parse(await file.files[0].text()));
    const proof = await post(`/human/${data.link}/begin`);
    await post(`/human/${data.link}/verify`, await signHuman(identity, proof.challenge, data.origin, data.request_id));
    location.reload();
  }, "primary"));
  app.append(actions);
  const alternative = element("details", "", "cli");
  alternative.append(element("summary", "Verify from your terminal"));
  const challenge = element("textarea");
  challenge.readOnly = true;
  challenge.setAttribute("aria-label", "Authentication challenge");
  alternative.append(element("p", "Create a challenge, save it as challenge.json, and use the CLI sign-challenge command on your device."));
  alternative.append(button("Create challenge", async () => {
    const result = await post(`/human/${data.link}/begin`);
    challenge.value = JSON.stringify(result);
  }), challenge);
  const proof = element("textarea");
  proof.placeholder = '{"public_key":"…","signature":"…"}';
  proof.setAttribute("aria-label", "Public verification proof");
  alternative.append(element("p", "Paste the public key and signature returned by the command."), proof, button("Verify proof", async () => {
    const value = JSON.parse(proof.value);
    if (Object.keys(value).sort().join(",") !== "public_key,signature") throw new Error("Paste only the public key and signature.");
    await post(`/human/${data.link}/verify`, value);
    location.reload();
  }));
  app.append(alternative);
}
function humanView() {
  if (["approved", "succeeded", "rejected", "expired", "cancelled"].includes(data.phase)) {
    terminalView(data.phase);
    return;
  }
  app.append(element("p", new URL(data.origin).host, "service"));
  title("SIGN-IN REQUEST", "Let your agent continue.", "Confirm this request to let your agent sign in with your permission.");
  requestContext();
  if (!data.human_id) {
    localAuthentication();
    requestDetails();
    return;
  }
  if (data.expected_human_id && data.expected_human_id !== data.human_id) {
    app.append(element("p", `You're signed in as ${data.human_id}. This link needs ${data.expected_human_id}. Switch accounts, then reopen the link.`, "notice"));
    requestDetails();
    return;
  }
  const account = element("p", "", "account");
  account.append(element("span", "Signed in as"), element("strong", data.human_id));
  app.append(account, element("h2", "Allow access to"));
  const choices = data.requested_permissions.map(permission => {
    const allowed = data.grantable_permissions.some(p => p.action === permission.action && p.resource === permission.resource);
    const label = element("label", "", "scope" + (allowed ? "" : " unavailable"));
    const check = document.createElement("input");
    check.type = "checkbox";
    check.disabled = !allowed;
    check.checked = allowed;
    const text = element("span", permission.action);
    text.append(element("small", permission.resource + (allowed ? "" : " · Unavailable to this account")));
    label.append(check, text);
    app.append(label);
    return {check, permission};
  });
  app.append(element("p", "Access ends " + date(data.requested_grant_expires_at) + ".", "duration"));
  const actions = element("div", "", "actions");
  const approve = button("Sign in for agent", async () => {
    const permissions = choices.filter(choice => !choice.check.disabled && choice.check.checked).map(choice => choice.permission);
    if (!permissions.length) throw new Error("Choose at least one permission, or decline this request.");
    await post(`/human/${data.link}/approve`, {permissions, expires_at: data.requested_grant_expires_at});
    location.reload();
  }, "primary");
  approve.disabled = !choices.some(choice => choice.check.checked);
  actions.append(button("Decline", async () => { await post(`/human/${data.link}/reject`); location.reload(); }), approve);
  app.append(actions, element("p", "Only the access shown above is shared. Your password and browser session stay with you.", "note"));
  requestDetails();
}

app.replaceChildren();
try {
  knownOrigin();
  ({home: homeView, human: humanView, invalid: () => terminalView("invalid")}[data.view] || (() => terminalView("invalid")))();
} catch (error) { say(error.message, true); }
