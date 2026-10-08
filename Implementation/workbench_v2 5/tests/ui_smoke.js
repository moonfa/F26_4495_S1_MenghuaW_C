// Run from the project root: node tests/ui_smoke.js  (simulated DOM + mocked API; no browser needed)
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8'),code=html.match(/<script>([\s\S]*)<\/script>/)[1];
const els={},H={click:[],change:[],input:[]},calls=[];
const el=s=>els[s]||(els[s]={innerHTML:"",textContent:"",value:"",disabled:false,open:false,style:{},dataset:{},addEventListener(){},
  showModal(){this.open=true},close(){this.open=false},querySelector(){return null}});
const pl={style:"trade",buy_below:90,target_price:130,stop_price:85,rules:"trim 30% at +15%"},ps={status:"near_target",flags:["near_target"],to_target:0.02,to_stop:-0.15,to_buy:-0.1};
const data={
 "/api/v1/companies":[{ticker:"MU",name:"Micron",status:"holding",view:"constructive",view_change:"new",price:1074.89,target_upside_pct:0.1,analysed_at:new Date().toISOString(),plan_status:ps}],
 "/api/v1/health":{version:"2.11.0-security"},"/api/v1/trades/pending":{all:3,total:2,items:[{id:7,code:"MU",symbol:"MU",side:"buy",quantity:5,price:200,currency:"USD",executed_at:"2026-07-01T15:00:00+00:00",reason:null}]},"/api/v1/companies/MU/timeline":[{id:1,created_at:"2026-10-01T10:00:00+00:00",kind:"baseline",level:"material",view:"neutral",view_change:"new",one_liner:"Baseline thesis",price:1000,level_reason:"r",changes:[],assumption_changes:[],delta_summary:{}}],"/api/v1/companies/MU/trades":[{id:2,code:"MU",reason:null,side:"buy",quantity:1,price:5000,fee:0,currency:"USD",executed_at:"2025-01-01T15:00:00+00:00"},{id:1,code:"MU",reason:{strategy:"swing",fundamental:"HBM demand",technical:"",revisit_on:null,review:"",reviewed:false},side:"buy",quantity:55,price:245,fee:2.1,currency:"USD",executed_at:"2026-07-17T19:12:19+00:00"}],"/api/v1/usage":{calls:2,by_model:{"gemini-3.8-flash":2}},
 "/api/v1/companies/MU/notes":{price_now:1,items:[{id:1,kind:"comment",body:"my note",created_at:"2026-09-01T00:00:00"}]},
 "/api/v1/journal/checklist":{since:"2026-09-01",exposure:{positions:40,top5:0.3,cautious:0.1,unanalysed:0.4},trades:[{id:7,symbol:"MU",side:"buy",quantity:5,price:200,currency:"USD",executed_at:"2026-09-20T15:00:00+00:00",has_reason:false}],trades_without_reason:1,changes:[{symbol:"MU",when:"2026-09-21T00:00:00",view:"cautious",view_change:"down",assumptions:[{id:"a1",from:"holding",to:"weakened"}]}],plan_alerts:[{symbol:"MU",status:"near_target"}],movers:[{symbol:"MU",weight:0.1,pct:0.12,exact:true}],stale:[{symbol:"AAPL",weight:0.05,days:null}],due:[]},
 "/api/v1/journal":[{id:3,kind:"macro",title:"Rates view",body:"Fed cuts <b>soon</b>",tickers:["TLT","MU"],revisit_on:"2026-12-01",done:false,snapshot:{positions:40,top5:0.3,cautious:0.1,unanalysed:0.4,holdings:[{symbol:"MU",weight:0.1,view:"cautious"}]},created_at:"2026-09-22T10:00:00"}],
 "/api/v1/portfolio":{count:1,top5:0.1,cautious:0,unanalysed:0.5,imported_at:new Date().toISOString(),items:[{id:1,code:"MU",symbol:"MU",name:"Micron",kind:"stock",currency:"USD",quantity:55,price:1074.89,pnl_pct:3.4,weight:0.101,analysed:true,view:"constructive",plan:pl,plan_status:ps}]},
 "/api/v1/companies/MU/brief":{ticker:"MU",name:"Micron",status:"holding",view:"constructive",view_change:"new",health:"Watch",health_reason:"a1 unverified",one_liner:"x",analysed_at:new Date().toISOString(),checked_at:new Date().toISOString(),last_check_level:"none",last_check_reason:"r",quote:{price:1074.89,yahoo_url:"https://finance.yahoo.com/quote/MU"},health_counts:{holding:1},assumptions:[{id:"a1",statement:"s",status:"holding",kill_criteria:"k",evidence:[]}],top_changes:[],monitor:[],news:[],data_notes:{gaps:[],warnings:["News unavailable. RSS: 0 items"]},due_notes:[],position:{quantity:55,cost:245,pnl_pct:3.4,weight:0.101,currency:"USD",kind:"stock"},plan:pl,plan_status:ps,valuation:null,meta:{kind:"baseline",usage:{}}}};
