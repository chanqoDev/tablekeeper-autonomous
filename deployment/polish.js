(() => {
  const tableLabels = new Map();
  const restaurantZones = new Map();
  const unavailableRestaurants = new Set();
  const reservationsByReference = new Map();
  const sourceEntries = new Map();
  let retryRender = null;
  const originalFetch = window.fetch.bind(window);

  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    const url = new URL(typeof args[0] === 'string' ? args[0] : args[0].url, location.href);
    const restaurantMatch = url.pathname.match(/^\/restaurants\/([^/]+)$/);
    if (restaurantMatch && response.ok) {
      try {
        const data = await response.clone().json();
        tableLabels.set(decodeURIComponent(restaurantMatch[1]), new Map((data.tables || []).map(table => [table.id, table.label])));
        restaurantZones.set(decodeURIComponent(restaurantMatch[1]), data.timezone || null);
      } catch (_) {}
    }
    const historyMatch = url.pathname.match(/^\/reservations\/([^/]+)\/history$/);
    if (historyMatch && response.ok) {
      try {
        const data = await response.clone().json();
        sourceEntries.set(decodeURIComponent(historyMatch[1]), data.entries || []);
      } catch (_) {}
    }
    return response;
  };

  const html = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const labelsFor = restaurantId => tableLabels.get(restaurantId);
  const niceField = field => ({table_id:'Table',table_ids:'Tables',starts_at_local:'Reservation time',party_size:'Party size'}[field] || String(field || 'Details').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase()));
  const eventName = event => ({created:'Created',cancelled:'Cancelled',reassigned:'Reassigned',changed:'Updated'}[event] || String(event || 'Updated').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase()));
  const tableValue = (value, labels) => {
    if (value === null || value === undefined) return '—';
    const ids = Array.isArray(value) ? value : [value];
    return ids.map(id => labels?.get(id) || 'Table label unavailable').join(' + ');
  };
  const prettyValue = (field, value, labels) => {
    if (value === null || value === undefined) return '—';
    if (field === 'table_id' || field === 'table_ids') return tableValue(value, labels);
    if (field === 'starts_at_local' && typeof value === 'string') return value.replace('T', ' at ');
    if (field === 'party_size') return `${value} ${Number(value) === 1 ? 'guest' : 'guests'}`;
    return typeof value === 'string' || typeof value === 'number' ? String(value) : JSON.stringify(value);
  };
  const formattedTime = (raw, zone) => {
    const date = new Date(raw);
    if (!Number.isFinite(date.getTime())) return `${raw} (timezone unavailable)`;
    if (zone) {
      try {
        const formatted = new Intl.DateTimeFormat(undefined, {dateStyle:'medium',timeStyle:'short',timeZone:zone}).format(date);
        return `${formatted} (${zone})`;
      } catch (_) {}
    }
    const match = String(raw).match(/^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)(?::(\d\d)(?:\.\d+)?)?(Z|[+-]\d\d:\d\d)$/);
    if (!match) return `${raw} (timezone unavailable)`;
    // Format the stored wall-clock fields as if they were UTC, then label them
    // with the numeric offset already present in the historical timestamp.
    const wallClock = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]), Number(match[6] || 0)));
    const formatted = new Intl.DateTimeFormat(undefined, {dateStyle:'medium',timeStyle:'short',timeZone:'UTC'}).format(wallClock);
    const offset = match[7] === 'Z' ? '+00:00' : match[7];
    return `${formatted} (UTC${offset})`;
  };
  const termSummary = terms => {
    if (!terms || typeof terms !== 'object') return 'Accepted terms were not included with this historical event.';
    const duration = terms.reservation_duration_minutes;
    const cutoff = terms.cancellation_cutoff_minutes;
    const slot = terms.slot_minutes;
    return `Accepted policy v${terms.policy_version ?? 'unknown'}: ${duration ?? 'unspecified'} minute seating; free cancellation until ${cutoff ?? 'unspecified'} minutes before the reservation${slot ? `; seatings begin every ${slot} minutes` : ''}.`;
  };

  const renderHistory = (panel, reference, restaurantId) => {
    const entries = sourceEntries.get(reference);
    if (!entries || !panel.isConnected) return;
    const labels = labelsFor(restaurantId) || new Map();
    const zone = restaurantZones.get(restaurantId);
    const list = panel.querySelector('.history-list');
    if (!list) return;
    list.innerHTML = entries.map(entry => {
      const changes = (entry.changes || []).map(change => {
        const field = change.field || 'details';
        const from = change.from === null ? null : prettyValue(field, change.from, labels);
        const to = change.to === null ? null : prettyValue(field, change.to, labels);
        const text = from === null ? to : `${from} → ${to}`;
        return `<li><strong>${html(niceField(field))}:</strong> ${html(text || 'Recorded')}</li>`;
      });
      const event = eventName(entry.event);
      const eventDescription = changes.length ? '' : event === 'Cancelled' ? 'This reservation was cancelled.' : event === 'Created' ? 'This reservation was created.' : event === 'Reassigned' ? 'The reservation was moved to another table.' : 'No field changes were recorded for this event.';
      return `<li><div class="history-heading"><strong>${html(event)}</strong><span>Revision ${html(entry.revision)}</span></div><time>${html(formattedTime(entry.at, zone))}</time>${changes.length ? `<ul class="history-changes">${changes.join('')}</ul>` : `<p class="small-note">${html(eventDescription)}</p>`}<p class="history-terms">${html(termSummary(entry.accepted_terms))}</p><details><summary>Technical details</summary><pre>${html(JSON.stringify(entry, null, 2))}</pre></details></li>`;
    }).join('');
    list.dataset.polished = 'true';
    if (retryRender) clearInterval(retryRender);
  };

  const observer = new MutationObserver(() => {
    const panel = document.getElementById('history-panel');
    const detail = document.querySelector('[data-testid="reservation-detail"]');
    if (!panel || !detail) return;
    if (panel.querySelector('.history-list')?.dataset.polished === 'true') return;
    const reference = detail.querySelector('code')?.textContent?.trim();
    const match = [...sourceEntries.keys()].find(key => key === reference);
    const reservation = reservationsByReference.get(reference);
    if (reservation && window.__tablekeeperRestaurantDetailsUnavailable) {
      unavailableRestaurants.add(reservation.restaurant_id);
      tableLabels.set(reservation.restaurant_id, new Map());
      restaurantZones.set(reservation.restaurant_id, null);
    }
    if (reservation && unavailableRestaurants.has(reservation.restaurant_id)) {
      const seating = detail.querySelector('[data-testid="reservation-tables"]');
      if (seating) seating.innerHTML = '<strong>Seating:</strong> Table label unavailable';
    }
    const restaurantId = reservation?.restaurant_id || window.__tablekeeperPolishRestaurantId;
    if (match && restaurantId) renderHistory(panel, match, restaurantId);
  });
  observer.observe(document.getElementById('main-content') || document.body, {childList:true, subtree:true});

  // The reservation response exposes restaurant_id before the history request.
  const apiFetch = window.fetch;
  window.fetch = async (...args) => {
    const url = new URL(typeof args[0] === 'string' ? args[0] : args[0].url, location.href);
    const reservationMatch = url.pathname.match(/^\/reservations\/([^/]+)$/);
    const response = await apiFetch(...args);
    if (reservationMatch && response.ok) {
      try {
        const data = await response.clone().json();
        window.__tablekeeperPolishRestaurantId = data.restaurant_id;
        reservationsByReference.set(data.reference, data);
      } catch (_) {}
    }
    return response;
  };

  const trackedFetch = window.fetch;
  window.fetch = async (...args) => {
    const request = args[0];
    const url = new URL(typeof request === 'string' ? request : request.url, location.href);
    const restaurantMatch = url.pathname.match(/^\/restaurants\/([^/]+)$/);
    const method = (args[1]?.method || (typeof request === 'string' ? 'GET' : request.method) || 'GET').toUpperCase();
    const canFallback = location.pathname === '/lookup' && restaurantMatch && method === 'GET';
    const fallback = () => {
      const id = decodeURIComponent(restaurantMatch[1]);
      unavailableRestaurants.add(id);
      tableLabels.set(id, new Map());
      restaurantZones.set(id, null);
      return new Response(JSON.stringify({id, name:'Restaurant details unavailable', timezone:null, tables:[]}), {status:200,headers:{'Content-Type':'application/json; charset=utf-8'}});
    };
    try {
      const response = await trackedFetch(...args);
      return canFallback && !response.ok ? fallback() : response;
    } catch (error) {
      if (canFallback) return fallback();
      throw error;
    }
  };

  retryRender = setInterval(() => {
    const panel = document.getElementById('history-panel');
    const detail = document.querySelector('[data-testid="reservation-detail"]');
    const reference = detail?.querySelector('code')?.textContent?.trim();
    const reservation = reservationsByReference.get(reference);
    if (reservation && window.__tablekeeperRestaurantDetailsUnavailable) {
      unavailableRestaurants.add(reservation.restaurant_id);
      tableLabels.set(reservation.restaurant_id, new Map());
      restaurantZones.set(reservation.restaurant_id, null);
    }
    if (detail && reservation && unavailableRestaurants.has(reservation.restaurant_id)) {
      const seating = detail.querySelector('[data-testid="reservation-tables"]');
      if (seating) seating.innerHTML = '<strong>Seating:</strong> Table label unavailable';
    }
    const restaurantId = reservation?.restaurant_id || window.__tablekeeperPolishRestaurantId;
    if (panel && reference && sourceEntries.has(reference) && panel.querySelector('.history-list')?.dataset.polished !== 'true') renderHistory(panel, reference, restaurantId);
  }, 250);
})();
