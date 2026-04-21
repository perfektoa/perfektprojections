const fs = require("fs");
const hitters = JSON.parse(fs.readFileSync("public/data/hitters.json", "utf8"));

const P = {
  MATURITY_AGE:25,GAP_MAX:0.95,GAP_STEEPNESS:0.6,
  RISK_FLOOR:0.80,RISK_CEILING:0.95,
  PEAK_END:25,DECLINE_RATE:0.06,CLIFF_AGE:30,CLIFF_RATE:0.12,
  DISCOUNT_RATE:0.03,MAX_CAREER_AGE:34,DEFAULT_YEARS_OF_CONTROL:6
};

function gf(age,p){
  const i=(16+p.MATURITY_AGE)/2;
  const r=1/(1+Math.exp(-p.GAP_STEEPNESS*(age-i)));
  const m=1/(1+Math.exp(-p.GAP_STEEPNESS*(p.MATURITY_AGE-i)));
  const s=1/(1+Math.exp(-p.GAP_STEEPNESS*(16-i)));
  return Math.max(0,Math.min(p.GAP_MAX,((r-s)/(m-s))*p.GAP_MAX));
}

function af(age,p){
  if(age<=p.PEAK_END)return 1;
  if(age<=p.CLIFF_AGE)return Math.pow(1-p.DECLINE_RATE,age-p.PEAK_END);
  return Math.pow(1-p.DECLINE_RATE,p.CLIFF_AGE-p.PEAK_END)*Math.pow(1-p.CLIFF_RATE,age-p.CLIFF_AGE);
}

function getPlayerRisk(age,gap,hasPot,p){
  if(!hasPot || gap<=0) return p.RISK_CEILING;
  const progress=Math.min(1,gf(age,p)/p.GAP_MAX);
  const gapCert=Math.max(0,1-(gap/10));
  const combined=0.6*progress+0.4*gapCert;
  return p.RISK_FLOOR+combined*(p.RISK_CEILING-p.RISK_FLOOR);
}

const A=[{r:-15,f:20},{r:-8,f:25},{r:-3,f:30},{r:0,f:40},{r:2,f:45},{r:5,f:50},{r:9,f:55},{r:14,f:60},{r:20,f:65},{r:28,f:70},{r:45,f:80}];

function scale(v){
  if(v<=A[0].r)return A[0].f;
  if(v>=A[A.length-1].r)return A[A.length-1].f;
  for(let i=0;i<A.length-1;i++){
    if(v>=A[i].r && v<A[i+1].r){
      const t=(v-A[i].r)/(A[i+1].r-A[i].r);
      return Math.round(A[i].f+t*(A[i+1].f-A[i].f));
    }
  }
  return 40;
}

function calc(player) {
  const age = parseFloat(player.Age)||25;
  let cw=-Infinity;
  for(const c of ["Max WAA wtd","Max WAA vR","WAA wtd","WAA wtd RP"]){
    const v=parseFloat(player[c]);if(!isNaN(v)&&v>cw)cw=v;
  }
  if(cw===-Infinity)cw=0;
  let pw=null;
  for(const c of ["MAX WAA P","WAP","WAP RP"]){
    const v=parseFloat(player[c]);if(!isNaN(v)&&(pw===null||v>pw))pw=v;
  }
  const hp=pw!==null;if(!hp)pw=cw;
  const gap=pw-cw;
  const risk=getPlayerRisk(age,gap,hp,P);
  const ep=hp&&gap>0?cw+gap*P.GAP_MAX*risk:cw;
  const projToAge=Math.min(P.MAX_CAREER_AGE,Math.max(age+P.DEFAULT_YEARS_OF_CONTROL,P.PEAK_END+2));
  const py=Math.max(1,projToAge-age);
  let t=0;
  if(hp&&gap>0){
    const sa=Math.max(age,P.MATURITY_AGE);
    for(let y=0;y<py;y++){
      const fa=age+y;if(fa<sa)continue;
      const w=fa<=P.PEAK_END?ep:ep*af(fa,P);
      t+=w*Math.pow(1-P.DISCOUNT_RATE,y);
    }
  } else {
    for(let y=0;y<py;y++){
      const fa=age+y;
      const w=fa<=P.PEAK_END?ep:ep*af(fa,P);
      t+=w*Math.pow(1-P.DISCOUNT_RATE,y);
    }
  }
  let ptp;
  if(!hp||pw<=0){ptp=100;}
  else if(cw<=0){ptp=Math.round(gf(age,P)/P.GAP_MAX*100);}
  else{ptp=Math.min(100,Math.round((cw/pw)*100));}
  const ytpeak = Math.max(0, P.MATURITY_AGE - age);
  return { rawFV:t, fvScale:scale(t), currentWAA:cw, potentialWAA:pw, hasPotential:hp, pctToPeak:ptp, yearsTilPeak:ytpeak, expectedPeak:ep, projYears:py };
}

// Test specific players
const tests = [
  {name:"Cameron Snow",find:"CAMERON SNOW"},
  {name:"David Saldivar",find:"DAVID SALDIVAR"},
  {name:"Yoshimoto",find:"TERUYUKI YOSHIMOTO"},
  {name:"Ben Reed",find:"BEN REED"},
  {name:"Eric Crippen",find:"ERIC CRIPPEN"},
  {name:"Rusty Garbarino",find:"RUSTY GARBARINO"},
  {name:"Jayden Trotter",find:"JAYDEN TROTTER"},
];

console.log("Player                    Age  CurrWAA  PotWAA  %Peak  ETA  ProjYr  RawFV  FV");
console.log("-".repeat(80));
for (const t of tests) {
  const p = hitters.find(h => h.Name && h.Name.toUpperCase().includes(t.find));
  if (!p) { console.log(t.name + " NOT FOUND"); continue; }
  const r = calc(p);
  const eta = r.yearsTilPeak > 0 ? r.yearsTilPeak+"yr" : "Now";
  console.log(
    t.name.padEnd(26) +
    Math.round(parseFloat(p.Age)||0).toString().padStart(3) +
    r.currentWAA.toFixed(1).padStart(9) +
    r.potentialWAA.toFixed(1).padStart(8) +
    (r.pctToPeak+"%").padStart(7) +
    eta.padStart(5) +
    r.projYears.toString().padStart(7) +
    r.rawFV.toFixed(1).padStart(8) +
    r.fvScale.toString().padStart(4)
  );
}

// Aging factor table
console.log("\n=== AGING FACTOR BY AGE ===");
for (let age = 24; age <= 34; age++) {
  const factor = af(age, P);
  console.log("  Age " + age + ": " + (factor*100).toFixed(1) + "% of peak");
}

// Distribution
console.log("\n=== FV DISTRIBUTION ===");
const allFV = hitters.map(p => calc(p).fvScale);
const fv40 = allFV.filter(f=>f>=40).length;
const fv50 = allFV.filter(f=>f>=50).length;
const fv60 = allFV.filter(f=>f>=60).length;
const fv70 = allFV.filter(f=>f>=70).length;
console.log("FV 40+:", fv40, "(" + (fv40/hitters.length*100).toFixed(1) + "%)");
console.log("FV 50+:", fv50, "(" + (fv50/hitters.length*100).toFixed(1) + "%)");
console.log("FV 60+:", fv60, "(" + (fv60/hitters.length*100).toFixed(1) + "%)");
console.log("FV 70+:", fv70, "(" + (fv70/hitters.length*100).toFixed(1) + "%)");
