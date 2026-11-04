'use strict';
let csrf = '';
let lastMetrics = null;
let filteringLoaded = false;
let updatesLoaded = false;
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
  filteringLoaded = false;
  updatesLoaded = false;
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

const lines = value => value.split(/[\n,]+/).map(item => item.trim()).filter(Boolean);
byId('filter-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    const form = event.target;
    const data = {ads: form.elements.ads.checked, threats: form.elements.threats.checked};
    for (const field of ['domains', 'allow', 'tlds', 'countries']) data[field] = lines(form.elements[field].value);
    await api('filtering', data);
    message('Filtering rules saved.');
    await status();
  });
});
byId('refresh-filters').addEventListener('click', event => busy(event.target, async () => {
  await api('filtering/refresh', {}); message('Blocklists updated.'); await status();
}));
byId('refresh-logs').addEventListener('click', event => busy(event.target, async () => {
  const result = await api('logs');
  byId('logs').textContent = Object.entries(result).map(([name, entries]) => name.toUpperCase() + '\n' + entries.join('\n')).join('\n\n');
}));
byId('backup-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    const result = await api('backup', {password: event.target.elements.password.value});
    const url = URL.createObjectURL(new Blob([JSON.stringify(result)], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = 'travelrouter-encrypted-backup.json'; link.click();
    URL.revokeObjectURL(url); event.target.reset(); message('Encrypted backup downloaded.');
  });
});
byId('import-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    const file = event.target.elements.file.files[0];
    if (!file || file.size > 750000) throw new Error('Backup must be smaller than 750 KB.');
    await api('import', {backup: JSON.parse(await file.text()), password: event.target.elements.password.value});
    event.target.reset(); csrf = ''; show('panel', false); show('login', true);
    message('Settings restored. Reconnect to the restored Wi-Fi network and sign in with its administrator password.');
  });
});

for (const [id, operation] of [['check-updates', 'check'], ['package-updates', 'packages']]) {
  byId(id).addEventListener('click', event => busy(event.target, async () => {
    await api('updates', {operation}); message('Update operation started. Progress appears below.');
  }));
}
byId('auto-update-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    await api('updates/settings', {automatic: event.target.elements.automatic.checked});
    message('Automatic update preference saved.');
  });
});
byId('app-update-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.submitter, async () => {
    const file = event.target.elements.file.files[0];
    if (!file || file.size > 2900000) throw new Error('Update file must be smaller than 2.9 MB.');
    await api('updates/install', {update: JSON.parse(await file.text())});
    event.target.reset(); message('Verifying the signed update. Check its status below before rebooting.');
  });
});
byId('reboot').addEventListener('click', event => busy(event.target, async () => {
  if (!window.confirm('Reboot this router now? Connected devices will briefly lose access.')) return;
  await api('reboot', {confirm: true}); message('Router is rebooting. Reconnect in a moment.');
}));

const formatBytes = value => value > 1048576 ? (value / 1048576).toFixed(1) + ' MiB' : (value / 1024).toFixed(1) + ' KiB';
async function metrics() {
  if (!csrf || byId('panel').hidden) return;
  const current = await api('metrics');
  byId('metrics').replaceChildren();
  const used = 100 * (1 - current.memory.available_bytes / current.memory.total_bytes);
  for (const [label, value] of [['Uptime', (current.uptime_seconds / 3600).toFixed(1) + ' h'],
    ['Memory used', used.toFixed(0) + '%'], ['Load (1 min)', current.load_average[0].toFixed(2)],
    ['Temperature', current.temperature_c === null ? 'N/A' : current.temperature_c.toFixed(1) + ' °C'],
    ['DNS queries', current.dns['total.num.queries'] ?? 'N/A'], ['DNS cache hits', current.dns['total.num.cachehits'] ?? 'N/A']]) {
    const tile = document.createElement('div'); const title = document.createElement('small'); title.textContent = label;
    const number = document.createElement('strong'); number.textContent = value; tile.append(title, number); byId('metrics').append(tile);
  }
  byId('traffic').replaceChildren();
  for (const [name, counters] of Object.entries(current.interfaces)) {
    const row = document.createElement('div'); row.className = 'network';
    let text = name + ' · Received ' + formatBytes(counters.rx_bytes) + ' · Sent ' + formatBytes(counters.tx_bytes);
    if (lastMetrics && lastMetrics.interfaces[name]) {
      const seconds = current.timestamp - lastMetrics.timestamp;
      if (seconds > 0) text += ' · ↓ ' + formatBytes(Math.max(0, counters.rx_bytes - lastMetrics.interfaces[name].rx_bytes) / seconds) + '/s';
    }
    row.textContent = text; byId('traffic').append(row);
  }
  byId('clients').replaceChildren();
  for (const client of current.clients) {
    const row = document.createElement('p'); row.textContent = client.ip + ' · ' + client.hostname; byId('clients').append(row);
  }
  if (!current.clients.length) byId('clients').textContent = 'No current DHCP leases.';
  lastMetrics = current;
}

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
  if (info.updates) {
    byId('update-status').textContent = info.updates.message + (info.updates.busy ? ' · Working…' : '') + (info.updates.reboot_required ? ' · Reboot required.' : '');
    if (!updatesLoaded) {
      byId('auto-update-form').elements.automatic.checked = info.updates.automatic;
      updatesLoaded = true;
    }
  }
  if (info.filtering) {
    const filtering = info.filtering;
    if (!filteringLoaded) {
      const form = byId('filter-form');
      for (const field of ['ads', 'threats']) form.elements[field].checked = filtering.settings[field];
      for (const field of ['domains', 'allow', 'tlds', 'countries']) form.elements[field].value = filtering.settings[field].join('\n');
      filteringLoaded = true;
    }
    byId('filter-status').textContent = filtering.metadata.updated
      ? 'Lists updated: ' + new Date(filtering.metadata.updated * 1000).toLocaleString() + '. ' + (filtering.last_error || '')
      : 'Lists will download after the first verified Internet connection. Custom domain rules work offline.';
  }
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

api('session').then(result => { signedIn(result); return status(); }).catch(() => {});
status().catch(error => message(error.message));
setInterval(() => status().catch(() => {}), 15000);
setInterval(() => metrics().catch(() => {}), 5000);
