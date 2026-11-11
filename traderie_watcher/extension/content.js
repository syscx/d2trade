(() => {
  "use strict";
  const CARD_SELECTORS = [".offer-listing-item", ".listing-card", '[data-testid*="listing"]', '[class*="listing-card"]', '[class*="ListingCard"]'];
  const TITLE_SELECTOR = "a.listing-name.selling-listing";
  const MAX_CARDS_PER_SCAN = 100, MAX_TEXT_LENGTH = 4000;
  const sentFingerprints = new Set();
  let scanTimer = null, lastPageContext = "";
  const clean = value => (value || "").replace(/\s+/g, " ").trim().slice(0, MAX_TEXT_LENGTH);
  const isVisible = element => {
    if (!(element instanceof Element)) return false;
    const style=getComputedStyle(element), rect=element.getBoundingClientRect();
    return style.display!=="none" && style.visibility!=="hidden" && Number(style.opacity||1)>0 && rect.width>0 && rect.height>0 && rect.bottom>0 && rect.top<window.innerHeight;
  };
  function getPageContext() {
    const params=new URLSearchParams(location.search);
    const searchInput=document.querySelector('input[type="search"], input[placeholder*="Search" i], input[aria-label*="Search" i]');
    return {page_type:/\/items?\//i.test(location.pathname)?"item_or_listing":(params.size?"search_or_filtered":"traderie_page"),pathname:location.pathname,query:clean(params.toString()),search_text:clean(searchInput?.value||""),title:clean(document.title)};
  }
  function findListingCards() {
    const found=new Set();
    for(const selector of CARD_SELECTORS) document.querySelectorAll(selector).forEach(el=>{if(found.size<MAX_CARDS_PER_SCAN&&isVisible(el))found.add(el);});
    document.querySelectorAll(TITLE_SELECTOR).forEach(link=>{const card=link.closest(".offer-listing-item");if(card&&found.size<MAX_CARDS_PER_SCAN&&isVisible(card))found.add(card);});
    return [...found];
  }
  function extractTradeDetails(card,title) {
    const lines=(card.innerText||"").split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
    const theyIndex=lines.findIndex(x=>/^they give$/i.test(x));
    const iIndex=lines.findIndex(x=>/^i give$/i.test(x));
    const tradingIndex=lines.findIndex(x=>/^trading for\s*:?[ ]*$/i.test(x)||/^trading for\s*:/i.test(x));
    const ageIndex=lines.findIndex(x=>/^\d+\s+(?:seconds?|minutes?|hours?|days?|weeks?)\s+ago$/i.test(x));
    const end=ageIndex>=0?ageIndex:lines.length;
    if(theyIndex>=0||iIndex>=0){
      const giveLines=iIndex>=0?lines.slice(iIndex+1,end):[];
      const cleanGive=giveLines.filter(x=>!/^high rune value\s*:/i.test(x));
      const trade=clean(cleanGive.join(" | "))||null;
      return {record_type:"completed_sale_observation",transaction_status:"completed_sale_page_record",they_give_text:theyIndex>=0?(title||null):null,i_give_text:trade,observed_trade_text:trade,asking_price_text:null,price_reliability:"uncertain_possible_overstatement",price_note:"Traderie completed-sales page record; observed trade terms may not equal the true final deal value."};
    }
    if(tradingIndex>=0){
      const inline=lines[tradingIndex].replace(/^trading for\s*:?[ ]*/i,"");
      const terms=[inline,...lines.slice(tradingIndex+1,end)].filter(Boolean).filter(x=>!/^high rune value\s*:/i.test(x));
      const ask=clean(terms.join(" | "))||null;
      return {record_type:"active_listing_ask",transaction_status:"active_or_asking",they_give_text:title||null,i_give_text:null,observed_trade_text:ask,asking_price_text:ask,price_reliability:"seller_ask_not_sale",price_note:"Active listing request only; not a completed transaction."};
    }
    return {record_type:"unknown_listing_record",transaction_status:"unknown",they_give_text:null,i_give_text:null,observed_trade_text:null,asking_price_text:null,price_reliability:"unknown",price_note:"Trade direction could not be identified from visible labels."};
  }
  function extractListing(card){
    const text=clean(card.innerText||card.textContent); if(text.length<8)return null;
    const titleLink=card.querySelector(TITLE_SELECTOR),link=titleLink||card.querySelector("a[href*='/listing/']");
    const url=link?.href?new URL(link.href):null;
    const href=url&&url.protocol==="https:"&&["traderie.com","www.traderie.com"].includes(url.hostname)?url.pathname+url.search:null;
    let title="";
    if(titleLink){const clone=titleLink.cloneNode(true);clone.querySelectorAll(".listing-container").forEach(n=>n.remove());title=clean(clone.innerText||clone.textContent);}
    else if(link)title=clean(link.innerText||link.textContent);
    const details=extractTradeDetails(card,title);
    return {listing_key:href,listing_path:href,title:title.slice(0,300),listing_type:details.record_type,...details,visible_text:text,extraction_method:"trade_record_type_labels_v3"};
  }
  function send(payload){try{chrome.runtime.sendMessage({type:"TRADERIE_OBSERVATION",payload},()=>{void chrome.runtime.lastError;});}catch(error){/* Refresh this Traderie tab after reloading the extension. */}}
  function scan(){
    scanTimer=null; const context=getPageContext(),fingerprint=JSON.stringify(context);
    if(fingerprint!==lastPageContext){lastPageContext=fingerprint;send({observation_type:"page_context",page_context:context});}
    for(const card of findListingCards()){
      const listing=extractListing(card);if(!listing||!listing.listing_path)continue;
      const fp=JSON.stringify({path:listing.listing_path,title:listing.title,type:listing.record_type,they:listing.they_give_text,trade:listing.observed_trade_text,text:listing.visible_text});
      if(sentFingerprints.has(fp))continue;sentFingerprints.add(fp);
      send({observation_type:"listing_snapshot",page_context:context,listing});
    }
    if(sentFingerprints.size>5000)sentFingerprints.clear();
  }
  function scheduleScan(){if(scanTimer!==null)clearTimeout(scanTimer);scanTimer=setTimeout(scan,800);}
  const observer=new MutationObserver(scheduleScan);observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true});
  window.addEventListener("scroll",scheduleScan,{passive:true});window.addEventListener("popstate",scheduleScan);scheduleScan();
})();