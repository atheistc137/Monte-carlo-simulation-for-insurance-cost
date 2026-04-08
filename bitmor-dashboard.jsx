import React, { useState, useMemo } from "react";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line, ReferenceLine, ScatterChart, Scatter, ZAxis, Cell } from "recharts";

const T = {
  bg:"#030916",bgCard:"#0a1428",bgCardHover:"#0f1d38",border:"#1a2a4a",borderLight:"#243556",
  persimmon:"#F25E13",persimmonDim:"rgba(242,94,19,0.15)",persimmonGlow:"rgba(242,94,19,0.4)",
  green:"#22c55e",greenDim:"rgba(34,197,94,0.15)",red:"#ef4444",yellow:"#eab308",
  text:"#e8ecf4",textDim:"#7a8ba8",textMuted:"#4a5d7a",white:"#ffffff",
};

const fmt=(n,d=0)=>n?.toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d})??"—";
const fmtUsd=n=>"$"+fmt(n);
const fmtPct=n=>fmt(n,1)+"%";
const Nd=x=>{const a1=.254829592,a2=-.284496736,a3=1.421413741,a4=-1.453152027,a5=1.061405429,p=.3275911;const s=x<0?-1:1;x=Math.abs(x)/Math.sqrt(2);const t=1/(1+p*x);const y=1-(((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t*Math.exp(-x*x);return .5*(1+s*y)};

const genAmort=(P,rate,n)=>{const r=rate/12,pmt=P*(r*Math.pow(1+r,n))/(Math.pow(1+r,n)-1);let b=P;return Array.from({length:n},(_,i)=>{const int=b*r,pr=Math.min(pmt-int,b);b=Math.max(0,b-pr);return{month:i+1,payment:pmt,principal:pr,interest:int,balance:b,pctPaid:(1-b/P)*100}})};

const genPath=(seed=0)=>{
  const rng=s=>{s=Math.sin(s*127.1+311.7)*43758.5453;return s-Math.floor(s)};
  const spot0=100000;let px=spot0,debt=70000,strike=Math.round(debt*1.1);const ip=5200;
  const rows=[];let cumSav=0,numRolls=0;
  for(let i=0;i<12;i++){
    px*=(1+(rng(seed*1000+i*37)-.4)*.12);
    const pmt=70000*(.00833*Math.pow(1.00833,12))/(Math.pow(1.00833,12)-1);
    debt=Math.max(0,debt-(pmt-debt*.00833));
    const newStrike=Math.round(Math.max(debt*1.1,strike*.85));
    const saving=i>0&&newStrike<strike?Math.round((strike-newStrike)*.08+rng(seed*100+i)*200):0;
    if(saving>0)numRolls++;
    cumSav+=saving;
    const oldStrike=strike;strike=newStrike;
    rows.push({month:i,debt:Math.round(debt),strike,oldStrike,saving,cumSav,
      savingPct:+(saving/ip*100).toFixed(1),cumPct:+(cumSav/ip*100).toFixed(1),
      action:i===0?`Buy $${Math.round(strike/1000)}K PUT (12mo)`
        :saving>0?`Roll $${Math.round(oldStrike/1000)}K → $${Math.round(strike/1000)}K (${12-i}mo)`
        :`Hold $${Math.round(strike/1000)}K PUT`,
      rolled:saving>0});
  }
  const recovery=cumSav/ip*100;
  return{rows,spot0,ip,ipPct:+(ip/spot0*100).toFixed(1),totalSav:cumSav,recovery:+recovery.toFixed(1),
    numRolls,finalPrice:Math.round(px),
    terminalPayoff:Math.max(0,strike-Math.round(px)),netCost:ip-cumSav,
    netCostPct:+((ip-cumSav)/spot0*100).toFixed(2)};
};


const genDist=(tierId)=>{
  // Tier 1: median 29.7%, right-skewed, most 10-50%, some up to 80%
  // Tier 2: median 95.9%, bear market, mass at 60-150%, some >200%
  // Tier 3: median 36.7%, wider spread, 0-100%+
  const bins=tierId===2?Array.from({length:28},(_,i)=>i*10):Array.from({length:22},(_,i)=>i*5);
  const totalPaths=tierId===1?731:tierId===2?366:1000;
  return bins.map(x=>{
    let count;
    if(tierId===1){
      // Right-skewed around 25-30
      count=Math.round(Math.exp(-((x-25)**2)/(2*14**2))*90*(1+Math.max(0,30-x)/40));
      if(x<=5)count=Math.round(count*1.8); // spike near zero (BTC pumped)
    }else if(tierId===2){
      // Mass at 80-120, long right tail
      count=x<40?Math.round(3+Math.random()*4):
            x<60?Math.round(8+Math.exp(-((x-50)**2)/(2*12**2))*15):
            Math.round(Math.exp(-((x-90)**2)/(2*25**2))*45*(1+Math.max(0,x-100)/80));
      if(x>=140)count=Math.round(Math.max(1,count*.4));
    }else{
      // Right-skewed around 30-40
      count=Math.round(Math.exp(-((x-32)**2)/(2*18**2))*80*(1+Math.max(0,35-x)/50));
      if(x<=5)count=Math.round(count*1.5);
    }
    return{bin:x,binEnd:x+(tierId===2?10:5),count:Math.max(0,count),pct:Math.round(Math.max(0,count)/totalPaths*1000)/10};
  });
};

// Scatter data: enriched with premium, savings, costs for tooltips
const genScatter=(tier,seed=7)=>{
  const rng=s=>{s=Math.sin(s*127.1+311.7)*43758.5453;return s-Math.floor(s)};
  if(tier===1){
    const start=new Date("2023-03-01").getTime(),end=new Date("2025-06-01").getTime();
    return Array.from({length:120},(_,i)=>{
      const t=start+(end-start)*rng(i*17+seed);
      const btc=28000+42000*((t-start)/(end-start))+rng(i*31)*8000-4000;
      const rec=Math.round(Math.min(rng(i*53+seed)*60+5+Math.max(0,(btc-40000)/2000),85)*10)/10;
      const prem=Math.round(btc*.07+rng(i*19)*500);
      const sav=Math.round(prem*rec/100);
      return{date:t,btcPrice:Math.round(btc),recovery:rec,premium:prem,rollSav:sav,putPct:+(prem/btc*100).toFixed(2),netPct:+((prem-sav)/btc*100).toFixed(2)};
    });
  }else if(tier===2){
    const start=new Date("2025-03-01").getTime(),end=new Date("2026-03-01").getTime();
    return Array.from({length:100},(_,i)=>{
      const t=start+(end-start)*rng(i*13+seed);const base=82000;
      const btc=Math.round(Math.max(60000,base-16000*((t-start)/(end-start))+rng(i*41)*12000+Math.sin((t-start)/86400000/30)*8000));
      const rec=Math.round(Math.min(40+rng(i*67+seed)*160+Math.max(0,(base-btc)/500),220)*10)/10;
      const prem=Math.round(btc*.065+rng(i*23)*400);
      const sav=Math.round(prem*rec/100);
      return{date:t,btcPrice:btc,recovery:rec,premium:prem,rollSav:sav,putPct:+(prem/btc*100).toFixed(2),netPct:+((prem-sav)/btc*100).toFixed(2)};
    });
  }else{
    return Array.from({length:200},(_,i)=>{
      const fp=Math.round(20000+rng(i*23+seed)*380000);
      const rec=Math.round(Math.max(0,fp<50000?100+rng(i*47)*150:fp<100000?30+rng(i*59)*80:5+rng(i*71)*50)*10)/10;
      const spot0=100000;const prem=Math.round(spot0*.06+rng(i*29)*600);
      const sav=Math.round(prem*rec/100);
      return{finalPrice:fp,recovery:rec,premium:prem,rollSav:sav,putPct:+(prem/spot0*100).toFixed(2),netPct:+((prem-sav)/spot0*100).toFixed(2)};
    });
  }
};

const TIERS=[
  {id:1,label:"Historical",badge:"Strongest",color:T.green,desc:"Pure historical backtest — BTC rallied from ~$28K to ~$66K across 731 loans (Mar 2023–2025).",paths:731,mr:29.7,medRoll:956,medPutPct:8.12,netPct:5.88,posRate:97.4,p5:3.2,p95:68.4,chartTitle:"Historical Backtest — Premium Recovery by Start Date"},
  {id:2,label:"Hist + Simulated",badge:"Blended",color:T.yellow,desc:"Bear market regime — BTC declined from ~$82K to ~$66K. Loans that started recently and haven't matured are extended with 1,000 simulated forward paths each.",paths:366,mr:95.9,medRoll:5355,medPutPct:5.78,netPct:0.21,posRate:99.2,p5:42.1,p95:185.3,chartTitle:"Recent Loans — Premium Recovery by Start Date"},
  {id:3,label:"Forward Sim",badge:"Speculative",color:T.persimmon,desc:"1,000 Monte Carlo paths from today's spot — 64% bullish, 37% bearish, reflecting BTC's historical drift and vol.",paths:1000,mr:36.7,medRoll:2190,medPutPct:9.0,netPct:5.69,posRate:91.3,p5:1.8,p95:142.6,chartTitle:"Premium Recovery vs Final BTC Price"},
];

const Card=({children,style})=><div style={{background:T.bgCard,border:`1px solid ${T.border}`,borderRadius:12,padding:28,...style}}>{children}</div>;
const SL=({n,t})=><div style={{display:"flex",alignItems:"center",gap:12,mb:8,marginBottom:8}}><span style={{fontSize:12,color:T.persimmon,fontWeight:600,letterSpacing:".1em"}}>{n}</span><span style={{fontSize:12,color:T.textMuted,letterSpacing:".06em",textTransform:"uppercase"}}>{t}</span></div>;
const Bdg=({children,color})=><span style={{display:"inline-block",padding:"3px 10px",borderRadius:4,fontSize:10,fontWeight:700,letterSpacing:".1em",textTransform:"uppercase",color,background:color+"22",border:`1px solid ${color}44`}}>{children}</span>;
const St=({l,v,s,a})=><div style={{minWidth:100}}><div style={{fontSize:11,color:T.textMuted,textTransform:"uppercase",letterSpacing:".08em",marginBottom:4}}>{l}</div><div style={{fontSize:22,fontWeight:600,color:a||T.text,fontVariantNumeric:"tabular-nums"}}>{v}</div>{s&&<div style={{fontSize:11,color:T.textDim,marginTop:2}}>{s}</div>}</div>;
const Pill=({children,active,onClick})=><button onClick={onClick} style={{padding:"6px 14px",borderRadius:6,border:`1px solid ${active?T.persimmon:T.border}`,background:active?T.persimmonDim:"transparent",color:active?T.persimmon:T.textDim,fontSize:13,fontWeight:500,cursor:"pointer",fontFamily:"inherit"}}>{children}</button>;
const Sl=({label,value,onChange,min,max,step,format})=><div style={{marginBottom:16}}><div style={{display:"flex",justifyContent:"space-between",marginBottom:6}}><span style={{fontSize:12,color:T.textDim}}>{label}</span><span style={{fontSize:13,color:T.text,fontWeight:600,fontVariantNumeric:"tabular-nums"}}>{format?format(value):value}</span></div><input type="range" min={min} max={max} step={step} value={value} onChange={e=>onChange(Number(e.target.value))} style={{width:"100%",accentColor:T.persimmon,height:4,cursor:"pointer"}}/></div>;
const Tabs=({tabs,active,onChange})=><div style={{display:"flex",borderBottom:`1px solid ${T.border}`,marginBottom:24}}>{tabs.map(t=><button key={t.id} onClick={()=>onChange(t.id)} style={{padding:"10px 20px",background:"none",border:"none",borderBottom:active===t.id?`2px solid ${T.persimmon}`:"2px solid transparent",color:active===t.id?T.text:T.textDim,fontSize:13,fontWeight:500,cursor:"pointer",fontFamily:"inherit"}}>{t.label}</button>)}</div>;
const tt={background:T.bgCard,border:`1px solid ${T.border}`,borderRadius:8,fontSize:11};

const ScatterTip=({active,payload,isTier3})=>{
  if(!active||!payload?.[0])return null;
  const d=payload[0].payload;
  const rows=isTier3?[
    {l:"Final BTC",v:"$"+fmt(d.finalPrice),c:T.text},
    null,
    {l:"Premium",v:"$"+fmt(d.premium),c:T.text},
    {l:"Roll Savings",v:"$"+fmt(d.rollSav),c:T.green},
    {l:"Recovery",v:d.recovery+"%",c:T.green,bold:true},
    null,
    {l:"PUT Cost",v:d.putPct+"% of BTC",c:T.textDim},
    {l:"Net Cost",v:d.netPct+"% of BTC",c:T.persimmon,bold:true},
  ]:[
    {l:new Date(d.date).toLocaleDateString("en-US",{year:"numeric",month:"short",day:"numeric"}),v:"",c:T.textMuted,isHeader:true},
    {l:"Entry Spot",v:"$"+fmt(d.btcPrice),c:T.text},
    null,
    {l:"Premium",v:"$"+fmt(d.premium),c:T.text},
    {l:"Roll Savings",v:"$"+fmt(d.rollSav),c:T.green},
    {l:"Recovery",v:d.recovery+"%",c:T.green,bold:true},
    null,
    {l:"PUT Cost",v:d.putPct+"% of BTC",c:T.textDim},
    {l:"Net Cost",v:d.netPct+"% of BTC",c:T.persimmon,bold:true},
  ];
  return <div style={{background:T.bg,border:`1px solid ${T.border}`,borderRadius:8,padding:"10px 14px",fontSize:11,fontVariantNumeric:"tabular-nums",minWidth:170,boxShadow:"0 4px 20px rgba(0,0,0,.4)"}}>
    {rows.map((r,i)=>r===null
      ?<div key={i} style={{borderTop:`1px solid ${T.border}`,margin:"5px 0"}}/>
      :r.isHeader
        ?<div key={i} style={{fontSize:10,color:r.c,marginBottom:4,fontWeight:500}}>{r.l}</div>
        :<div key={i} style={{display:"flex",justifyContent:"space-between",gap:16,padding:"1.5px 0"}}>
          <span style={{color:T.textDim}}>{r.l}</span>
          <span style={{color:r.c,fontWeight:r.bold?600:400}}>{r.v}</span>
        </div>
    )}
  </div>;
};

const NAV=[{id:"configure",label:"Cost Calculator"},{id:"backtest",label:"Roll-Down Research"}];
const Nav=({active,onChange})=><nav style={{position:"sticky",top:0,zIndex:100,background:T.bg+"ee",backdropFilter:"blur(16px)",borderBottom:`1px solid ${T.border}`,padding:"0 32px",display:"flex",alignItems:"center",justifyContent:"space-between"}}><div style={{display:"flex",alignItems:"center",gap:10}}><div style={{width:28,height:28,borderRadius:6,background:T.persimmon,display:"flex",alignItems:"center",justifyContent:"center",fontSize:14,fontWeight:800,color:T.white}}>B</div><span style={{fontSize:15,fontWeight:600,color:T.text}}>Bitmor</span></div><div style={{display:"flex"}}>{NAV.map(n=><button key={n.id} onClick={()=>onChange(n.id)} style={{padding:"16px 20px",background:"none",border:"none",borderBottom:active===n.id?`2px solid ${T.persimmon}`:"2px solid transparent",color:active===n.id?T.text:T.textDim,fontSize:13,fontWeight:500,cursor:"pointer",fontFamily:"inherit"}}>{n.label}</button>)}</div><a href="https://bitmor.xyz/loans" target="_blank" rel="noopener" style={{padding:"7px 18px",borderRadius:6,background:T.persimmon,color:T.white,fontSize:12,fontWeight:600,textDecoration:"none"}}>Join Waitlist</a></nav>;

const V1=({onNav})=>{
  const[bp,setBp]=useState(null);const ba=1;const[dp,setDp]=useState(30);const[rt,setRt]=useState(9);const sig=55;
  React.useEffect(()=>{
    fetch("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
      .then(r=>r.json()).then(d=>{setBp(Math.round(d.bitcoin.usd))})
      .catch(()=>{setBp(107544)});
  },[]);
  if(!bp) return <div style={{maxWidth:960,margin:"0 auto",padding:"80px 24px",textAlign:"center"}}><div style={{fontSize:14,color:T.textDim}}>Loading BTC price...</div></div>;
  const bv=bp*ba,dwn=bv*(dp/100),pr=bv-dwn,r=rt/100/12,pmt=pr*(r*Math.pow(1+r,12))/(Math.pow(1+r,12)-1),ti=pmt*12-pr,tr=pr+ti,sch=genAmort(pr,rt/100,12);
  // BS theoretical (for reference)
  const spb=pr/ba,d1=(Math.log(bp/spb)+.5*(sig/100)**2)/((sig/100)),d2=d1-(sig/100);
  const bsPut=Math.max(0,(spb*Nd(-d2)-bp*Nd(-d1))*ba);
  // Deribit market price (used as actual PUT cost) — placeholder: ~15% above BS to simulate market spread
  const deribitStrike=Math.round(spb/5000)*5000;
  const deribitIv=sig;
  const deribitMark=Math.round(bsPut*1.15);
  const deribitExpiry="26 MAR 27";
  // Use Deribit mark as the PUT cost
  const pp=deribitMark,ppb=pp/ba;
  const eff=(dwn+pp+tr)/ba,prem=((eff-bp)/bp)*100;
  const rs=pp*.34,effAR=eff-rs/ba,premAR=((effAR-bp)/bp)*100;

  return <div style={{maxWidth:960,margin:"0 auto",padding:"48px 24px"}}>
    {/* Intro */}
    <div style={{marginBottom:48}}>
      <h1 style={{fontSize:32,fontWeight:700,color:T.text,margin:"0 0 8px"}}>Bitcoin mortgages, on-chain</h1>
      <p style={{fontSize:15,color:T.textDim,margin:"0 0 28px",lineHeight:1.7,maxWidth:680}}>Bitmor lets you buy BTC with a down payment and repay in fixed monthly installments. A PUT option replaces traditional liquidation, so your position is never force-sold on a price drop.</p>

      <Card style={{padding:"20px 24px"}}>
        <div style={{fontSize:10,color:T.textMuted,textTransform:"uppercase",letterSpacing:".1em",marginBottom:16}}>How a loan is created</div>
        <div style={{display:"flex",alignItems:"flex-start",gap:6,overflowX:"auto",paddingBottom:4}}>
          {[
            {l:"USDC\nDown Payment",s:"30% of BTC value",c:T.persimmon},
            {l:"Pool Funds\nRemaining",s:"70% from lenders",c:T.persimmon},
            {l:"Buy BTC\non DEX",s:"full amount",c:"#2dd4bf"},
            {l:"Deposit BTC\nin Vault",s:"locked as collateral",c:"#2dd4bf"},
          ].map((step,i)=><div key={i} style={{display:"flex",alignItems:"center",gap:6,flexShrink:0}}>
            <div style={{padding:"12px 18px",borderRadius:8,background:T.bg,border:`1px solid ${step.c}33`,minWidth:120,textAlign:"center"}}>
              <div style={{fontSize:12,fontWeight:600,color:T.text,whiteSpace:"pre-line",lineHeight:1.4}}>{step.l}</div>
              <div style={{fontSize:9,color:T.textMuted,marginTop:5}}>{step.s}</div>
            </div>
            {i<3&&<span style={{color:T.textMuted,fontSize:14}}>→</span>}
          </div>)}
        </div>
        <div style={{fontSize:11,color:T.textDim,marginTop:14}}>Collateral is released only after full repayment.</div>
      </Card>
    </div>

    <SL n="01" t="Loan Configuration"/><h2 style={{fontSize:28,fontWeight:600,color:T.text,margin:"0 0 6px"}}>What does it really cost?</h2><p style={{fontSize:14,color:T.textDim,margin:"0 0 24px",lineHeight:1.6,maxWidth:620}}>See the total cost of a Bitmor loan at today's price, including interest, PUT hedge, and estimated savings from rolling down.</p>

    {/* Parameters — horizontal bar */}
    <Card style={{padding:"18px 24px",marginBottom:24}}>
      <div style={{display:"flex",alignItems:"center",gap:28,flexWrap:"wrap"}}>
        {/* BTC Spot */}
        <div style={{flexShrink:0}}>
          <div style={{fontSize:9,color:T.textMuted,textTransform:"uppercase",letterSpacing:".08em",marginBottom:4}}>BTC Spot</div>
          <div style={{fontSize:22,fontWeight:700,color:T.green,fontVariantNumeric:"tabular-nums"}}>{fmtUsd(bp)}</div>
        </div>
        {/* Divider */}
        <div style={{width:1,height:40,background:T.border,flexShrink:0}}/>
        {/* Interest Rate */}
        <div style={{minWidth:180,flex:"1 1 180px"}}>
          <Sl label="Annual Interest Rate" value={rt} onChange={setRt} min={5} max={12} step={.5} format={v=>v.toFixed(1)+"%"}/>
        </div>
        {/* Divider */}
        <div style={{width:1,height:40,background:T.border,flexShrink:0}}/>
        {/* Down Payment */}
        <div style={{flexShrink:0}}>
          <div style={{fontSize:11,color:T.textDim,marginBottom:6}}>Down Payment</div>
          <div style={{display:"flex",gap:6}}>{[20,30,40,50].map(d=><Pill key={d} active={dp===d} onClick={()=>setDp(d)}>{d}%</Pill>)}</div>
        </div>
        {/* Divider */}
        <div style={{width:1,height:40,background:T.border,flexShrink:0}}/>
        {/* Loan Term */}
        <div style={{flexShrink:0}}>
          <div style={{fontSize:11,color:T.textDim,marginBottom:6}}>Loan Term</div>
          <div style={{padding:"5px 12px",borderRadius:6,border:`1px solid ${T.persimmon}`,background:T.persimmonDim,color:T.persimmon,fontSize:12,fontWeight:500}}>12 months</div>
        </div>
      </div>
    </Card>

    {/* HERO — full width effective price */}
    <Card style={{background:"linear-gradient(135deg,#0f1d38 0%,#0a1428 100%)",border:`1px solid ${T.borderLight}`,position:"relative",overflow:"hidden",marginBottom:20,padding:"32px 36px"}}>
      <div style={{position:"absolute",top:-60,right:-60,width:200,height:200,borderRadius:"50%",background:T.persimmonGlow,filter:"blur(100px)",opacity:.25}}/>
      <div style={{position:"relative"}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",flexWrap:"wrap",gap:20}}>
          <div>
            <div style={{fontSize:11,color:T.textMuted,textTransform:"uppercase",letterSpacing:".1em",marginBottom:12}}>Effective price per BTC</div>
            <div style={{display:"flex",alignItems:"baseline",gap:16,marginBottom:6}}>
              <span style={{fontSize:48,fontWeight:700,color:T.text,fontVariantNumeric:"tabular-nums",letterSpacing:"-.02em"}}>{fmtUsd(effAR)}</span>
              <span style={{fontSize:18,fontWeight:700,fontVariantNumeric:"tabular-nums",color:premAR<=10?T.green:premAR<=20?T.yellow:T.persimmon}}>+{fmtPct(premAR)} over spot</span>
            </div>
            <div style={{fontSize:13,color:T.textDim,lineHeight:1.8,fontVariantNumeric:"tabular-nums"}}>
              <span style={{color:T.text}}>{fmtUsd(bp)}</span> spot
              <span style={{color:T.textMuted}}> + </span>
              <span style={{color:T.yellow}}>{fmtUsd(ti/ba)}</span> interest
              <span style={{color:T.textMuted}}> + </span>
              <span style={{color:T.persimmon}}>{fmtUsd(ppb)}</span> PUT
              <span style={{color:T.textMuted}}> − </span>
              <span style={{color:T.green}}>{fmtUsd(rs/ba)}</span> roll savings
              <span style={{color:T.textMuted}}> = </span>
              <span style={{color:T.text,fontWeight:600}}>{fmtUsd(effAR)}</span>
            </div>
          </div>
          {/* Stacked bar — right side */}
          <div style={{minWidth:280,flex:"0 0 280px"}}>
            <div style={{fontSize:10,color:T.textMuted,marginBottom:8}}>Cost composition</div>
            <div style={{display:"flex",height:36,borderRadius:8,overflow:"hidden",border:`1px solid ${T.border}`}}>
              <div style={{width:`${(bp/eff)*100}%`,background:T.textMuted+"33",display:"flex",alignItems:"center",justifyContent:"center"}}><span style={{fontSize:10,color:T.textDim,fontWeight:500}}>Spot</span></div>
              <div style={{width:`${((ti/ba)/eff)*100}%`,background:T.yellow+"44",display:"flex",alignItems:"center",justifyContent:"center"}}><span style={{fontSize:9,color:T.yellow,fontWeight:500}}>Int.</span></div>
              <div style={{width:`${(ppb/eff)*100}%`,background:T.persimmonDim,display:"flex",alignItems:"center",justifyContent:"center"}}><span style={{fontSize:9,color:T.persimmon,fontWeight:500}}>PUT</span></div>
            </div>
            <div style={{display:"flex",justifyContent:"space-between",marginTop:8,fontSize:10,color:T.textDim}}>
              <span>Spot: {fmtPct(bp/eff*100)}</span>
              <span style={{color:T.yellow}}>Int: {fmtPct((ti/ba)/eff*100)}</span>
              <span style={{color:T.persimmon}}>PUT: {fmtPct(ppb/eff*100)}</span>
            </div>
          </div>
        </div>
      </div>
    </Card>

    {/* Detail cards — three columns */}
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:14,marginBottom:20}}>
      {/* Upfront */}
      <Card style={{padding:20}}>
        <div style={{fontSize:10,color:T.textMuted,textTransform:"uppercase",letterSpacing:".1em",marginBottom:12}}>Upfront Cost</div>
        <div style={{fontSize:24,fontWeight:700,color:T.text,fontVariantNumeric:"tabular-nums",marginBottom:10}}>{fmtUsd(dwn+pp)}</div>
        <div style={{fontSize:11,color:T.textDim,lineHeight:1.8}}>
          <div style={{display:"flex",justifyContent:"space-between"}}><span>Down payment ({dp}%)</span><span style={{color:T.text}}>{fmtUsd(dwn)}</span></div>
          <div style={{display:"flex",justifyContent:"space-between"}}><span>PUT hedge</span><span style={{color:T.persimmon}}>{fmtUsd(pp)}</span></div>
        </div>
        <div style={{borderTop:`1px solid ${T.border}`,marginTop:10,paddingTop:8,fontSize:10,color:T.textMuted}}>Paid at origination</div>
      </Card>

      {/* Repayment */}
      <Card style={{padding:20,cursor:"pointer"}} onClick={()=>document.getElementById("amort-section")?.scrollIntoView({behavior:"smooth",block:"start"})}>
        <div style={{fontSize:10,color:T.textMuted,textTransform:"uppercase",letterSpacing:".1em",marginBottom:12}}>12-Month Repayment</div>
        <div style={{fontSize:24,fontWeight:700,color:T.persimmon,fontVariantNumeric:"tabular-nums",marginBottom:10}}>{fmtUsd(pmt)}<span style={{fontSize:12,color:T.textDim,fontWeight:400}}>/mo</span></div>
        <div style={{fontSize:11,color:T.textDim,lineHeight:1.8}}>
          <div style={{display:"flex",justifyContent:"space-between"}}><span>Principal repaid</span><span style={{color:T.text}}>{fmtUsd(pr)}</span></div>
          <div style={{display:"flex",justifyContent:"space-between"}}><span>Total interest</span><span style={{color:T.yellow}}>{fmtUsd(ti)}</span></div>
        </div>
        <div style={{borderTop:`1px solid ${T.border}`,marginTop:10,paddingTop:8,fontSize:10,color:T.persimmon,fontWeight:500}}>View schedule ↓</div>
      </Card>

      {/* Recovery — bridge to backtests */}
      <div onClick={()=>onNav("backtest")} style={{cursor:"pointer",transition:"transform 0.15s"}} onMouseEnter={e=>e.currentTarget.style.transform="translateY(-2px)"} onMouseLeave={e=>e.currentTarget.style.transform="none"}>
        <Card style={{padding:20,background:T.greenDim,border:`1px solid ${T.green}33`,height:"100%"}}>
          <div style={{fontSize:10,color:T.green,textTransform:"uppercase",letterSpacing:".1em",marginBottom:12,fontWeight:600}}>Expected Recovery</div>
          <div style={{fontSize:24,fontWeight:700,color:T.green,fontVariantNumeric:"tabular-nums",marginBottom:10}}>−{fmtUsd(rs)}</div>
          <div style={{fontSize:11,color:T.textDim,lineHeight:1.7}}>
            <div style={{display:"flex",justifyContent:"space-between"}}><span>Median recovery</span><span style={{color:T.green}}>34%</span></div>
            <div style={{display:"flex",justifyContent:"space-between"}}><span>Net hedge cost</span><span style={{color:T.text}}>{fmtUsd(pp-rs)}</span></div>
          </div>
          <div style={{borderTop:`1px solid ${T.green}22`,marginTop:10,paddingTop:8,fontSize:10,color:T.green,fontWeight:500}}>How does this work? →</div>
        </Card>
      </div>
    </div>

    {/* PUT pricing — full width */}
    <Card style={{padding:"16px 20px",border:`1px solid ${T.persimmon}33`,background:T.persimmonDim,marginBottom:20}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12}}>
        <div style={{display:"flex",alignItems:"center",gap:8}}>
          <div style={{width:6,height:6,borderRadius:"50%",background:T.persimmon}}/>
          <span style={{fontSize:10,color:T.persimmon,textTransform:"uppercase",letterSpacing:".1em",fontWeight:600}}>PUT Option Cost</span>
        </div>
        <span style={{fontSize:9,color:"#2dd4bf"}}>● Deribit market data</span>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:1,background:T.border,borderRadius:8,overflow:"hidden"}}>
        {[
          {l:"Strike",v:fmtUsd(deribitStrike),s:"nearest listed strike",c:T.text},
          {l:"Deribit Mark",v:fmtUsd(pp),s:fmtPct(pp/bp*100)+" of spot",c:T.persimmon},
          {l:"IV (σ)",v:deribitIv+"%",s:"market implied",c:T.text},
          {l:"Expiry",v:deribitExpiry,s:"nearest 12mo expiry",c:T.text},
        ].map((s,i)=><div key={i} style={{background:T.bgCard,padding:"12px 14px"}}>
          <div style={{fontSize:9,color:T.textMuted,textTransform:"uppercase",letterSpacing:".08em",marginBottom:4}}>{s.l}</div>
          <div style={{fontSize:18,fontWeight:700,color:s.c,fontVariantNumeric:"tabular-nums"}}>{s.v}</div>
          <div style={{fontSize:9,color:T.textDim,marginTop:2}}>{s.s}</div>
        </div>)}
      </div>
      <div style={{borderTop:`1px solid ${T.border}`,marginTop:12,paddingTop:10,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
        <div style={{fontSize:10,color:T.textDim}}>
          <span style={{color:T.textMuted}}>BS theoretical: </span>
          <span>{fmtUsd(bsPut)}</span>
          <span style={{color:T.textMuted}}> ({fmtPct(bsPut/spb*100)} of strike · σ={sig}%)</span>
        </div>
        <div style={{fontSize:10,color:T.textDim}}>
          Paid upfront: <span style={{color:T.persimmon,fontWeight:600}}>{fmtPct((dwn+pp)/bv*100)} of BTC</span>
        </div>
      </div>
      <div style={{fontSize:10,color:T.textDim,marginTop:8,lineHeight:1.5}}>Strike = financed principal. Purchased at origination. Eliminates price-based liquidation for the full loan term.</div>
    </Card>
    <div id="amort-section" style={{marginTop:40}}>
      <SL n="02" t="Repayment Schedule"/>
      <h2 style={{fontSize:22,fontWeight:600,color:T.text,margin:"0 0 4px"}}>Month-by-month amortization</h2>
      <p style={{fontSize:13,color:T.textDim,margin:"0 0 20px"}}>Each payment covers accrued interest first, then reduces principal. Balance reaches zero at month 12.</p>
      <Card style={{padding:"20px 24px",overflowX:"auto"}}>
        <table style={{width:"100%",borderCollapse:"collapse",fontSize:12,fontVariantNumeric:"tabular-nums"}}>
          <thead><tr>{["Mo.","Payment","Principal","Interest","Balance","% Paid"].map(h=><th key={h} style={{textAlign:h==="Mo."?"center":"right",padding:"10px 12px",color:T.textMuted,fontWeight:500,borderBottom:`1px solid ${T.border}`,fontSize:10,textTransform:"uppercase",letterSpacing:".06em"}}>{h}</th>)}</tr></thead>
          <tbody>{sch.map(row=><tr key={row.month} style={{borderBottom:`1px solid ${T.border}22`}}>
            <td style={{textAlign:"center",padding:"8px 12px",color:T.textDim}}>{row.month}</td>
            <td style={{textAlign:"right",padding:"8px 12px",color:T.text}}>{fmtUsd(row.payment)}</td>
            <td style={{textAlign:"right",padding:"8px 12px",color:T.persimmon}}>{fmtUsd(row.principal)}</td>
            <td style={{textAlign:"right",padding:"8px 12px",color:T.textDim}}>{fmtUsd(row.interest)}</td>
            <td style={{textAlign:"right",padding:"8px 12px",color:T.text,fontWeight:500}}>{fmtUsd(row.balance)}</td>
            <td style={{textAlign:"right",padding:"8px 12px",color:T.green}}>{fmtPct(row.pctPaid)}</td>
          </tr>)}</tbody>
        </table>
      </Card>
    </div>
  </div>;
};

const V2=()=>{
  const[at,setAt]=useState(1);const[ps,setPs]=useState(42);
  const path=useMemo(()=>genPath(ps),[ps]);
  const dist=useMemo(()=>genDist(at),[at]);
  const scatterData=useMemo(()=>genScatter(at),[at]);
  const tier=TIERS[at-1];
  const totalPaths=2494;

  return <div style={{maxWidth:960,margin:"0 auto",padding:"48px 24px"}}>
    {/* Context banner — both $ and % */}
    <Card style={{padding:"14px 20px",background:T.persimmonDim,border:`1px solid ${T.persimmon}33`,marginBottom:32}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",flexWrap:"wrap",gap:12}}>
        <div style={{fontSize:13,color:T.textDim}}>
          Typical PUT cost: <span style={{color:T.persimmon,fontWeight:600}}>5-9% of spot</span>
          <span style={{color:T.textMuted}}> → </span>
          After roll-down: <span style={{color:T.green,fontWeight:600}}>~34% recovered</span>
          <span style={{color:T.textMuted}}> → </span>
          Net hedge cost: <span style={{color:T.text,fontWeight:500}}>~5-6% of BTC</span>
        </div>
        <div style={{fontSize:11,color:T.textMuted}}>70% LTV · 12mo · 10% APR</div>
      </div>
    </Card>

    <div style={{textAlign:"center",marginBottom:40}}>
      <div style={{fontSize:12,color:T.persimmon,fontWeight:600,letterSpacing:".12em",textTransform:"uppercase",marginBottom:12}}>PUT Roll-Down Research</div>
      <h1 style={{fontSize:36,fontWeight:700,color:T.text,margin:"0 0 8px"}}>Rolling down cuts the cost of hedging</h1>
      <p style={{fontSize:15,color:T.textDim,margin:"0 0 32px",maxWidth:560,marginLeft:"auto",marginRight:"auto",lineHeight:1.6}}>As monthly payments reduce the outstanding debt, the required PUT strike drops with it. The higher-strike option is worth more than the lower-strike replacement — the difference is returned to the borrower.</p>
    </div>

    <SL n="01" t="Path Explorer"/>
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:20}}>
      <div>
        <h2 style={{fontSize:22,fontWeight:600,color:T.text,margin:"0 0 4px"}}>Single path deep-dive</h2>
        <p style={{fontSize:13,color:T.textDim,margin:0}}>Step through one loan at a time to see how each monthly roll plays out.</p>
      </div>
      <div style={{display:"flex",alignItems:"center",gap:8}}>
        <button onClick={()=>setPs(s=>Math.max(1,s-1))} style={{width:32,height:32,borderRadius:6,border:`1px solid ${T.border}`,background:T.bgCard,color:T.textDim,fontSize:14,cursor:"pointer",fontFamily:"inherit",display:"flex",alignItems:"center",justifyContent:"center"}}>←</button>
        <div style={{padding:"6px 14px",borderRadius:6,background:T.bgCard,border:`1px solid ${T.border}`,fontSize:11,color:T.textDim,fontVariantNumeric:"tabular-nums"}}>Path <span style={{color:T.text,fontWeight:600}}>#{ps}</span> of {fmt(totalPaths)}</div>
        <button onClick={()=>setPs(s=>s+1)} style={{width:32,height:32,borderRadius:6,border:`1px solid ${T.border}`,background:T.bgCard,color:T.textDim,fontSize:14,cursor:"pointer",fontFamily:"inherit",display:"flex",alignItems:"center",justifyContent:"center"}}>→</button>
        <button onClick={()=>setPs(Math.floor(Math.random()*totalPaths)+1)} style={{padding:"6px 14px",borderRadius:6,border:`1px solid ${T.border}`,background:T.bgCardHover,color:T.text,fontSize:11,fontWeight:500,cursor:"pointer",fontFamily:"inherit",display:"flex",alignItems:"center",gap:5}}><span style={{fontSize:13}}>↻</span> Random</button>
      </div>
    </div>

    {/* Debt vs Strike chart — dollars */}
    <Card style={{marginBottom:16}}>
      <div style={{fontSize:12,fontWeight:600,color:T.text,marginBottom:4}}>Debt Balance vs PUT Strike</div>
      <div style={{fontSize:11,color:T.textDim,marginBottom:16}}>The gap between strike (dashed) and debt (solid) is where roll savings come from.</div>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={path.rows}>
          <CartesianGrid stroke={T.border} strokeDasharray="3 3" vertical={false}/>
          <XAxis dataKey="month" tick={{fill:T.textMuted,fontSize:10}} tickLine={false} axisLine={{stroke:T.border}} tickFormatter={v=>"Mo."+v}/>
          <YAxis tick={{fill:T.textMuted,fontSize:10}} tickLine={false} axisLine={false} tickFormatter={v=>"$"+(v/1000).toFixed(0)+"k"}/>
          <Tooltip contentStyle={tt} formatter={v=>fmtUsd(v)}/>
          <Line dataKey="debt" stroke={T.persimmon} strokeWidth={2.5} dot={{r:3,fill:T.persimmon}} name="Debt Balance"/>
          <Line dataKey="strike" stroke={"#2dd4bf"} strokeWidth={1.5} strokeDasharray="6 3" dot={{r:2.5,fill:"#2dd4bf",stroke:"#2dd4bf"}} name="PUT Strike"/>
        </LineChart>
      </ResponsiveContainer>
    </Card>

    {/* Cash flows (dollars) + summary stats (dollars primary, % secondary) */}
    <div style={{display:"grid",gridTemplateColumns:"1fr 300px",gap:16,marginBottom:16}}>
      <Card style={{padding:"16px 20px",overflowX:"auto"}}>
        <div style={{fontSize:12,fontWeight:600,color:T.text,marginBottom:12}}>Roll-down cash flows</div>
        <table style={{width:"100%",borderCollapse:"collapse",fontSize:11,fontVariantNumeric:"tabular-nums"}}>
          <thead><tr>
            {["Mo.","Action","Saving","Cumulative"].map(h=><th key={h} style={{textAlign:h==="Mo."?"center":h==="Action"?"left":"right",padding:"6px 10px",color:T.textMuted,fontWeight:500,borderBottom:`1px solid ${T.border}`,fontSize:9,textTransform:"uppercase",letterSpacing:".06em"}}>{h}</th>)}
          </tr></thead>
          <tbody>{path.rows.map(row=><tr key={row.month} style={{borderBottom:`1px solid ${T.border}22`}}>
            <td style={{textAlign:"center",padding:"7px 10px",color:T.textDim}}>{row.month}</td>
            <td style={{padding:"7px 10px",color:row.rolled?T.textDim:T.textMuted,fontSize:10}}>{row.action}</td>
            <td style={{textAlign:"right",padding:"7px 10px",color:row.saving>0?T.green:T.textMuted,fontWeight:row.saving>0?600:400}}>{row.saving>0?"+"+fmtUsd(row.saving):row.month===0?"-"+fmtUsd(path.ip):"—"}</td>
            <td style={{textAlign:"right",padding:"7px 10px",color:row.month===0?T.persimmon:row.cumSav>0?T.text:T.textMuted,fontWeight:500}}>{row.month===0?"-"+fmtUsd(path.ip):row.cumSav>0?fmtUsd(row.cumSav):"—"}{row.cumSav>0&&row.month>0&&<span style={{color:T.textDim,fontWeight:400,fontSize:9}}> ({fmtPct(row.cumPct)})</span>}</td>
          </tr>)}</tbody>
        </table>
      </Card>

      <div style={{display:"flex",flexDirection:"column",gap:12}}>
        {/* Hero: Recovery % */}
        <Card style={{padding:16,background:T.greenDim,border:`1px solid ${T.green}33`,textAlign:"center"}}>
          <div style={{fontSize:9,color:T.green,textTransform:"uppercase",letterSpacing:".1em",fontWeight:600,marginBottom:6}}>Recovery</div>
          <div style={{fontSize:36,fontWeight:800,color:T.green,fontVariantNumeric:"tabular-nums"}}>{fmtPct(path.recovery)}</div>
          <div style={{fontSize:10,color:T.textDim,marginTop:4}}>{fmtUsd(path.totalSav)} of {fmtUsd(path.ip)} PUT</div>
        </Card>
        {/* Hero: Net cost */}
        <Card style={{padding:16,textAlign:"center"}}>
          <div style={{fontSize:9,color:T.textMuted,textTransform:"uppercase",letterSpacing:".1em",marginBottom:6}}>Net Hedge Cost</div>
          <div style={{fontSize:28,fontWeight:700,color:T.persimmon,fontVariantNumeric:"tabular-nums"}}>{fmtUsd(path.netCost)}</div>
          <div style={{fontSize:10,color:T.textDim,marginTop:4}}>{fmtPct(path.netCostPct)} of spot</div>
        </Card>
        {/* Secondary */}
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
          {[
            {l:"Gross PUT Cost",v:fmtUsd(path.ip),s:fmtPct(path.ipPct)+" of spot",c:T.persimmon},
            {l:"Rolls Executed",v:path.numRolls.toString(),c:T.text},
          ].map((s,i)=><Card key={i} style={{padding:"10px 12px"}}>
            <div style={{fontSize:8,color:T.textMuted,textTransform:"uppercase",letterSpacing:".08em",marginBottom:3}}>{s.l}</div>
            <div style={{fontSize:16,fontWeight:700,color:s.c,fontVariantNumeric:"tabular-nums"}}>{s.v}</div>
            <div style={{fontSize:8,color:T.textDim,marginTop:2}}>{s.s}</div>
          </Card>)}
        </div>
        {/* Tertiary */}
        <Card style={{padding:"10px 12px"}}>
          <div style={{fontSize:10,color:T.textDim,lineHeight:1.7}}>
            <div style={{display:"flex",justifyContent:"space-between"}}><span>Final BTC spot</span><span style={{color:T.text}}>{fmtUsd(path.finalPrice)}</span></div>
            <div style={{display:"flex",justifyContent:"space-between"}}><span>Terminal payoff</span><span style={{color:path.terminalPayoff>0?T.green:T.textDim}}>{fmtUsd(path.terminalPayoff)}</span></div>
          </div>
        </Card>
      </div>
    </div>

    {/* ── Section 2: Tiered Results (directly after path explorer) ── */}
    <div style={{marginTop:40}}>
      <SL n="02" t="Aggregate Results"/>
      <h2 style={{fontSize:22,fontWeight:600,color:T.text,margin:"0 0 6px"}}>Three tiers of evidence</h2>
      <p style={{fontSize:13,color:T.textDim,margin:"0 0 20px"}}>Tier 1 uses only real market data. Tier 2 extends recent loans that haven't matured yet with simulated forward paths. Tier 3 is fully Monte Carlo from today's spot.</p>
      <Tabs tabs={TIERS.map(t=>({id:t.id,label:t.label}))} active={at} onChange={setAt}/>

      {/* Tier description */}
      <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:16}}>
        <Bdg color={tier.color}>{tier.badge}</Bdg>
        <span style={{fontSize:13,color:T.textDim,lineHeight:1.5}}>{tier.desc}</span>
      </div>

      {/* Stats + range bar */}
      <Card style={{padding:"20px 24px",marginBottom:16,background:"linear-gradient(135deg,#0f1d38,#0a1428)",border:`1px solid ${T.borderLight}`}}>
        {/* Key stats row */}
        <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:1,background:T.border,borderRadius:10,overflow:"hidden",marginBottom:20}}>
          {[
            {l:"Recovery (median)",v:fmtPct(tier.mr),c:T.green},
            {l:"Net Hedge Cost",v:fmtPct(tier.netPct),c:T.persimmon},
            {l:"Gross PUT Cost",v:fmtPct(tier.medPutPct),c:T.text},
            {l:"Win Rate",v:fmtPct(tier.posRate),c:T.text,s:fmt(tier.paths)+" "+(at===3?"paths":"loans")},
            {l:"Roll Savings",v:fmtPct(tier.medPutPct-tier.netPct),c:T.green,s:"of BTC value"},
          ].map((s,i)=><div key={i} style={{background:T.bgCard,padding:"14px 14px"}}>
            <div style={{fontSize:8,color:T.textMuted,textTransform:"uppercase",letterSpacing:".08em",marginBottom:4}}>{s.l}</div>
            <div style={{fontSize:18,fontWeight:700,color:s.c,fontVariantNumeric:"tabular-nums"}}>{s.v}</div>
            {s.s&&<div style={{fontSize:8,color:T.textDim,marginTop:2}}>{s.s}</div>}
          </div>)}
        </div>

        {/* Recovery range bar */}
        <div style={{fontSize:10,color:T.textMuted,textTransform:"uppercase",letterSpacing:".08em",marginBottom:10}}>Recovery range</div>
        <div style={{display:"flex",alignItems:"center",gap:16}}>
          <div style={{textAlign:"center",flexShrink:0,minWidth:56}}>
            <div style={{fontSize:16,fontWeight:700,color:T.red,fontVariantNumeric:"tabular-nums"}}>{fmtPct(tier.p5)}</div>
            <div style={{fontSize:8,color:T.textMuted}}>5th pctl</div>
          </div>
          <div style={{flex:1}}>
            <div style={{position:"relative",height:10,background:T.border,borderRadius:5}}>
              <div style={{position:"absolute",left:`${tier.p5/Math.max(tier.p95*1.1,100)*100}%`,right:`${100-tier.p95/Math.max(tier.p95*1.1,100)*100}%`,top:0,bottom:0,background:`linear-gradient(90deg,${T.red}55,${T.yellow}55,${T.green}55)`,borderRadius:5}}/>
              <div style={{position:"absolute",left:`${tier.mr/Math.max(tier.p95*1.1,100)*100}%`,top:-3,width:4,height:16,background:T.green,borderRadius:2,transform:"translateX(-50%)",boxShadow:`0 0 6px ${T.green}66`}}/>
            </div>
            <div style={{display:"flex",justifyContent:"center",marginTop:6}}>
              <span style={{fontSize:10,color:T.green,fontWeight:600}}>▲ median {fmtPct(tier.mr)}</span>
            </div>
          </div>
          <div style={{textAlign:"center",flexShrink:0,minWidth:56}}>
            <div style={{fontSize:16,fontWeight:700,color:T.green,fontVariantNumeric:"tabular-nums"}}>{fmtPct(tier.p95)}</div>
            <div style={{fontSize:8,color:T.textMuted}}>95th pctl</div>
          </div>
        </div>

        {/* One-liner */}
        <div style={{fontSize:12,color:T.textDim,marginTop:16,paddingTop:14,borderTop:`1px solid ${T.border}`,lineHeight:1.6}}>
          The median borrower recovers <span style={{color:T.green,fontWeight:600}}>{fmtPct(tier.mr)}</span> of the PUT cost, bringing the net hedge from {fmtPct(tier.medPutPct)} down to <span style={{color:T.persimmon,fontWeight:600}}>{fmtPct(tier.netPct)} of BTC</span>.
        </div>
      </Card>

      {/* Chart view toggle: Scatter vs Distribution */}
      {(()=>{const[chartView,setChartView]=React.useState("scatter");return <>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12}}>
          <div style={{fontSize:13,fontWeight:600,color:T.text}}>{chartView==="scatter"?tier.chartTitle:"Distribution of Premium Recovery (%)"}</div>
          <div style={{display:"flex",gap:0,border:`1px solid ${T.border}`,borderRadius:6,overflow:"hidden"}}>
            {[{id:"scatter",label:"Scatter"},{id:"dist",label:"Distribution"}].map(v=>
              <button key={v.id} onClick={()=>setChartView(v.id)} style={{padding:"5px 14px",background:chartView===v.id?T.bgCardHover:"transparent",border:"none",color:chartView===v.id?T.text:T.textDim,fontSize:11,fontWeight:500,cursor:"pointer",fontFamily:"inherit"}}>{v.label}</button>
            )}
          </div>
        </div>
        <Card style={{marginBottom:20}}>
          <div style={{fontSize:11,color:T.textDim,marginBottom:14}}>
            {chartView==="scatter"
              ?(at===3?"Each dot is one simulated path. X = final BTC price, Y = % of PUT premium recovered."
                :"Each dot is one loan. X = start date, Y = % of PUT premium recovered. Gray line = BTC spot.")
              :"How recovery outcomes are distributed. Most loans recover 10-50% of the PUT cost. In bear markets, some exceed 100%."}
          </div>

          {chartView==="scatter" ? (
            <ResponsiveContainer width="100%" height={320}>
              {at===3 ? (
                <ScatterChart margin={{left:10,right:10,bottom:20}}>
                  <CartesianGrid stroke={T.border} strokeDasharray="3 3"/>
                  <XAxis dataKey="finalPrice" type="number" tick={{fill:T.textMuted,fontSize:9}} tickLine={false} axisLine={{stroke:T.border}} tickFormatter={v=>"$"+(v/1000).toFixed(0)+"k"} name="Final BTC" label={{value:"Final BTC Spot ($)",position:"bottom",offset:5,fill:T.textMuted,fontSize:10}}/>
                  <YAxis dataKey="recovery" type="number" tick={{fill:T.textMuted,fontSize:9}} tickLine={false} axisLine={false} name="Recovery %" label={{value:"% of Premium Recovered",angle:-90,position:"insideLeft",fill:T.textMuted,fontSize:10}}/>
                  <Tooltip content={<ScatterTip isTier3={true}/>} cursor={{strokeDasharray:"3 3",stroke:T.border}}/>
                  <ReferenceLine y={tier.mr} stroke={"#2dd4bf"} strokeDasharray="4 4" label={{value:"Median "+fmtPct(tier.mr),fill:"#2dd4bf",fontSize:10,position:"right"}}/>
                  <Scatter data={scatterData} fill={T.persimmon} fillOpacity={.7} r={3}/>
                </ScatterChart>
              ) : (
                <ScatterChart margin={{left:10,right:40,bottom:20}}>
                  <CartesianGrid stroke={T.border} strokeDasharray="3 3"/>
                  <XAxis dataKey="date" type="number" tick={{fill:T.textMuted,fontSize:9}} tickLine={false} axisLine={{stroke:T.border}} tickFormatter={v=>new Date(v).toLocaleDateString("en-US",{month:"short",year:"2-digit"})} name="Date" label={{value:"Loan Start Date",position:"bottom",offset:5,fill:T.textMuted,fontSize:10}} domain={["dataMin","dataMax"]}/>
                  <YAxis yAxisId="left" dataKey="recovery" type="number" tick={{fill:T.textMuted,fontSize:9}} tickLine={false} axisLine={false} name="Recovery %" label={{value:"% of Premium Recovered",angle:-90,position:"insideLeft",fill:T.textMuted,fontSize:10}}/>
                  <YAxis yAxisId="right" orientation="right" dataKey="btcPrice" type="number" tick={{fill:T.textMuted,fontSize:9}} tickLine={false} axisLine={false} tickFormatter={v=>"$"+fmt(v)} label={{value:"BTC Spot ($)",angle:90,position:"insideRight",fill:T.textMuted,fontSize:10}}/>
                  <Tooltip content={<ScatterTip isTier3={false}/>} cursor={{strokeDasharray:"3 3",stroke:T.border}}/>
                  <ReferenceLine yAxisId="left" y={tier.mr} stroke={"#2dd4bf"} strokeDasharray="4 4" label={{value:"Median "+fmtPct(tier.mr),fill:"#2dd4bf",fontSize:10,position:"right"}}/>
                  <Scatter yAxisId="left" data={scatterData} fill={T.persimmon} fillOpacity={.7} r={3}/>
                </ScatterChart>
              )}
            </ResponsiveContainer>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={dist} barCategoryGap="6%">
                <CartesianGrid stroke={T.border} strokeDasharray="3 3" vertical={false}/>
                <XAxis dataKey="bin" tick={{fill:T.textMuted,fontSize:9}} tickLine={false} axisLine={{stroke:T.border}} tickFormatter={v=>v+"%"}/>
                <YAxis tick={{fill:T.textMuted,fontSize:9}} tickLine={false} axisLine={false}/>
                <Tooltip content={({active,payload})=>{
                  if(!active||!payload?.[0])return null;
                  const d=payload[0].payload;
                  return <div style={{background:T.bg,border:`1px solid ${T.border}`,borderRadius:8,padding:"8px 12px",fontSize:11,boxShadow:"0 4px 20px rgba(0,0,0,.4)",fontVariantNumeric:"tabular-nums",minWidth:140}}>
                    <div style={{fontWeight:600,color:T.text,marginBottom:4}}>{d.bin}–{d.binEnd}% recovery</div>
                    <div style={{display:"flex",justifyContent:"space-between",gap:16}}><span style={{color:T.textDim}}>Count</span><span style={{color:T.persimmon,fontWeight:600}}>{d.count} {at===3?"paths":"loans"}</span></div>
                    <div style={{display:"flex",justifyContent:"space-between",gap:16}}><span style={{color:T.textDim}}>% of total</span><span style={{color:T.text}}>{d.pct}%</span></div>
                  </div>;
                }}/>
                <ReferenceLine x={tier.mr} stroke={"#2dd4bf"} strokeDasharray="4 4" label={{value:"Median "+fmtPct(tier.mr),fill:"#2dd4bf",fontSize:9,position:"top"}}/>
                <Bar dataKey="count" fill={T.persimmon} fillOpacity={.8} radius={[2,2,0,0]}/>
              </BarChart>
            </ResponsiveContainer>
          )}

          {/* Legend */}
          <div style={{display:"flex",gap:20,justifyContent:"center",marginTop:10,fontSize:10,color:T.textDim}}>
            {chartView==="scatter"&&at!==3&&<span><span style={{color:T.textMuted+"66"}}>——</span> BTC Spot</span>}
            <span><span style={{color:"#2dd4bf"}}>- - -</span> Median ({fmtPct(tier.mr)})</span>
            <span><span style={{display:"inline-block",width:8,height:8,borderRadius:"50%",background:T.persimmon,verticalAlign:"middle",marginRight:4}}/>{chartView==="scatter"?"% Recovered":"Count"}</span>
          </div>

          {/* Insight callout */}
          {chartView==="scatter"&&<div style={{marginTop:16,padding:"12px 16px",borderRadius:8,background:T.bg,border:`1px solid ${T.border}`,display:"flex",gap:12,alignItems:"flex-start"}}>
            <div style={{width:20,height:20,borderRadius:"50%",background:T.green+"22",display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0,marginTop:1}}><span style={{fontSize:10,color:T.green}}>↑</span></div>
            <div style={{fontSize:11,color:T.textDim,lineHeight:1.6}}>
              {at===3
                ?<span>Low recovery at high final prices is the best outcome. BTC appreciated so much that the PUT expired worthless, but your collateral gained far more than the insurance cost.</span>
                :<span><span style={{color:T.text,fontWeight:500}}>Low recovery = BTC pumped.</span> When recovery is near zero, BTC rallied sharply from the loan start. The PUT expired worthless, but the borrower's BTC appreciated far more than the insurance cost.</span>}
            </div>
          </div>}
        </Card>
      </>})()}
    </div>

    {/* ── Methodology — collapsible ── */}
    {(()=>{const[showMethod,setShowMethod]=React.useState(false);return <div style={{marginTop:40}}>
      <Card style={{padding:"14px 20px",cursor:"pointer"}} onClick={()=>setShowMethod(!showMethod)}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <div style={{display:"flex",alignItems:"center",gap:10}}>
            <SL n="03" t="Methodology"/>
          </div>
          <span style={{fontSize:14,color:T.textMuted,transform:showMethod?"rotate(180deg)":"none",transition:"transform .2s"}}>▾</span>
        </div>
        {!showMethod&&<div style={{fontSize:12,color:T.textDim,marginTop:4}}>Key assumptions, data sources, and limitations behind these numbers.</div>}
      </Card>
      {showMethod&&<div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16,marginTop:16}}>
        {[
          {t:"Option Pricing",b:"Black-Scholes, European cash-settled PUTs. Risk-free rate assumed zero (crypto convention). IV from SVI surface."},
          {t:"IV Surface",b:"Deribit options trades, 700+ days of data. SVI parameterization, 26 moneyness points."},
          {t:"GBM Calibration",b:"~3yr Binance BTCUSDT hourly candles. Daily log returns for drift and vol estimation."},
          {t:"Assumptions",b:"IV held constant for forward projections. No transaction fees. Monthly roll checkpoints. Constant GBM parameters."},
        ].map((f,i)=><Card key={i}><div style={{fontSize:13,fontWeight:600,color:T.text,marginBottom:8}}>{f.t}</div><div style={{fontSize:12,color:T.textDim,lineHeight:1.6}}>{f.b}</div></Card>)}
      </div>}
    </div>})()}
  </div>;
};

