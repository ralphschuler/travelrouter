# Mobile-first operations console

The primary operator is using a phone connected to the router's local hotspot.
The first screen must answer: is the upstream reachable, what route protects
traffic, and how do I connect? Desktop expands the same console rather than
changing its navigation or terminology.

## Tokens and layout

- Canvas `#f3f6fa`, surface `#ffffff`, navigation `#182944`, text `#1c2c44`,
  accent `#2455cf`, success `#17735b`, warning `#996316`.
- Locally bundled IBM Plex Sans; technical identifiers use the native monospace
  stack. No external font or analytics requests.
- A 64 px status header, single-column mobile views, 44 px minimum actions,
  16 px input text, and safe-area-aware bottom navigation.
- Overview, Connect, Privacy and Filters are one-tap mobile destinations. Logs,
  Updates and Settings are in More. At 1000 px the same destinations become a
  persistent left sidebar.
- The dashboard's three-part route view explains devices → router → upstream.
  All counters come from current metrics, never a decorative sample graph.
- Form groups expand for the chosen VPN/proxy mode; inactive configuration
  fields do not overwhelm the smaller screen.

## Interaction and accessibility

Semantic links with URL hashes identify each view. Form controls have labels;
passwords accept paste and password managers. Keyboard focus is visible, a skip
link reaches the workspace, changes have a polite live region, and reduced-motion
preferences are respected. Polling does not reset dirty configuration forms.
Long network names wrap and are inserted as text, not HTML.

The design was reviewed using frontend-design and web-design-guidelines. The
earlier marketing headline and long page of simultaneous forms were replaced
with a task-oriented console. Responsive browser tests are separate from real
phone/captive-assistant qualification on the CM5.
