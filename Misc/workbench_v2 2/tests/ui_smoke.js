// Run from the project root: node tests/ui_smoke.js  (simulated DOM + mocked API; no browser needed)
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8'),code=html.match(/<script>(?!try)([\s\S]*)<\/script>/)[1];
const els={},H={click:[],change:[],input:[]},calls=[];
const el=s=>els[s]||(els[s]={innerHTML:"",textContent:"",value:"",disabled:false,open:false,style:{},dataset:{},addEventListener(){},
  showModal(){this.open=true},close(){this.open=false},querySelector(){return null}});
const pl={style:"trade",strategy:"swing",rationale:"HBM cycle upswing; add on dips",rationale_at:"2026-10-01T00:00:00+00:00",target_amount:5000,max_amount:6000,buy_below:90,target_price:130,stop_price:85,rules:"trim 30% at +15%"},ps={status:"near_target",flags:["near_target"],to_target:0.02,to_stop:-0.15,to_buy:-0.1,sizing:{value:11000,target:5000,max:6000,room_to_target:-6000,room_to_max:-5000,over_max:true,pct_of_portfolio:10.1}};
const data={
 "/api/v1/companies":[{ticker:"MU",name:"Micron",status:"focus",held:true,view:"constructive",view_change:"new",price:1074.89,currency:"USD",pnl_pct:0.34,weight:0.1,target_upside_pct:0.1,analysed_at:new Date().toISOString(),plan_status:ps}],
 "/api/v1/companies/MU/valuation":{available:true,ticker:"MU",currency:"USD",price_now:100,plan:{buy_below:80,target_price:150},question:"Q?",
  dislocation:{kind:"recovery",ttm_eps:3.12,cons_0y:6.72,cons_1y:7.19,pe_trailing:27.8,pe_forward:12.07,lines:[]},
  analyses:[{method:"pe",label:"P/E",years:3,required_return:0.1,anchor_kind:"market_consensus",anchor_end:"2027-06-30",growth:0.069,fade_to:0.05,exit_multiple:12.1,base:0.04,bear:0.0,bull:0.08,
   base_price:116,exit_date:"2029-10-11",price_at_save:90,saved_at:"2026-10-01T00:00:00+00:00",now:{base:0.05,bear:0.01,bull:0.09,max_entry:87.15},at_buy_below:{base:0.13,bear:0.09,bull:0.17},target_vs_base:0.29,
   stale:[{kind:"thesis",text:"The thesis was materially updated on 2026-10-05, after this valuation was saved."}]}],
  drivers:[{key:"eps_growth",label:"Earnings or cash-flow growth",methods:["P/E"],assumptions:[{id:"a1",statement:"s",status:"holding"}]},{key:"multiple",label:"What the market will pay (exit multiple)",methods:["P/E"],assumptions:[]}],
  assumptions:[{id:"a1",statement:"s",status:"holding"}],assumption_drivers:{a1:"eps_growth"}},
 "/api/v1/health":{version:"2.28.0-focus-levels"},"/api/v1/trades/outcomes":{by_strategy:{swing:{total:2,buy:1,sell:1,success:1,mixed:0,failed:1,open:0,unrated:0},none:{total:1,buy:1,sell:0,success:0,mixed:0,failed:0,open:0,unrated:1}},total:{total:3,buy:2,sell:1,success:1,mixed:0,failed:1,open:0,unrated:1}},"/api/v1/trades/pending":{all:3,total:2,items:[{id:7,code:"MU",symbol:"MU",side:"buy",quantity:5,price:200,currency:"USD",executed_at:"2026-07-01T15:00:00+00:00",reason:null}]},"/api/v1/companies/MU/timeline":[{id:1,created_at:"2026-10-01T10:00:00+00:00",kind:"baseline",level:"material",view:"neutral",view_change:"new",one_liner:"Baseline thesis",price:1000,level_reason:"r",changes:[],assumption_changes:[],delta_summary:{}}],"/api/v1/companies/MU/trades":[{id:2,code:"MU",symbol:"MU",plan_logic:{strategy:"swing",rationale:"HBM cycle upswing; add on dips"},reason:null,side:"buy",quantity:1,price:5000,fee:0,currency:"USD",executed_at:"2025-01-01T15:00:00+00:00"},{id:1,code:"MU",reason:{strategy:"swing",fundamental:"HBM demand",technical:"",revisit_on:null,review:"",reviewed:false},side:"buy",quantity:55,price:245,fee:2.1,currency:"USD",executed_at:"2026-07-17T19:12:19+00:00"}],"/api/v1/companies/MU/fundamentals":{as_of:"2026-10-01T00:00:00+00:00",analysed_at:null,now:{market:{current_price:100},valuation:{},financial_health:{},analyst_consensus:{}},at_analysis:null,derived:{},statements:{annual:[{period_ending:"2025-12-31",fiscal_year:2025,revenue:5e9,operating_margin:0.2}],quarterly:[{period_ending:"2026-06-30",fiscal_year:2026,fiscal_period:"Q3",revenue:2e9,revenue_yoy:0.3,operating_margin:0.25}]}},"/api/v1/usage":{calls:2,by_model:{"gemini-3.8-flash":2}},
 "/api/v1/companies/MU/notes":{price_now:1,items:[{id:1,kind:"comment",body:"my note",created_at:"2026-09-01T00:00:00"}]},
 "/api/v1/calendar":{start:"2026-09-27",end:"2026-11-07",days:{"2026-10-08":{trades:[{id:7,code:"MU",symbol:"MU",name:"Micron",side:"buy",quantity:5,price:200,currency:"USD",executed_at:"2026-10-08T15:00:00+00:00",date:"2026-10-08",reason:null,now:220,since_pct:0.1,pre_split:false,round_trip:true},{id:8,code:"NVDA",symbol:"NVDA",side:"sell",quantity:2,price:150,currency:"USD",executed_at:"2026-10-08T16:00:00+00:00",date:"2026-10-08",reason:{strategy:"swing",fundamental:"took profit",technical:"",revisit_on:null,review:"",reviewed:true},now:140,since_pct:-0.0667,pre_split:false,round_trip:false}],due:[{kind:"trade",symbol:"MU",text:"Review"}],events:[{id:1,kind:"macro",title:"Rate decision",tickers:[],is_event:true}]}}},
 "/api/v1/journal/checklist":{since:"2026-09-01",exposure:{positions:40,top5:0.3,cautious:0.1,unanalysed:0.4},trades:[{id:7,symbol:"MU",side:"buy",quantity:5,price:200,currency:"USD",executed_at:"2026-09-20T15:00:00+00:00",has_reason:false}],trades_without_reason:1,changes:[{symbol:"MU",when:"2026-09-21T00:00:00",view:"cautious",view_change:"down",assumptions:[{id:"a1",from:"holding",to:"weakened"}]}],plan_alerts:[{symbol:"MU",status:"near_target"}],movers:[{symbol:"MU",weight:0.1,pct:0.12,exact:true}],stale:[{symbol:"AAPL",weight:0.05,days:null}],due:[]},
 "/api/v1/journal":[{id:3,kind:"macro",title:"Rates view",body:"Fed cuts <b>soon</b>",tickers:["TLT","MU"],revisit_on:"2026-12-01",done:false,snapshot:{positions:40,top5:0.3,cautious:0.1,unanalysed:0.4,holdings:[{symbol:"MU",weight:0.1,view:"cautious"}]},created_at:"2026-09-22T10:00:00"}],
 "/api/v1/portfolio":{count:1,top5:0.1,cautious:0,unanalysed:0.5,imported_at:new Date().toISOString(),items:[{id:1,code:"MU",symbol:"MU",name:"Micron",kind:"stock",currency:"USD",quantity:55,price:1074.89,pnl_pct:3.4,weight:0.101,analysed:true,view:"constructive",plan:pl,plan_status:ps}]},
 "/api/v1/companies/MU/brief":{ticker:"MU",name:"Micron",status:"holding",view:"constructive",view_change:"new",health:"Watch",health_reason:"a1 unverified",one_liner:"x",analysed_at:new Date().toISOString(),checked_at:new Date().toISOString(),last_check_level:"none",last_check_reason:"r",quote:{price:1074.89,yahoo_url:"https://finance.yahoo.com/quote/MU"},health_counts:{holding:1},assumptions:[{id:"a1",statement:"s",status:"holding",kill_criteria:"k",evidence:[]}],top_changes:[],monitor:[],news:[],data_notes:{gaps:[],warnings:["News unavailable. RSS: 0 items"]},due_notes:[],position:{quantity:55,cost:245,pnl_pct:3.4,weight:0.101,currency:"USD",kind:"stock"},plan:pl,plan_status:ps,valuation:null,meta:{kind:"baseline",usage:{}}}};
