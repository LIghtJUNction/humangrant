# A quiet login handoff

HumanGrant has one visible task: complete the sign-in requested by an agent. The normal home page has a wordmark and a short explanation. It has no login button, request form, developer console or account dashboard.

Agents discover the protocol through `/.well-known/humangrant.json`, `/agent.md`, an HTTP `Link` header, and a `<link rel="humangrant">` element in the document head. These public resources work without JavaScript. Their absence from the visible interface is a presentation choice; authentication still depends on verified signatures and account evidence.

A human link opens a focused handoff page showing the service, requester, purpose, account and requested access. An existing valid login leads directly to confirmation. Only requested permissions currently grantable by that account start selected; unavailable pairs stay disabled. Signing in verifies the account; the final confirmation authorizes the displayed selection. Loading a page never submits either operation.

The interface uses system fonts, generous spacing, restrained light and dark colors, keyboard focus indicators, and reduced-motion rules. CSS, JavaScript and SVG assets are local. Request data is inserted as text. The content security policy restricts scripts and connections to the service origin.

The reference key-file and local-signature controls support development. Integrations use the site's existing account login and keep the same compact confirmation page. The agent never receives a human password, cookie or private key.