export default function App(){
  const[v,setV]=useState("configure");
  return <div style={{minHeight:"100vh",background:T.bg,color:T.text,fontFamily:"'Bricolage Grotesque','DM Sans',system-ui,sans-serif"}}>
    <style>{`@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@400;500;600;700;800&family=DM+Sans:wght@400;500;600&display=swap');*{box-sizing:border-box;margin:0;padding:0}::-webkit-scrollbar{width:6px;height:6px}::-webkit-scrollbar-track{background:${T.bg}}::-webkit-scrollbar-thumb{background:${T.border};border-radius:3px}input[type="range"]{-webkit-appearance:none;appearance:none;background:${T.border};border-radius:2px;outline:none}input[type="range"]::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;border-radius:50%;background:${T.persimmon};cursor:pointer;border:2px solid ${T.bg}}`}</style>
    <Nav active={v} onChange={setV}/>
    {v==="configure"&&<V1 onNav={setV}/>}
    {v==="backtest"&&<V2/>}
    <footer style={{borderTop:`1px solid ${T.border}`,padding:"24px 32px",marginTop:48,display:"flex",justifyContent:"space-between",alignItems:"center"}}><div style={{fontSize:12,color:T.textMuted}}>bitmor.xyz — Educational tool. Not financial advice.</div><a href="https://bitmor.xyz/loans" target="_blank" rel="noopener" style={{fontSize:12,color:T.persimmon,textDecoration:"none",fontWeight:500}}>Join the Loan Waitlist →</a></footer>
  </div>;
}