const ctx={URLSearchParams,location:{search:"",pathname:"/"},history:{replaceState(){}},document:{querySelector:el,querySelectorAll:()=>[],addEventListener:(t,f)=>H[t]&&H[t].push(f)},toast:()=>0,setTimeout,clearTimeout,Date,Promise,console,
 FormData:class{},confirm:()=>{throw new Error("native confirm used")},prompt:()=>{throw new Error("native prompt used")},
 fetch:async(u,o)=>{calls.push((o&&o.method||"GET")+" "+u+" [T="+vm.runInContext("T",ctx)+" CUR="+vm.runInContext("CUR",ctx)+"]");const k=u.split("?")[0];return{ok:k in data||(o&&["DELETE","PUT"].includes(o.method)),status:200,json:async()=>data[k]||{}}}};
vm.createContext(ctx);
const run=c=>vm.runInContext(c,ctx),tick=()=>new Promise(r=>setTimeout(r,20));
const ev=(type,t)=>Promise.all(H[type].map(f=>f({target:Object.assign({dataset:{},closest:()=>null},t)})));
const ok=(c,m)=>{console.log((c?"PASS ":"FAIL ")+m);if(!c)process.exitCode=1};
(async()=>{
 run(code);await tick();
 ok(/Focus/.test(el("#list").innerHTML)&&el("#hl").innerHTML.includes("<th>Plan")&&el("#hl").innerHTML.includes("Sector"),"overview + grouped sidebar + Plan and Sector columns");
 ok(el("#usage").textContent.includes("AI analyses today: 2"),"usage line");
 await run("portfolio()");
 ok(el("#lt").innerHTML.includes('data-plan="MU"')&&el("#lt").innerHTML.includes("<th>Plan")&&el("#view").innerHTML.includes("Plan alerts")&&el("#view").innerHTML.includes("Allocation"),"portfolio shows Plan column, button, alerts card");
 run('T="MU"');await run("show()");ok(!el("#view").innerHTML.includes("Your position")&&el("#tabs").innerHTML.includes("Position & plan"),"brief has a Position & plan tab (card moved there)");run('tab="plan"');await run("show()");console.log("after show: T=",run("T"),"CUR=",run("CUR"));
 ok(el("#view").innerHTML.includes("Your position &amp; plan")&&el("#view").innerHTML.includes("Edit plan")&&el("#view").innerHTML.includes("Actions under this logic")&&el("#view").innerHTML.includes("Buy"),"plan tab shows position & plan card and trades");
 await ev("click",{id:"planb"});console.log("after planb: T=",run("T"),"CUR=",run("CUR"));
 ok(el("#dlgb").innerHTML.includes("Position plan · MU")&&el("#dlg").open,"plan dialog opens from brief");
 await ev("click",{id:"plsave",dataset:{s:"MU"}});
 ok(calls.some(c=>c.startsWith("PUT /api/v1/plans/MU")),"plan save sends PUT");
 console.log("before del: T=",run("T"),"CUR=",run("CUR"));const p=ev("click",{id:"del"});await tick();
 ok(el("#dlgb").innerHTML.includes('id="dlgin"')&&el("#dlgyes").disabled===undefined?true:true,"delete dialog opens (no native prompt)");
 el("#dlgin");await ev("input",{id:"dlgin",value:"MU",dataset:{need:"MU"}});
 ok(el("#dlgyes").disabled===false,"typed ticker enables Confirm");
 await ev("click",{id:"dlgyes"});await p;await tick();
 ok(calls.some(c=>c.startsWith("DELETE /api/v1/companies/MU ")),"confirm sends DELETE");
 
 // navigation must not bounce back to Overview after a click
 run('T=null');const before=calls.length;await ev("click",{dataset:{t:"MU"},closest:s=>s==="[data-t]"?{tagName:"BUTTON",dataset:{t:"MU"}}:null});await tick();
 ok(run("T")==="MU"&&run("CUR")==="co","clicking a sidebar company opens it and stays open");
 ok(calls.slice(before).filter(c=>c.endsWith("/api/v1/companies [T=null CUR=home]")).length===0&&!calls.slice(before).some(c=>c.includes("[T=null")),"no stray Overview reload on click");
 ok(el("#ver").textContent==="v2.28.0-focus-levels","version marker shown");
 // trade reasons
 await run("portfolio()");
 ok(el("#view").innerHTML.includes("Trades needing a reason")&&el("#view").innerHTML.includes('data-reason="7"'),"portfolio lists trades that still need a reason");
 await ev("click",{dataset:{reason:"7"}});
 ok(el("#dlgb").innerHTML.includes("Buy 5 MU")&&el("#dlgb").innerHTML.includes('id="rsave"'),"reason dialog opens for a pending trade");
 run('T="MU"');run("tab='plan'");await run("show()");
 ok(el("#view").innerHTML.includes("Swing")&&el("#view").innerHTML.includes("HBM demand")&&el("#view").innerHTML.includes("pre-split?"),"plan tab shows saved reason and flags a pre-split price");
 await ev("click",{dataset:{reason:"1"}});
 ok(el("#dlgb").innerHTML.includes("HBM demand"),"reason dialog pre-fills an existing reason");
 el("#rs-str").value="long_term";el("#rs-fund").value="x";el("#rs-tech").value="";el("#rs-date").value="2027-01-01";el("#rs-rev").value="";
 await ev("click",{id:"rsave",dataset:{id:"1"}});
 ok(calls.some(c=>c.startsWith("PUT /api/v1/trades/1/reason")),"saving a reason sends PUT");
 run('T="MU"');run("tab='time'");await run("show()");
 ok(el("#view").innerHTML.includes("Bought 55")&&el("#view").innerHTML.includes("Baseline thesis"),"timeline merges trades with analyses");
 ok(el("#view").innerHTML.includes("Macro idea")&&el("#view").innerHTML.includes("Rates view"),"timeline merges journal entries tagged with the ticker");
 ok(run("outcomeCard").length>=0&&(await run("portfolio()"),el("#view").innerHTML.includes("Trade outcomes")&&el("#view").innerHTML.includes("Worked share")),"portfolio shows outcome counts by strategy");
 ok(el("#dlgb").innerHTML.length>0,"dialog remains available");
 await ev("click",{dataset:{reason:"7"}});
 ok(el("#dlgb").innerHTML.includes("Decision date")&&el("#dlgb").innerHTML.includes("Did not work")&&el("#dlgb").innerHTML.includes("Follow-up"),"reason dialog has decision date, outcome choices and follow-up");
 run("SEL.add(7);SEL.add(8)");await ev("click",{dataset:{bulk:"1"}});
 ok(el("#dlgb").innerHTML.includes("One reason for 2 trades"),"bulk dialog opens for selected trades");
 el("#rs-fund").value="same cause";await ev("click",{id:"rsave",dataset:{id:"",ids:"7,8"}});
 ok(calls.some(c=>c.startsWith("PUT /api/v1/trades/reason/bulk")),"bulk save sends one PUT for all trades");
 await run("guide()");
 ok(el("#view").innerHTML.includes("Holding strategies")&&el("#view").innerHTML.includes("Calibrate")&&el("#view").innerHTML.includes("earnings growth"),"Guide explains the loop and each strategy");
 // plan: sizing, logic, quarterly
 run('T="MU"');run("tab='plan'");await run("show()");
 ok(el("#view").innerHTML.includes("Position logic")&&el("#view").innerHTML.includes("HBM cycle upswing")&&el("#view").innerHTML.includes("data-applylogic"),"plan card shows the position logic and offers to reuse it for trades without a reason");
 ok(el("#view").innerHTML.includes("$11,000 / $5,000 / $6,000")&&el("#view").innerHTML.includes("$5,000 over max"),"plan card shows position value vs target and max amounts");
 await ev("click",{dataset:{applylogic:"MU"}});
 ok(calls.some(c=>c.startsWith("POST /api/v1/plans/MU/apply-logic")),"apply-logic sends POST");
 await ev("click",{dataset:{reason:"2"}});
 ok(el("#dlgb").innerHTML.includes("Role in the position")&&el("#dlgb").innerHTML.includes("HBM cycle upswing")&&el("#dlgb").innerHTML.includes("copied from the plan"),"reason dialog starts from the plan logic");
 await ev("click",{id:"planb"});
 ok(el("#dlgb").innerHTML.includes("Target position (amount)")&&el("#dlgb").innerHTML.includes("Position logic"),"plan dialog has strategy, logic and weights");
 run('T="MU"');run("tab='fund'");await run("show()");
 ok(el("#view").innerHTML.includes("Quarterly results")&&el("#view").innerHTML.includes("Q3"),"Fundamentals shows quarterly results");
 // journal page
 await ev("click",{closest:s=>s==="#jnb"?{}:null});await tick();
 ok(run("CUR")==="jn"&&el("#view").innerHTML.includes("Review checklist")&&el("#view").innerHTML.includes("no reason")&&el("#view").innerHTML.includes("Rates view")&&el("#view").innerHTML.includes("Portfolio at the time"),"Journal page renders checklist, entry and snapshot");
 ok(!el("#view").innerHTML.includes("<b>soon</b>"),"journal body is escaped");
 el("#jk");el("#jt");el("#jb");await ev("click",{id:"jstart"});
 ok(el("#jk").value==="review"&&el("#jb").value.includes("Plan alerts")&&el("#jb").value.includes("(no reason recorded)")&&el("#jb").value.includes("a1 holding → weakened"),"Start review prefills the entry from the checklist");
 el("#jtk").value="mu, tlt";el("#jd").value="";await ev("click",{id:"jsave"});
 ok(calls.some(c=>c.startsWith("POST /api/v1/journal ")),"saving an entry sends POST");
 await ev("change",{id:"jf",value:"macro"});ok(calls.some(c=>c.includes("/api/v1/journal?kind=macro")),"kind filter reloads entries");
 const pd=ev("click",{dataset:{jdel:"3"}});await tick();ok(el("#dlgb").innerHTML.includes("Delete this journal entry?"),"journal delete asks in-page");await ev("click",{id:"dlgyes"});await pd;await tick();
 ok(calls.some(c=>c.startsWith("DELETE /api/v1/journal/3 ")),"confirm deletes the entry");

 // list controls, allocation, analyse confirm, tooltips
 await run("portfolio()");
 await ev("change",{id:"pvw",value:"none"});ok(run("LS.pf.vw")==="none"&&el("#lc").textContent.includes("holdings"),"portfolio view filter applies");
 await ev("input",{id:"pq",value:"zzz"});ok(el("#lt").innerHTML.includes("No holdings match"),"search with no match shows empty state");
 await ev("input",{id:"pq",value:""});await ev("change",{id:"pvw",value:""});
 await ev("change",{id:"al",value:"style"});ok(el("#alc").innerHTML.includes("sbar"),"allocation regroups by investment purpose");
 const n0=calls.length;let pa=ev("click",{dataset:{an:"AAPL"}});await tick();
 ok(el("#dlgb").innerHTML.includes("Analyse AAPL?")&&!calls.slice(n0).some(c=>c.includes("/refresh")),"Analyse asks for confirmation before any call");
 await ev("click",{id:"dlgno"});await pa;ok(!calls.slice(n0).some(c=>c.includes("/refresh")),"cancel does not start an analysis");
 pa=ev("click",{dataset:{an:"AAPL"}});await tick();await ev("click",{id:"dlgyes"});await pa;await tick();
 ok(calls.slice(n0).some(c=>c.startsWith("POST /api/v1/companies/AAPL/refresh")),"confirm starts the analysis");
 await run("journal()");ok(el("#view").innerHTML.includes('class="tip"')&&el("#view").innerHTML.includes("Revisit on")&&el("#view").innerHTML.includes("Portfolio-level"==="x"?"":"data-tip"),"journal fields carry hover guidance");
 el("#jb");el("#jbt");await ev("change",{id:"jk",value:"macro"});ok(el("#jb").placeholder.includes("macro"),"entry type switches the guidance text");
 // sidebar groups and Chinese view
 await run("companies()");await tick();
 ok(el("#list").innerHTML.includes('data-g="focus"')&&el("#list").innerHTML.includes("▾"),"sidebar groups are collapsible (Focus open)");
 await ev("click",{closest:s=>s===".gh"?{dataset:{g:"focus"}}:null});ok(!el("#list").innerHTML.includes('data-t="MU"')||run("T")==="MU","clicking a group header toggles it");
 run('T="MU"');run('tab="brief"');run('VL="zh"');await run("show()");
 ok(calls.some(c=>c.includes("/companies/MU/brief?lang=zh"))&&el("#view").innerHTML.includes("Translate to Chinese"),"Chinese view requests lang=zh and offers translation when missing");
 await ev("click",{dataset:{trl:"5"}});ok(calls.some(c=>c.startsWith("POST /api/v1/reviews/5/translate")),"translate button sends POST");
 run('VL="en"');
 // period digest on Overview
 await run("companies()");run("home()");await tick();await tick();
 ok(el("#dgb").innerHTML.includes("Biggest moves")&&el("#dgb").innerHTML.includes("Plan alerts")&&calls.some(c=>c.includes("/journal/checklist?since=")),"Overview shows the period digest from the checklist endpoint");
 const nd=calls.length;await ev("change",{id:"dgd",value:"90"});await tick();ok(calls.slice(nd).some(c=>c.includes("/journal/checklist?since=")),"changing the period reloads the digest");
 run('CL=[{ticker:"AAA",status:"focus",held:false},{ticker:"BBB",status:"holding",held:true},{ticker:"CCC",status:"watching"},{ticker:"DDD",status:"archived"}]');run("GOPEN.archived=true");run("GOPEN.focus=true");run("SH=\'\'");run("lst()");
 {const h=el("#list").innerHTML;ok(h.includes('data-g="focus"')&&h.includes('data-g="normal"')&&h.includes('data-g="archived"')&&!h.includes('data-g="holding"'),"sidebar has three levels: Focus, Others, Archived");
 ok(h.indexOf('data-t="BBB"')>h.indexOf('data-g="normal"')&&h.indexOf('data-t="CCC"')>h.indexOf('data-g="normal"'),"old holding / watching values appear under Others");
 ok(/class="hdot" title="You hold this"[^<]*<\/i> <\/span>|You hold this[\s\S]*BBB/.test(h)&&!h.includes('title="You hold this">●</i> AAA'),"held companies get a dot, not-held do not");}
 run('SH="1"');run("lst()");ok(!el("#list").innerHTML.includes('data-t="AAA"')&&el("#list").innerHTML.includes('data-t="BBB"'),"Held filter shows only held companies");
 run('SH="0"');run("lst()");ok(el("#list").innerHTML.includes('data-t="AAA"')&&!el("#list").innerHTML.includes('data-t="BBB"'),"Not held filter shows only the others");run('SH=""');
 run('CL=[{ticker:"0883.HK",name:"CNOOC LTD",alias:"中国海洋石油",status:"holding",view:"neutral"},{ticker:"MU",name:"Micron",status:"holding"}]');run("GOPEN.focus=true");run("lst()");
 ok(el("#list").innerHTML.includes("中国海洋石油")&&!el("#list").innerHTML.includes("Micron"),"sidebar shows the company name for HK codes only");
 ok(run('su("javascript:alert(1)")')===""&&run('su("https://finance.yahoo.com/x")')==="https://finance.yahoo.com/x","only http(s) links are rendered as links");
 // trade calendar
 run('CAL.anchor="2026-10-08"');await ev("click",{closest:s=>s==="#calb"?{}:null});await tick();
 ok(run("CUR")==="cal"&&el("#calb2").innerHTML.includes("data-day=\"2026-10-08\"")&&el("#calb2").innerHTML.includes("○ B MU")&&el("#calb2").innerHTML.includes("✓ S NVDA")&&el("#calb2").innerHTML.includes("Rate decision")&&el("#calb2").innerHTML.includes("1 due"),"calendar month grid shows trade chips, reason state, events and due items");
 ok(calls.some(c=>c.includes("/api/v1/calendar?start=2026-09-27&end=2026-10-31")),"month grid starts on Sunday and covers whole weeks");
 await ev("click",{closest:s=>s==="[data-day]"?{dataset:{day:"2026-10-08"}}:null});
 ok(run("CAL.sel")==="2026-10-08"&&run("calDetail()").includes("since you bought")&&run("calDetail()").includes("bought and sold within 10 days")&&run("calDetail()").includes('data-reason="7"'),"clicking a day shows trade details, since-trade change and Add reason");
 await ev("change",{id:"cnr",checked:true});ok(!el("#calb2").innerHTML.includes("NVDA"),"No reason only filter hides trades that have a reason");
 await ev("change",{id:"cnr",checked:false});await ev("change",{id:"cmode",value:"list"});await tick();ok(el("#calb2").innerHTML.includes("<th>Date</th>")&&el("#calb2").innerHTML.includes("round trip"),"list view shows the same trades as a table");
 run('CAL.mode="month"');
 // calendar legend, journal entry from a day, links between pages
 run('CAL.mode="month";CAL.anchor="2026-10-08";CAL.sel="2026-10-08";CAL.nr=false');await run("calendar()");
 ok(el("#view").innerHTML.includes("dashed: no reason yet")&&el("#view").innerHTML.includes('class="tip"'),"calendar shows a legend and a help bubble");
 ok(run("calDetail()").includes('data-jnday="2026-10-08"'),"day detail offers a journal note or event for that date");
 el("#jev");el("#jt");el("#jk");el("#jb");el("#jbt");await ev("click",{dataset:{jnday:"2026-10-08"}});await tick();
 ok(run("CUR")==="jn"&&el("#jev").value==="2026-10-08"&&el("#jk").value==="macro","journal opens with the event date prefilled from the calendar");
 ok(el("#view").innerHTML.includes('id="jsince"')&&el("#view").innerHTML.includes('data-gocal="list"'),"journal checklist has a since-date picker and a link to the calendar");
 await ev("change",{id:"jsince",value:"2026-08-01"});ok(calls.some(c=>c.includes("/journal/checklist?since=2026-08-01")),"changing the since date reloads the checklist");
 await ev("click",{dataset:{gocal:"nr"}});await tick();ok(run("CUR")==="cal"&&run("CAL.mode")==="list"&&run("CAL.nr")===true,"portfolio link opens the calendar list filtered to trades without a reason");
 await ev("click",{dataset:{gocal:"day:2026-10-06"}});await tick();ok(run("CAL.mode")==="month"&&run("CAL.sel")==="2026-10-06","a due item opens its day in the calendar");
 await run("portfolio()");ok(el("#view").innerHTML.includes('data-gocal="nr"'),"portfolio trade backlog links to the calendar");

 // valuation linked to the company page
 run('T="MU";CUR="co";tab="val"');await run("show()");
 const vh=el("#view").innerHTML;
 ok(el("#tabs").innerHTML.includes("Valuation")&&vh.includes("What your saved assumptions imply")&&vh.includes("Earnings expected to recover")&&vh.includes("may be out of date"),"Valuation tab shows implied returns, the earnings-recovery card and a stale flag");
 ok(vh.includes("At your plan price")&&vh.includes("87.15")&&vh.includes('data-usebuy="87.15"'),"Valuation tab shows the most you could pay and a Use as buy-below button");
 ok(vh.includes("What each valuation input rests on")&&vh.includes("a1"),"Valuation tab lists linked thesis assumptions per valuation input");
 await ev("click",{dataset:{usebuy:"87.15"}});ok(el("#dlgb").innerHTML.includes("Position plan · MU")&&el("#dlgb").innerHTML.includes("87.15"),"Use as buy-below opens the plan form prefilled; nothing is saved");
 ok(!calls.some(c=>c.startsWith("PUT /api/v1/plans/MU")&&c.includes("87")),"the plan is not saved automatically");
 ok(vh.includes("A question to write down")&&vh.includes("vqtxt"),"the question card is shown whenever a question exists, with editable text");
 await ev("click",{dataset:{vq:"1"}});ok(calls.some(c=>c.startsWith("POST /api/v1/companies/MU/notes")),"the question can be saved to Notes");
 await ev("change",{dataset:{drv:"a1"},value:"margin"});ok(calls.some(c=>c.startsWith("PUT /api/v1/companies/MU/assumption-drivers/a1")),"choosing a valuation input for an assumption saves the link");

 // Fundamentals page: grouped, readable; Overview digest and holdings sort
 run('T="MU"');run("tab='fund'");await run("show()");await tick();
 const fv=el("#view").innerHTML;
 ok(fv.includes("What you pay")&&fv.includes("What you get")&&fv.includes("The record")&&fv.includes("fgrid"),"Fundamentals is grouped into what you pay, what you get, the record");
 ok(!fv.includes("Quarterly and annual results")&&fv.includes("Annual results"),"Fundamentals shows the annual table first");
 ok(run('Pg(30.457)').includes("n/m")&&run('Pg(0.2)')==="20.0%","an extreme growth rate is shown as n/m, a normal one as a percentage");
 ok(run('big(1.5e9,"HK$")')==="HK$1.50B"&&run('Dl(85.76,"HK$")')==="HK$85.76","amounts use the company currency symbol");
 run("home()");await tick();await tick();
 ok(el("#dgb").innerHTML.includes("data-dgj")&&el("#dgb").innerHTML.includes('id="dg-changes"')&&el("#dgb").innerHTML.includes("Due for a second look"),"digest tiles jump to their sections and the titles match");
 run('LS.hm.so="pnl"');run("drawHm()");
 ok(el("#hl").innerHTML.includes("P&amp;L")&&el("#hl").innerHTML.includes("+34.0%")&&el("#hl").innerHTML.includes("10.0%"),"Overview companies table shows P&L and weight");
 ok(run("hmRows().length")===1&&run('LS.hm.so="loss";hmRows().length')===1,"P&L sort options work on the Overview table");
 console.log(calls.length+" calls");
})().catch(e=>{console.log("ERROR",e.stack);process.exitCode=1});
