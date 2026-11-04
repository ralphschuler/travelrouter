'use strict';
let csrf = '';
const byId = id => document.getElementById(id);
const show = (id, visible) => { byId(id).hidden = !visible; };
const message = text => { byId('message').textContent = text; show('message', true); };

async function api(path, data) {
  const response = await fetch('/api/' + path, {
    method: data === undefined ? 'GET' : 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
    credentials: 'same-origin',
    body: data === undefined ? undefined : JSON.stringify(data)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}

function busy(element, action) {
  element.disabled = true;
  Promise.resolve().then(action).catch(error => message(error.message))
    .finally(() => { element.disabled = false; });
}

function signedIn(result) {
  csrf = result.csrf;
  show('login', false);
  show('setup', result.setup_required);
  show('panel', !result.setup_required);
}

byId('login-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    const data = Object.fromEntries(new FormData(event.target));
    signedIn(await api('login', data));
    event.target.reset();
    show('message', false);
    await status();
  });
});

for (const id of ['setup-form', 'settings-form']) {
  byId(id).addEventListener('submit', event => {
    event.preventDefault();
    busy(event.submitter, async () => {
      const data = Object.fromEntries(new FormData(event.target));
      if (data.admin_password !== data.confirmation) throw new Error('Administrator passwords do not match.');
      delete data.confirmation;
      const result = await api(id === 'setup-form' ? 'setup' : 'settings', data);
      event.target.reset();
      csrf = '';
      show('panel', false); show('setup', false); show('login', true);
      message('Saved. Join “' + result.ssid + '” with your new Wi-Fi passphrase, then sign in with your new administrator password.');
    });
  });
}

byId('scan').addEventListener('click', event => busy(event.target, async () => {
  const result = await api('scan', {});
  byId('networks').replaceChildren();
  for (const item of result.networks) {
    const row = document.createElement('div'); row.className = 'network';
    const name = document.createElement('span'); name.textContent = item.ssid;
    const info = document.createElement('small'); info.textContent = item.security + ' · ' + item.signal + '%';
    name.append(info);
    const select = document.createElement('button'); select.type = 'button'; select.textContent = 'Choose';
    select.addEventListener('click', () => {
      byId('connect-form').elements.ssid.value = item.ssid;
      byId('connect-form').elements.allow_open.checked = item.security === 'Open';
      byId('connect-form').elements.password.focus();
    });
    row.append(name, select); byId('networks').append(row);
  }
  if (!result.networks.length) message('No networks found. Check the upstream Wi-Fi adapter and try again.');
}));

byId('connect-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    const data = Object.fromEntries(new FormData(event.target));
    data.allow_open = event.target.elements.allow_open.checked;
    await api('connect', data);
    event.target.elements.password.value = '';
    message('Network saved. Checking Internet access. If a public sign-in is required, open http://neverssl.com in a new tab.');
    await status();
  });
});

byId('saved').addEventListener('click', event => busy(event.target, async () => {
  const result = await api('saved', {});
  byId('saved-networks').replaceChildren();
  for (const item of result.networks) {
    const row = document.createElement('div'); row.className = 'network';
    const name = document.createElement('span'); name.textContent = item.ssid + ' · priority ' + item.priority;
    row.append(name);
    for (const [label, action] of [['Use', 'activate'], ['Forget', 'forget'], ['Prioritize', 'priority']]) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
      button.addEventListener('click', () => busy(button, async () => {
        await api('network', {uuid: item.uuid, action, priority: Math.min(100, item.priority + 10)});
        message('Saved network updated.');
        if (action === 'forget') row.remove();
      }));
      row.append(button);
    }
    byId('saved-networks').append(row);
  }
}));

byId('logout').addEventListener('click', event => busy(event.target, async () => {
  await api('logout', {}); csrf = ''; show('panel', false); show('setup', false); show('login', true);
}));

byId('dns-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    await api('dns', {mode: event.target.elements.mode.value});
    message('DNS mode saved. The local resolver is being updated.');
    await status();
  });
});

byId('privacy-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    const data = Object.fromEntries(new FormData(event.target));
    data.port = Number(data.port);
    data.acknowledge_plaintext = event.target.elements.acknowledge_plaintext.checked;
    await api('privacy', data);
    event.target.elements.config.value = '';
    event.target.elements.password.value = '';
    message('Privacy route saved. Checking the protected connection.');
    await status();
  });
});

async function status() {
  const info = await api('status');
  byId('state').textContent = ({online: 'Internet connected', captive: 'Public Wi-Fi sign-in required', offline: 'Offline · setup available'})[info.state];
  byId('summary').textContent = info.state === 'captive'
    ? 'Your upstream network needs a sign-in. Open a plain HTTP page in another tab to finish its login.'
    : info.state === 'online' ? 'Your devices are behind the router firewall. Client DNS uses encrypted upstream resolution.'
    : 'Your private hotspot is ready. Choose an upstream network below to get online.';
  byId('details').replaceChildren();
  for (const [label, value] of [['Wi-Fi', info.ssid], ['Hotspot adapter', info.ap_interface],
    ['Upstream adapter', info.wan_interface || 'Not detected'], ['DNS', info.dns], ['Firewall', info.firewall ? 'Active' : 'Starting']]) {
    const key = document.createElement('dt'); key.textContent = label;
    const text = document.createElement('dd'); text.textContent = value;
    byId('details').append(key, text);
  }
  byId('hardware').textContent = info.hardware_note || info.last_error || '';
  byId('privacy-status').textContent = info.privacy_mode === 'direct'
    ? 'Direct mode: the firewall is active; no VPN or proxy protects your connection.'
    : info.privacy_mode + ': kill-switch enabled. ' + (info.tunnel_ready && info.state === 'online' ? 'Protected connection verified.' : 'Waiting for a verified tunnel; direct client access is blocked.');
  if (!byId('panel').contains(document.activeElement)) {
    byId('settings-form').elements.ssid.value = info.ssid || '';
    byId('settings-form').elements.country.value = info.country === '00' ? '' : info.country || '';
    byId('dns-form').elements.mode.value = info.dns_mode || 'dot';
    byId('privacy-form').elements.mode.value = info.privacy_mode || 'direct';
  }
}

api('session').then(signedIn).catch(() => {});
status().catch(error => message(error.message));
setInterval(() => status().catch(() => {}), 15000);
