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
      account.innerHTML='<a class="quiet-link" href="/login">Sign in</a><a class="quiet-link" href="/signup">Create account</a>';
      return;
    }
    account.innerHTML=`<span class="current-user" data-testid="current-user">${escapeHtml(s.display_name)}</span><button class="quiet-button" id="logout-button" data-testid="logout-button" type="button">Sign out</button>`;
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
    root.innerHTML=`<div class="auth-layout"><section class="auth-aside"><span class="eyebrow">A little more room for good things</span><h1>${signup?'Make room for a lovely evening.':'Welcome back to the table.'}</h1><p>Find a place you love, save your booking details, and keep every plan close at hand.</p></section><section class="auth-panel"><span class="eyebrow">${signup?'Join the table':'Your account'}</span><h1>${signup?'Create your account':'Sign in'}</h1><p class="panel-copy">${signup?'A few details, then the good part.':'Pick up where your next evening begins.'}</p><form class="stack-form" id="auth-form">${signup?'<div><label for="display-name">Your name</label><input id="display-name" data-testid="signup-display-name" autocomplete="name" required></div>':''}<div><label for="email">Email address</label><input id="email" data-testid="${signup?'signup':'login'}-email" type="email" autocomplete="email" required></div><div><label for="password">Password</label><input id="password" data-testid="${signup?'signup':'login'}-password" type="password" autocomplete="${signup?'new-password':'current-password'}" required></div><button class="primary-button" data-testid="${signup?'signup':'login'}-submit" type="submit">${signup?'Create account':'Sign in'}</button></form><p class="small-note">${signup?'Already have an account? <a href="/login">Sign in</a>':'New here? <a href="/signup">Create an account</a>'}</p></section></div>`;
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
    root.innerHTML=`<section class="lookup-panel"><span class="eyebrow">Your plans, close at hand</span><h1>Look up a booking</h1><p class="panel-copy">Enter the reference from your confirmation and we’ll bring up the details.</p>${session()?.token?'':'<p class="small-note"><a href="/login">Sign in</a> to view and manage your reservation.</p>'}<form class="lookup-form" id="lookup-form"><div><label for="lookup-reference">Booking reference</label><input id="lookup-reference" data-testid="lookup-reference-input" type="text" maxlength="12" autocomplete="off" required></div><button class="primary-button" data-testid="lookup-submit" type="submit">Find booking</button></form><div id="lookup-result"></div></section>`;
    const form=document.getElementById('lookup-form'), result=document.getElementById('lookup-result');
    const renderReservation=(reservation)=>{
      const ids=reservation.table_ids || (reservation.table_id?[reservation.table_id]:[]);
      api(`/restaurants/${encodeURIComponent(reservation.restaurant_id)}`).then(({data})=>{
        const labels=ids.map(id=>data.tables.find(t=>t.id===id)?.label||id);
        result.innerHTML=`<article class="reservation-detail" data-testid="reservation-detail"><span class="eyebrow">Your table is ${reservation.status==='confirmed'?'waiting':'released'}</span><h2>${escapeHtml(data.name)}</h2><p><span class="status-pill" data-testid="reservation-status">${escapeHtml(reservation.status)}</span></p><p><strong>When:</strong> ${escapeHtml(reservation.starts_at_local.replace('T',' at '))}</p><p data-testid="reservation-tables"><strong>Seating:</strong> ${labels.map(escapeHtml).join(' + ')}</p><p><strong>Reference:</strong> ${escapeHtml(reservation.reference)}</p>${reservation.status==='cancelled'?'':'<button class="primary-button" id="cancel-booking" type="button" data-testid="reservation-cancel-button">Cancel reservation</button>'}</article>`;
        const cancel=document.getElementById('cancel-booking');
        if(cancel) cancel.addEventListener('click',async()=>{
          hide(result,'reservation-error');cancel.disabled=true;
          try{const {response,data}=await api(`/reservations/${encodeURIComponent(reservation.reference)}/cancel`,{method:'POST'});if(!response.ok){show(result,'reservation-error',messageOf(data),'reservation-error');cancel.disabled=false;return;}renderReservation(data);}
          catch(error){show(result,'reservation-error',error.message,'reservation-error');cancel.disabled=false;}
        });
      }).catch(error=>show(result,'reservation-error',error.message,'reservation-error'));
    };
    form.addEventListener('submit',async event=>{
      event.preventDefault();result.replaceChildren();
      const ref=document.getElementById('lookup-reference').value.trim().toUpperCase();
      try{const {response,data}=await api(`/reservations/${encodeURIComponent(ref)}`);if(!response.ok){show(result,'reservation-error',messageOf(data),'reservation-error');return;}renderReservation(data);}
      catch(error){show(result,'reservation-error',error.message,'reservation-error');}
    });
    return;
  }

  if (path!=='/') { root.innerHTML='<section class="empty-state">We could not find that page. <a href="/">Find a table</a></section>';return; }
  root.innerHTML=`<section class="hero"><div><span class="eyebrow">A good evening begins with a seat</span><h1>Find your place<br>at the table.</h1><p>Discover a neighborhood favorite and make a little room for a meal worth remembering.</p></div><div class="hero-note">“There is always room for one more story.”</div></section><section class="search-panel" aria-label="Search for a table"><form class="search-controls" id="search-form"><div><label for="restaurant">Restaurant</label><select id="restaurant" data-testid="restaurant-select" required><option value="">Choose a restaurant</option></select></div><div><label for="date">Date</label><input id="date" data-testid="date-input" type="date" required></div><div><label for="party-size">Guests</label><input id="party-size" data-testid="party-size-input" type="number" min="1" step="1" value="2" required></div><button class="primary-button" data-testid="search-button" type="submit">Find a table</button></form></section><section id="availability-region" aria-live="polite"></section><section class="booking-panel" id="booking-panel" hidden></section>`;
  const restaurantSelect=document.getElementById('restaurant'),dateInput=document.getElementById('date'),partyInput=document.getElementById('party-size'),gridRegion=document.getElementById('availability-region'),bookingPanel=document.getElementById('booking-panel');
  const today=new Date();dateInput.value=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  let restaurantRows=[],restaurantCache=new Map(),sequence=0,lastSearch=null,selected=null,pending=null,confirmation=null;
  api('/restaurants').then(({data})=>{restaurantRows=data.restaurants||[];restaurantSelect.innerHTML='<option value="">Choose a restaurant</option>'+restaurantRows.map(r=>`<option value="${escapeHtml(r.id)}">${escapeHtml(r.name)}</option>`).join('');if(restaurantRows.length===1)restaurantSelect.value=restaurantRows[0].id;}).catch(error=>show(gridRegion,'search-error',error.message,'feedback error'));
  const details=async id=>{if(!restaurantCache.has(id)){const {response,data}=await api(`/restaurants/${encodeURIComponent(id)}`);if(!response.ok)throw new Error(messageOf(data));restaurantCache.set(id,data);}return restaurantCache.get(id);};
  const searchQuery=()=>({restaurant_id:restaurantSelect.value,date:dateInput.value,party_size:partyInput.value});
  const loadAvailability=async (query,searchSeq,fromConflict=false)=>{
    try{
      const {response,data}=await api(`/availability?restaurant_id=${encodeURIComponent(query.restaurant_id)}&date=${encodeURIComponent(query.date)}&party_size=${encodeURIComponent(query.party_size)}`);
      if(searchSeq!==sequence)return;
      if(!response.ok){gridRegion.innerHTML='';show(gridRegion,'search-error',messageOf(data),'feedback error');return;}
      const restaurant=await details(query.restaurant_id);if(searchSeq!==sequence)return;
      lastSearch={...query};renderGrid(data,restaurant);
      if(fromConflict)show(gridRegion,'search-note','Availability has been refreshed. Choose another seating option or retry after checking the updated choices.','feedback');
    }catch(error){if(searchSeq===sequence)show(gridRegion,'search-error',error.message,'feedback error');}
  };
  const renderGrid=(data,restaurant)=>{
    gridRegion.replaceChildren();hide(gridRegion,'search-error');hide(gridRegion,'search-note');
    if(!data.slots.length){show(gridRegion,'no-slots','There are no reservation times on this date. Try another day.','empty-state');return;}
    const heading=document.createElement('div');heading.className='section-heading';heading.innerHTML=`<div><span class="eyebrow">${escapeHtml(restaurant.name)}</span><h2>Available seatings</h2><p>${escapeHtml(data.date)} · ${escapeHtml(data.timezone)} · ${escapeHtml(data.slots.length)} times</p></div>`;gridRegion.append(heading);
    const grid=document.createElement('div');grid.className='availability-grid';grid.dataset.testid='availability-grid';
    const tableLabels=new Map(restaurant.tables.map(t=>[t.id,t.label]));
    const declaredPairs=restaurant.combinable||[];
    for(const slot of data.slots){const hm=slot.starts_at_local.slice(11,16);const availableSingles=new Set(slot.available_table_ids||[]);const optionKeys=new Set((slot.available_options||[]).map(o=>(o.table_ids||[]).join('\0')));
      for(const table of restaurant.tables){const ids=[table.id],ok=availableSingles.has(table.id);grid.append(makeCell(ids,[table.label],hm,ok,slot,restaurant));}
      for(const pair of declaredPairs){const key=pair.join('\0');const reverse=pair.slice().reverse().join('\0');const ok=optionKeys.has(key)||optionKeys.has(reverse);grid.append(makeCell(pair,pair.map(id=>tableLabels.get(id)||id),hm,ok,slot,restaurant));}
    }
    gridRegion.append(grid);
  };
  const makeCell=(ids,labels,hm,available,slot,restaurant)=>{
    const button=document.createElement('button');button.type='button';button.className='slot-cell';button.dataset.available=String(available);button.dataset.testid=`slot-${ids.join('+')}-${hm}`;button.disabled=!available;button.setAttribute('aria-label',`${labels.join(' and ')}, ${hm}, ${available?'available':'unavailable'}`);
    button.innerHTML=`<span class="slot-time">${escapeHtml(hm)}</span><span class="slot-label">${labels.map(escapeHtml).join(' + ')}</span><span class="slot-capacity">${available?'Available for '+escapeHtml(lastSearch.party_size)+' guests':'Not available'}</span>`;
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
    const labels=selected.labels;bookingPanel.innerHTML=`<div class="booking-top"><div><span class="eyebrow">Your evening, taking shape</span><h2>Complete your booking</h2><p class="booking-summary" data-testid="booking-summary">${escapeHtml(selected.restaurant_name)} · ${labels.map(escapeHtml).join(' + ')} · ${escapeHtml(selected.local.replace('T',' at '))}</p></div><span class="status-pill">${labels.length>1?'Together':'A table'}</span></div><form id="booking-form-inner"><div class="form-row"><label for="booking-size">Guests</label><input id="booking-size" data-testid="booking-party-size" type="number" min="1" step="1" value="${escapeHtml(selected.party_size)}" required></div><div id="booking-feedback"></div><div class="booking-actions"><button class="primary-button" type="submit" data-testid="booking-submit">Confirm booking</button><span class="small-note">Your table is held when your booking is confirmed.</span></div></form><div id="confirmation-region"></div>`;
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
    document.getElementById('confirmation-region').innerHTML=`<section class="confirmation" data-testid="confirmation"><div class="confirmation-title">Your table is confirmed</div><div class="confirmation-reference" data-testid="confirmation-reference">${escapeHtml(data.reference)}</div><div class="confirmation-details" data-testid="confirmation-details">${escapeHtml(selected.restaurant_name)} · ${labels.map(escapeHtml).join(' + ')} · ${escapeHtml(data.starts_at_local.replace('T',' at '))}</div><div class="confirmation-tables" data-testid="confirmation-tables">${labels.map(escapeHtml).join(' + ')}</div><a class="quiet-link" href="/lookup">View or manage this booking</a></section>`;
  };
})();
