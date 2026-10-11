# Identity and example UI

The wordmark and symbol are original vector source assets for this repository. The joined strokes
represent an explicit connection, not a borrowed identity-provider mark or security certification.

Use [the light button](../assets/continue-with-human-beings.svg) or
[the dark button](../assets/continue-with-human-beings-dark.svg). Keep the text exactly:
**Continue with human beings**. SVG viewBox dimensions are 368 × 64; render at proportional sizes.
The actual interactive HTML button must have that accessible name. Decorative inner symbols have
empty alt text. A static image does not initiate a request or prove that integration is complete.

The [reference UI](../examples/web/index.html) uses local CSS and JavaScript, system fonts, a quiet
light/dark palette, ample space, keyboard focus indicators, and reduced-motion rules. It has no
external font download, analytics script, UI framework or CDN dependency. Request text is inserted
with textContent, not interpreted as HTML. CSP restricts scripts and connections to the service origin.

The human page separates request details, identity proof, and explicit scope selection. Permissions
start unchecked. The AI example does not store human keys or cookies and uses an independent key.
The Node tests cover the browser crypto module, not visual layout, accessibility certification or a
real browser support matrix. Full browser interaction remains unverified in this environment.
