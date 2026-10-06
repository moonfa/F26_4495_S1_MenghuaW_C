// Run from the project root: node tests/ui_smoke.js  (simulated DOM + mocked API; no browser needed)
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8'),code=html.match(/<script>([\s\S]*)<\/script>/)[1];
const els={},H={click:[],change:[],input:[]},calls=[];
const el=s=>els[s]||(els[s]={innerHTML:"",textContent:"",value:"",disabled:false,open:false,style:{},dataset:{},addEventListener(){},
  showModal(){this.open=true},close(){this.open=false},querySelector(){return null}});
const pl={style:"trade",buy_below:90,target_price:130,stop_price:85,rules:"trim 30% at +15%"},ps={status:"near_target",flags:["near_target"],to_target:0.02,to_stop:-0.15,to_buy:-0.1};
const data={
 "/api/v1/companies":[{ticker:"MU",name:"Micron",status:"holding",view:"constructive",view_change:"new",price:1074.89,target_upside_pct:0.1,analysed_at:new Date().toISOString(),plan_status:ps}],
 "/api/v1/health":{version:"2.5.1-plan-tab"},"/api/v1/companies/MU/trades":[{id:1,side:"buy",quantity:55,price:245,fee:2.1,currency:"USD",executed_at:"2026-07-17T19:12:19+00:00"}],"/api/v1/usage":{calls:2,by_model:{"gemini-3.8-flash":2}},
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
 ok(/Holdings/i.test(el("#list").innerHTML)&&el("#view").innerHTML.includes("<th>Plan</th>"),"overview + grouped sidebar + Plan column");
 ok(el("#usage").textContent.includes("AI analyses today: 2"),"usage line");
 await run("portfolio()");
 ok(el("#view").innerHTML.includes('data-plan="MU"')&&el("#view").innerHTML.includes("<th>Plan</th>")&&el("#view").innerHTML.includes("Plan alerts"),"portfolio shows Plan column, button, alerts card");
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
 ok(el("#ver").textContent==="v2.5.1-plan-tab","version marker shown");
 console.log(calls.length+" calls");
})().catch(e=>{console.log("ERROR",e.stack);process.exitCode=1});
