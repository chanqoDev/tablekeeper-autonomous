(() => {
  const root = document.getElementById('main-content');
  const account = document.getElementById('account-area');
  const path = location.pathname;
  const session = () => {
    try { return JSON.parse(localStorage.getItem('tablekeeper-session') || 'null'); }
    catch (_) { return null; }
  };
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const api = async (url, options={}) => {
    const s = session();
    const headers = new Headers(options.headers || {});
    if (s?.token) headers.set('Authorization', `Bearer ${s.token}`);
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type','application/json');
    const response = await fetch(url,{...options,headers});
    let data;
    try { data = response.status === 204 ? null : await response.json(); }
    catch (_) { throw new Error('The server response could not be read.'); }
    return {response,data};
  };
  const messageOf = data => data?.error?.message || data?.error?.code || 'Please try again.';
  const setAccount = () => {
    const s=session();
    if (!s?.token) {
      account.innerHTML='<a class="quiet-link" href="/login">Sign in</a><a class="account-join" href="/signup">Join us</a>';
      return;
    }
    account.innerHTML=`<span class="current-user" data-testid="current-user"><span class="user-dot" aria-hidden="true"></span>${escapeHtml(s.display_name)}</span><button class="quiet-button" id="logout-button" data-testid="logout-button" type="button">Sign out</button>`;
    document.getElementById('logout-button').addEventListener('click',()=>{localStorage.removeItem('tablekeeper-session');location.href='/';});
  };
  const show = (host,id,text,kind='error') => {
    let node=host.querySelector(`[data-testid="${id}"]`);
    if (!node) { node=document.createElement('div');node.dataset.testid=id;node.className=kind;node.setAttribute('role','status');host.append(node); }
    node.textContent=text; return node;
  };
  const hide = (host,id) => host.querySelector(`[data-testid="${id}"]`)?.remove();
  setAccount();

  if (path==='/signup' || path==='/login') {
    const signup=path==='/signup';
    root.innerHTML=`<div class="auth-layout"><section class="auth-aside"><span class="eyebrow">MIDNIGHT PURR · GOOD EVENINGS, KEPT</span><div class="auth-orbit" aria-hidden="true"><span class="auth-moon"></span><span class="auth-cat">⌁</span><span class="auth-spark spark-one">✦</span><span class="auth-spark spark-two">✧</span></div><h1>${signup?'Make room for a lovely evening.':'Your table is waiting.'}</h1><p>Find a neighborhood favorite, settle in, and keep the little details close.</p></section><section class="auth-panel"><span class="eyebrow">${signup?'A seat with your name on it':'Good to see you again'}</span><h2>${signup?'Create your account':'Sign in'}</h2><p class="panel-copy">${signup?'A few details, then the good part.':'Pick up where your next evening begins.'}</p><form class="stack-form" id="auth-form">${signup?'<div><label for="display-name">Your name</label><input id="display-name" data-testid="signup-display-name" type="text" autocomplete="name" required></div>':''}<div><label for="email">Email address</label><input id="email" data-testid="${signup?'signup':'login'}-email" type="email" autocomplete="email" required></div><div><label for="password">Password</label><input id="password" data-testid="${signup?'signup':'login'}-password" type="password" autocomplete="${signup?'new-password':'current-password'}" required></div><button class="primary-button" data-testid="${signup?'signup':'login'}-submit" type="submit">${signup?'Create account':'Sign in'}</button></form><p class="small-note">${signup?'Already have an account? <a href="/login">Sign in</a>':'New here? <a href="/signup">Create an account</a>'}</p></section></div>`;
    const form=document.getElementById('auth-form');
    form.addEventListener('submit',async event=>{
      event.preventDefault();hide(form,'auth-error');
      const body={email:document.getElementById('email').value,password:document.getElementById('password').value};
      if(signup) body.display_name=document.getElementById('display-name').value;
      const button=form.querySelector('button');button.disabled=true;
      try{
        const {response,data}=await api(signup?'/auth/signup':'/auth/login',{method:'POST',body:JSON.stringify(body)});
        if(!response.ok){show(form,'auth-error',messageOf(data),'auth-error');return;}
        localStorage.setItem('tablekeeper-session',JSON.stringify({token:data.token,user_id:data.user_id,display_name:data.display_name}));
        location.href='/';
      }catch(error){show(form,'auth-error',error.message,'auth-error');}
      finally{button.disabled=false;}
    });
    return;
  }

  if (path==='/lookup') {
    root.innerHTML=`<section class="lookup-panel"><span class="eyebrow">YOUR PLANS · SAFE AND SOUND</span><h1>Find your booking</h1><p class="panel-copy">Enter the reference from your confirmation to see your table and manage your plans.</p>${session()?.token?'':'<p class="auth-hint"><span aria-hidden="true">✦</span> <a href="/login">Sign in</a> to view and manage your reservation.</p>'}<form class="lookup-form" id="lookup-form"><div><label for="lookup-reference">Booking reference</label><input id="lookup-reference" data-testid="lookup-reference-input" type="text" maxlength="12" autocomplete="off" placeholder="e.g. M7K4QP" required></div><button class="primary-button" data-testid="lookup-submit" type="submit"><span>Find my booking</span><span aria-hidden="true">→</span></button></form><div id="lookup-result"></div></section>`;
    const form=document.getElementById('lookup-form'), result=document.getElementById('lookup-result');
    let lookupSequence=0,pendingSeries=null;
    const renderReservation=(reservation)=>{
      const ids=reservation.table_ids || (reservation.table_id?[reservation.table_id]:[]);
      const sequenceAtRender=++lookupSequence;
      api(`/restaurants/${encodeURIComponent(reservation.restaurant_id)}`).then(({data})=>{
        if(sequenceAtRender!==lookupSequence)return;
        const labels=ids.map(id=>data.tables.find(t=>t.id===id)?.label||id);
        result.innerHTML=`<article class="reservation-detail" data-testid="reservation-detail"><div class="reservation-topline"><span class="eyebrow">YOUR EVENING</span><span class="status-pill" data-testid="reservation-status">${escapeHtml(reservation.status)}</span></div><h2>${escapeHtml(data.name)}</h2><p class="reservation-when"><span aria-hidden="true">☾</span> ${escapeHtml(reservation.starts_at_local.replace('T',' at '))}</p><p data-testid="reservation-tables"><strong>Seating:</strong> ${labels.map(escapeHtml).join(' + ')}</p><p><strong>Reference:</strong> <code>${escapeHtml(reservation.reference)}</code></p><p class="reservation-terms"><strong>Accepted policy v${escapeHtml(reservation.accepted_terms?.policy_version??0)}:</strong> ${escapeHtml(reservation.accepted_terms?.reservation_duration_minutes??'')} minute seating · ${escapeHtml(reservation.accepted_terms?.cancellation_cutoff_minutes??'')} minute cancellation cutoff.</p><section class="history-panel" id="history-panel" aria-live="polite"><h3>Reservation history</h3><p class="small-note">Loading the story of this booking…</p></section>${reservation.status==='confirmed'?`<form class="series-form" id="series-form"><h3>Make it a regular evening</h3><p class="small-note">Keep the same table and time on a weekly or monthly rhythm.</p><div class="series-fields"><div><label for="series-count">Number of visits</label><input id="series-count" type="number" min="2" max="12" value="4" required></div><div><label for="series-interval">Every (weeks)</label><input id="series-interval" type="number" min="1" max="4" value="1" required></div></div><button class="secondary-button" type="submit">Create recurring series</button><div id="series-feedback"></div></form>`:''}${reservation.status==='cancelled'?'':'<button class="secondary-button" id="cancel-booking" type="button" data-testid="reservation-cancel-button">Cancel reservation</button>'}</article>`;
        const historyPanel=document.getElementById('history-panel');
        api(`/reservations/${encodeURIComponent(reservation.reference)}/history`).then(({response,data})=>{
          if(sequenceAtRender!==lookupSequence)return;
          if(!response.ok){historyPanel.innerHTML=`<p class="small-note">${escapeHtml(messageOf(data))}</p>`;return;}
          const entries=data.entries||[];
          historyPanel.innerHTML=entries.length?`<h3>Reservation history</h3><ol class="history-list">${entries.map(entry=>`<li><div class="history-heading"><strong>${escapeHtml(entry.event)}</strong><span>Revision ${escapeHtml(entry.revision)}</span></div><time>${escapeHtml(entry.at.replace('T',' · '))}</time><ul>${entry.changes.map(change=>`<li><span>${escapeHtml(change.field.replaceAll('_',' '))}</span>${change.from===null?'':` <span>${escapeHtml(JSON.stringify(change.from))} →</span>`} <span>${escapeHtml(JSON.stringify(change.to))}</span></li>`).join('')}</ul><details><summary>Accepted terms · policy v${escapeHtml(entry.accepted_terms.policy_version)}</summary><pre>${escapeHtml(JSON.stringify(entry.accepted_terms,null,2))}</pre></details></li>`).join('')}</ol>`:'<h3>Reservation history</h3><p class="small-note">No changes have been recorded yet.</p>';
        }).catch(()=>{if(sequenceAtRender===lookupSequence)historyPanel.innerHTML='<h3>Reservation history</h3><p class="small-note">History is temporarily unavailable.</p>';});
        const cancel=document.getElementById('cancel-booking');
        if(cancel) cancel.addEventListener('click',async()=>{
          hide(result,'reservation-error');cancel.disabled=true;
          try{const {response,data}=await api(`/reservations/${encodeURIComponent(reservation.reference)}/cancel`,{method:'POST'});if(!response.ok){show(result,'reservation-error',messageOf(data),'reservation-error');cancel.disabled=false;return;}renderReservation(data);}
          catch(error){show(result,'reservation-error',error.message,'reservation-error');cancel.disabled=false;}
        });
        const seriesForm=document.getElementById('series-form');
        if(seriesForm)seriesForm.addEventListener('submit',async event=>{
          event.preventDefault();const body={anchor_reference:reservation.reference,count:Number(document.getElementById('series-count').value),interval_weeks:Number(document.getElementById('series-interval').value)};const canonical=JSON.stringify(body);
          if(!pendingSeries||pendingSeries.canonical!==canonical)pendingSeries={canonical,key:(crypto.randomUUID?.()||`${Date.now()}-${Math.random()}`)};
          const feedback=document.getElementById('series-feedback');hide(feedback,'series-error');hide(feedback,'series-uncertain');const button=seriesForm.querySelector('button');button.disabled=true;
          try{const {response,data}=await api('/series',{method:'POST',headers:{'Idempotency-Key':pendingSeries.key},body:JSON.stringify(body)});if(!response.ok){show(feedback,'series-error',messageOf(data),'booking-error');button.disabled=false;return;}feedback.innerHTML=`<section class="series-result" data-testid="series-result"><h4>Recurring visits saved</h4><ol>${data.occurrences.map(occurrence=>`<li>Visit ${escapeHtml(occurrence.index+1)} · ${escapeHtml(occurrence.reservation.starts_at_local.replace('T',' at '))} · <code>${escapeHtml(occurrence.reference)}</code></li>`).join('')}</ol></section>`;}
          catch(error){show(feedback,'series-uncertain','We could not confirm whether the series was saved. Retry these same details to recover the original result.','booking-uncertain');}
          finally{button.disabled=false;}
        });
      }).catch(error=>show(result,'reservation-error',error.message,'reservation-error'));
    };
    form.addEventListener('submit',async event=>{
      event.preventDefault();result.replaceChildren();lookupSequence++;pendingSeries=null;
      const ref=document.getElementById('lookup-reference').value.trim().toUpperCase();
      try{const {response,data}=await api(`/reservations/${encodeURIComponent(ref)}`);if(!response.ok){show(result,'reservation-error',messageOf(data),'reservation-error');return;}renderReservation(data);}
      catch(error){show(result,'reservation-error',error.message,'reservation-error');}
    });
    return;
  }

  if (path!=='/') { root.innerHTML='<section class="empty-state">We could not find that page. <a href="/">Find a table</a></section>';return; }
  root.innerHTML=`<section class="hero"><div class="hero-copy"><span class="eyebrow">TABLES FOR THE MOONLIT HOUR</span><h1>Good food.<br><span>Soft lights.</span></h1><p>Find a neighborhood favorite and make room for a meal worth keeping.</p><div class="hero-note"><span aria-hidden="true">✦</span> Thoughtful tables, lovely evenings</div></div><div class="hero-art" aria-hidden="true"><span class="hero-orbit"></span><span class="hero-moon"></span><span class="hero-cat"><i></i></span><span class="hero-star star-a">✦</span><span class="hero-star star-b">✧</span><span class="hero-star star-c">·</span><span class="hero-caption">A LITTLE MAGIC<br>AT EVERY TABLE</span></div></section><section class="search-panel" aria-label="Search for a table"><div class="panel-heading"><div><span class="eyebrow">01 · FIND YOUR EVENING</span><h2>Where shall we save you a seat?</h2></div><span class="panel-flourish" aria-hidden="true">✦</span></div><form class="search-controls" id="search-form"><div><label for="restaurant">Restaurant</label><select id="restaurant" data-testid="restaurant-select" required><option value="">Choose a restaurant</option></select></div><div><label for="date">Date</label><input id="date" data-testid="date-input" type="date" required></div><div><label for="party-size">Guests</label><input id="party-size" data-testid="party-size-input" type="number" min="1" step="1" value="2" required></div><label class="explain-toggle"><input id="explain-seatings" type="checkbox"> Explain unavailable tables</label><button class="primary-button" data-testid="search-button" type="submit"><span>Find a table</span><span aria-hidden="true">→</span></button></form></section><section id="availability-region" aria-live="polite"></section><section class="booking-panel" id="booking-panel" hidden></section>`;
  const restaurantSelect=document.getElementById('restaurant'),dateInput=document.getElementById('date'),partyInput=document.getElementById('party-size'),gridRegion=document.getElementById('availability-region'),bookingPanel=document.getElementById('booking-panel');
  const today=new Date();dateInput.value=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  let restaurantRows=[],restaurantCache=new Map(),sequence=0,lastSearch=null,selected=null,pending=null,confirmation=null;
  api('/restaurants').then(({data})=>{restaurantRows=data.restaurants||[];restaurantSelect.innerHTML='<option value="">Choose a restaurant</option>'+restaurantRows.map(r=>`<option value="${escapeHtml(r.id)}">${escapeHtml(r.name)}</option>`).join('');if(restaurantRows.length===1)restaurantSelect.value=restaurantRows[0].id;}).catch(error=>show(gridRegion,'search-error',error.message,'feedback error'));
  const details=async id=>{if(!restaurantCache.has(id)){const {response,data}=await api(`/restaurants/${encodeURIComponent(id)}`);if(!response.ok)throw new Error(messageOf(data));restaurantCache.set(id,data);}return restaurantCache.get(id);};
  const searchQuery=()=>({restaurant_id:restaurantSelect.value,date:dateInput.value,party_size:partyInput.value,explain:document.getElementById('explain-seatings').checked});
  const loadAvailability=async (query,searchSeq,fromConflict=false)=>{
    try{
      const explainParam=query.explain?'&explain=true':'';
      const {response,data}=await api(`/availability?restaurant_id=${encodeURIComponent(query.restaurant_id)}&date=${encodeURIComponent(query.date)}&party_size=${encodeURIComponent(query.party_size)}${explainParam}`);
      if(searchSeq!==sequence)return;
      if(!response.ok){gridRegion.innerHTML='';show(gridRegion,'search-error',messageOf(data),'feedback error');return;}
      const restaurant=await details(query.restaurant_id);if(searchSeq!==sequence)return;
      lastSearch={...query};renderGrid(data,restaurant);
      if(fromConflict)show(gridRegion,'search-note','Availability has been refreshed. Choose another seating option or retry after checking the updated choices.','feedback');
    }catch(error){if(searchSeq===sequence)show(gridRegion,'search-error',error.message,'feedback error');}
  };
  const renderGrid=(data,restaurant)=>{
    gridRegion.replaceChildren();hide(gridRegion,'search-error');hide(gridRegion,'search-note');
    if(!data.slots.length){show(gridRegion,'no-slots','No seatings on this date. Try another evening and we’ll look again.','empty-state');return;}
    const heading=document.createElement('div');heading.className='section-heading';heading.innerHTML=`<div><span class="eyebrow">02 · THE EVENING AWAITS</span><h2>${escapeHtml(restaurant.name)}</h2><p>${escapeHtml(data.date)} <span aria-hidden="true">·</span> ${escapeHtml(data.timezone)} <span aria-hidden="true">·</span> ${escapeHtml(data.slots.length)} seatings</p></div><span class="section-mark" aria-hidden="true">✦</span>`;gridRegion.append(heading);
    const grid=document.createElement('div');grid.className='availability-grid';grid.dataset.testid='availability-grid';
    const tableLabels=new Map(restaurant.tables.map(t=>[t.id,t.label]));
    const declaredPairs=restaurant.combinable||[];
    for(const slot of data.slots){const hm=slot.starts_at_local.slice(11,16);const availableSingles=new Set(slot.available_table_ids||[]);const optionKeys=new Set((slot.available_options||[]).map(o=>(o.table_ids||[]).join('\0')));const reasons=new Map((slot.explain||[]).map(row=>[row.table_id,row]));
      for(const table of restaurant.tables){const ids=[table.id],ok=availableSingles.has(table.id);grid.append(makeCell(ids,[table.label],hm,ok,slot,restaurant,explanationReason(ids,reasons,lastSearch.explain)));}
      for(const pair of declaredPairs){const key=pair.join('\0');const reverse=pair.slice().reverse().join('\0');const ok=optionKeys.has(key)||optionKeys.has(reverse);grid.append(makeCell(pair,pair.map(id=>tableLabels.get(id)||id),hm,ok,slot,restaurant,explanationReason(pair,reasons,lastSearch.explain)));}
    }
    gridRegion.append(grid);
  };
  const explanationReason=(ids,reasons,explain)=>{
    if(!explain)return '';
    if(ids.length===1&&reasons.get(ids[0])?.rules?.find(rule=>rule.rule==='capacity')?.holds===false)return 'Capacity is too small for this party';
    if(ids.some(id=>reasons.get(id)?.rules?.find(rule=>rule.rule==='no_overlap')?.holds===false))return 'A table in this seating is already reserved';
    return 'Capacity is too small for this party';
  };
  const makeCell=(ids,labels,hm,available,slot,restaurant,reason)=>{
    const button=document.createElement('button');button.type='button';button.className='slot-cell';button.dataset.available=String(available);button.dataset.testid=`slot-${ids.join('+')}-${hm}`;button.disabled=!available;button.setAttribute('aria-label',`${labels.join(' and ')}, ${hm}, ${available?'available':'unavailable'}`);
    button.innerHTML=`<span class="slot-time">${escapeHtml(hm)}</span><span class="slot-label">${labels.map(escapeHtml).join(' + ')}</span><span class="slot-capacity"><span class="availability-dot" aria-hidden="true"></span>${available?'Available for '+escapeHtml(lastSearch.party_size)+' guests':'Not available'}</span>${!available&&reason?`<span class="slot-reason">${escapeHtml(reason)}</span>`:''}`;
    if(available)button.addEventListener('click',async()=>{
      selected={ids:[...ids],labels:[...labels],local:slot.starts_at_local,restaurant_id:restaurant.id,restaurant_name:restaurant.name,slot,party_size:Number(lastSearch.party_size)};
      if(!session()?.token){show(gridRegion,'auth-error','Sign in to reserve this seating.','feedback error');setTimeout(()=>{location.href='/login';},500);return;}
      confirmation=null;renderBooking();bookingPanel.scrollIntoView({behavior:'smooth',block:'center'});
    });
    return button;
  };
  document.getElementById('search-form').addEventListener('submit',event=>{
    event.preventDefault();const query=searchQuery();if(!query.restaurant_id||!query.date||!/^\d+$/.test(query.party_size)||Number(query.party_size)<1)return;
    sequence+=1;const current=sequence;lastSearch={...query};selected=null;confirmation=null;bookingPanel.hidden=true;gridRegion.replaceChildren();show(gridRegion,'search-loading','Finding a table…','empty-state');loadAvailability(query,current);
  });
  const currentPayload=()=>{
    if(!selected)return null;
    const payload={restaurant_id:selected.restaurant_id,starts_at_local:selected.local,party_size:Number(document.querySelector('[data-testid="booking-party-size"]')?.value||selected.party_size)};
    // Keep the Stage 1 singleton request shape so a saved Stage 1 receipt can be retried after import.
    if(selected.ids.length===1)payload.table_id=selected.ids[0];else payload.table_ids=[...selected.ids];
    return payload;
  };
  const bookingKey=payload=>{
    const canonical=JSON.stringify(payload);
    if(!pending||pending.canonical!==canonical)pending={canonical,key:(crypto.randomUUID?.()||`${Date.now()}-${Math.random()}`),payload:JSON.parse(canonical)};
    return pending;
  };
  const renderBooking=()=>{
    if(!selected){bookingPanel.hidden=true;return;}bookingPanel.hidden=false;
    const labels=selected.labels;bookingPanel.innerHTML=`<div class="booking-top"><div><span class="eyebrow">03 · YOUR SEAT, YOUR EVENING</span><h2>Make it yours</h2><p class="booking-summary" data-testid="booking-summary">${escapeHtml(selected.restaurant_name)} <span aria-hidden="true">·</span> ${labels.map(escapeHtml).join(' + ')} <span aria-hidden="true">·</span> ${escapeHtml(selected.local.replace('T',' at '))}</p></div><span class="status-pill">${labels.length>1?'Together':'A table'}</span></div><form id="booking-form-inner"><div class="form-row"><label for="booking-size">How many guests?</label><input id="booking-size" data-testid="booking-party-size" type="number" min="1" step="1" value="${escapeHtml(selected.party_size)}" required></div><div id="booking-feedback"></div><div class="booking-actions"><button class="primary-button" type="submit" data-testid="booking-submit"><span>Confirm this table</span><span aria-hidden="true">→</span></button><span class="small-note">Your booking is confirmed when you see its reference.</span></div></form><div id="confirmation-region"></div>`;
    const partyField=document.getElementById('booking-size');partyField.addEventListener('input',()=>{if(confirmation){confirmation=null;document.querySelector('[data-testid="confirmation"]')?.remove();}});
    const form=document.getElementById('booking-form-inner'),feedback=document.getElementById('booking-feedback');form.dataset.testid='booking-form';
    form.addEventListener('submit',async event=>{
      event.preventDefault();const payload=currentPayload();const request=bookingKey(payload);hide(feedback,'booking-error');hide(feedback,'booking-uncertain');const submit=form.querySelector('button');submit.disabled=true;
      try{
        const {response,data}=await api('/reservations',{method:'POST',headers:{'Idempotency-Key':request.key},body:JSON.stringify(request.payload)});
        if(!response.ok){show(feedback,'booking-error',messageOf(data),'booking-error');if(data?.error?.code==='table_unavailable'&&lastSearch){sequence+=1;loadAvailability({...lastSearch},sequence,true);}submit.disabled=false;return;}
        confirmation=data;renderConfirmation(data);
      }catch(error){show(feedback,'booking-uncertain','We couldn’t confirm whether the booking was saved. Retry with the same details to safely recover the result.','booking-uncertain');}
      finally{submit.disabled=false;}
    });
    if(confirmation)renderConfirmation(confirmation);
  };
  const renderConfirmation=data=>{
    const ids=data.table_ids||(data.table_id?[data.table_id]:selected.ids);const labels=ids.map((id,i)=>selected.ids.includes(id)?selected.labels[selected.ids.indexOf(id)]:id);
    document.getElementById('confirmation-region').innerHTML=`<section class="confirmation" data-testid="confirmation"><div class="confirmation-topline"><span class="confirmation-icon" aria-hidden="true">✦</span><span class="confirmation-title">You’re all set</span><span class="confirmation-icon" aria-hidden="true">✦</span></div><p class="confirmation-kicker">YOUR EVENING IS BOOKED</p><div class="confirmation-reference" data-testid="confirmation-reference">${escapeHtml(data.reference)}</div><div class="confirmation-details" data-testid="confirmation-details">${escapeHtml(selected.restaurant_name)} · ${labels.map(escapeHtml).join(' + ')} · ${escapeHtml(data.starts_at_local.replace('T',' at '))}</div><div class="confirmation-tables" data-testid="confirmation-tables">${labels.map(escapeHtml).join(' + ')}</div><a class="quiet-link" href="/lookup">View or manage this booking <span aria-hidden="true">→</span></a></section>`;
  };
})();