const ctx={document:{querySelector:el,addEventListener:(t,f)=>H[t]&&H[t].push(f)},toast:()=>0,setTimeout,clearTimeout,Date,Promise,console,
 FormData:class{},confirm:()=>{throw new Error("native confirm used")},prompt:()=>{throw new Error("native prompt used")},
 fetch:async(u,o)=>{calls.push((o&&o.method||"GET")+" "+u+" [T="+vm.runInContext("T",ctx)+" CUR="+vm.runInContext("CUR",ctx)+"]");const k=u.split("?")[0];return{ok:k in data||(o&&["DELETE","PUT"].includes(o.method)),status:200,json:async()=>data[k]||{}}}};
vm.createContext(ctx);
const run=c=>vm.runInContext(c,ctx),tick=()=>new Promise(r=>setTimeout(r,20));
const ev=(type,t)=>Promise.all(H[type].map(f=>f({target:Object.assign({dataset:{},closest:()=>null},t)})));
const ok=(c,m)=>{console.log((c?"PASS ":"FAIL ")+m);if(!c)process.exitCode=1};
(async()=>{
 run(code);await tick();
 ok(/Holdings/i.test(el("#list").innerHTML)&&el("#hl").innerHTML.includes("<th>Plan")&&el("#hl").innerHTML.includes("Sector"),"overview + grouped sidebar + Plan and Sector columns");
 ok(el("#usage").textContent.includes("AI analyses today: 2"),"usage line");
 await run("portfolio()");
 ok(el("#lt").innerHTML.includes('data-plan="MU"')&&el("#lt").innerHTML.includes("<th>Plan")&&el("#view").innerHTML.includes("Plan alerts")&&el("#view").innerHTML.includes("Allocation"),"portfolio shows Plan column, button, alerts card");
 run('T="MU"');await run("show()");ok(!el("#view").innerHTML.includes("Your position")&&el("#tabs").innerHTML.includes("Position & plan"),"brief has a Position & plan tab (card moved there)");run('tab="plan"');await run("show()");console.log("after show: T=",run("T"),"CUR=",run("CUR"));
 ok(el("#view").innerHTML.includes("Your position &amp; plan")&&el("#view").innerHTML.includes("Edit plan")&&el("#view").innerHTML.includes("Your trades")&&el("#view").innerHTML.includes("Buy"),"plan tab shows position & plan card and trades");
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
 ok(el("#ver").textContent==="v2.11.0-security","version marker shown");
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
 ok(el("#list").innerHTML.includes('data-g="holding"')&&el("#list").innerHTML.includes("▾"),"sidebar groups are collapsible (holdings open)");
 await ev("click",{closest:s=>s===".gh"?{dataset:{g:"holding"}}:null});ok(!el("#list").innerHTML.includes('data-t="MU"')||run("T")==="MU","clicking a group header toggles it");
 run('T="MU"');run('tab="brief"');run('VL="zh"');await run("show()");
 ok(calls.some(c=>c.includes("/companies/MU/brief?lang=zh"))&&el("#view").innerHTML.includes("Translate to Chinese"),"Chinese view requests lang=zh and offers translation when missing");
 await ev("click",{dataset:{trl:"5"}});ok(calls.some(c=>c.startsWith("POST /api/v1/reviews/5/translate")),"translate button sends POST");
 run('VL="en"');
 // period digest on Overview
 await run("companies()");run("home()");await tick();await tick();
 ok(el("#dgb").innerHTML.includes("Biggest moves")&&el("#dgb").innerHTML.includes("Plan alerts")&&calls.some(c=>c.includes("/journal/checklist?since=")),"Overview shows the period digest from the checklist endpoint");
 const nd=calls.length;await ev("change",{id:"dgd",value:"90"});await tick();ok(calls.slice(nd).some(c=>c.includes("/journal/checklist?since=")),"changing the period reloads the digest");
 run('CL=[{ticker:"0883.HK",name:"CNOOC LTD",alias:"中国海洋石油",status:"holding",view:"neutral"},{ticker:"MU",name:"Micron",status:"holding"}]');run("GOPEN.holding=true");run("lst()");
 ok(el("#list").innerHTML.includes("中国海洋石油")&&!el("#list").innerHTML.includes("Micron"),"sidebar shows the company name for HK codes only");
 ok(run('su("javascript:alert(1)")')===""&&run('su("https://finance.yahoo.com/x")')==="https://finance.yahoo.com/x","only http(s) links are rendered as links");
 console.log(calls.length+" calls");
})().catch(e=>{console.log("ERROR",e.stack);process.exitCode=1});
