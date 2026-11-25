#!/usr/bin/env node
// SPDX-License-Identifier: GPL-2.0-only
// Rootless exact workflow replay; does not execute the inspected workflows.
import {execFileSync} from 'node:child_process';
function require(v,r){if(!v)throw Error("ROUND091_ROUTING_FIRST_ERROR "+r)}

function norm(s){return s.replace(/\n+$/,"\n")}

function jobs(s){const k=s.indexOf("\njobs:\n")+1;require(k>0,"jobs header");const body=s.slice(k+6),marks=[...body.matchAll(/^  ([A-Za-z0-9_-]+):\n/gm)];require(marks.length,"job boundaries");return {header:s.slice(0,k),jobs:marks.map((x,i)=>({id:x[1],body:body.slice(x.index,i+1<marks.length?marks[i+1].index:undefined)}))}}

function hasVM(s){return /(?:kunit\.py\s+(?:run|exec|build)|qemu-system-|--arch[= ](?:um|uml)(?:\s|$))/im.test(s)}

function pushEvent(s){const start=s.indexOf("\non:");if(start<0)return null;const on=s.slice(start+1).match(/^on:[^\n]*\n(?:[ \t#][^\n]*\n|\n)*/);if(!on)return null;const body=on[0];if(/\bpush\b/.test(body.split("\n")[0]))return {raw:body,paths:null};const match=/^  push:[^\n]*\n((?:    [^\n]*\n|\n)*)/m.exec(body);if(!match)return null;const p=/^    paths:\n((?:      - [^\n]+\n)+)/m.exec(match[0]);return {raw:match[0],paths:p?p[1].trimEnd().split("\n").map(l=>l.trim().slice(2).replace(/^['"]|['"]$/g,"")):null}}

function pathMatches(p,s){require(/^[A-Za-z0-9_./*-]+$/.test(p),"unsupported glob "+p);return new RegExp("^"+p.split("/").map(x=>x==="**"?".*":x.replaceAll(".","\\.").replaceAll("*","[^/]*")).join("/")+"$").test(s)}

function transform(s,e){
 const {path,id,kind,companion}=e,p=jobs(s),target=p.jobs.find(j=>j.id===id);require(target&&hasVM(target.body),"missing VM "+path);require(p.jobs.filter(j=>hasVM(j.body)).length===1,"multiple VM jobs "+path);
 let body=target.body,tail="";
 if(kind==="origin"){
  const mark='            config="$RUNNER_TEMP/origin-$profile.kunitconfig"\n',a=body.indexOf(mark),b=body.indexOf('      - name: "Retain bounded source and failure evidence"\n');require(a>0&&b>a,"origin cut");
  tail=body.slice(b).replace("name: phase-a-bio-origin-kunit\n","name: phase-a-bio-origin-source-objects-only\n");
  body=body.slice(0,a)+"            printf 'kunit_executed=no\\nresult=PASS_SOURCE_OBJECTS_ONLY\\n' >> \"$manifest\"\n          done\n          manifest=\"$evidence/setup.txt\"\n          printf 'source_modified=yes\\nkunit_executed=no\\nresult=PASS_SOURCE_OBJECTS_ONLY\\n' >> \"$manifest\"\n"+tail;
  body=body.replace('name: "Stage actual Linux source, build y/n and execute KUnit"','name: "Stage actual Linux source and compile y/n objects only (no VM)"');
 }else{
  const stop=kind==="credential"?/^      - name: Install ephemeral original UML build dependencies\n/m:kind==="sideband"?/^      - name: Build and BOOT disposable UML[^\n]*\n/m:/^      - name: "?(?:Real original UML boot|Boot REAL UML)[^\n]*\n/m;
  const a=stop.exec(body);require(a&&a.index>0,"VM step boundary "+path);
  if(kind!=="sideband"){
   const u=/^      - (?:uses: actions\/upload-artifact@v4|name: (?:Retain|"Retain)[^\n]*\n        if: always\(\)\n        uses: actions\/upload-artifact@v4)\n/m.exec(body.slice(a.index));require(u,"artifact boundary "+path);
   tail=body.slice(a.index+u.index).replace(/^      - name: [^\n]+/m,"      - name: Retain source-only evidence (no VM)").replace(/^          name: ([^\n]+)$/m,"          name: $1-source-only");
   if(kind==="v1")tail=tail.split("\n").filter(l=>!/(?:original-uml-first-error|original-v1-evidence|original-v1\.kunitconfig|original-v1\.json|original-uml\/test\.log)/.test(l)).join("\n");
  }
  body=body.slice(0,a.index)+tail;
 }
 if(/^    name: [^\n]+\n/m.test(body))body=body.replace(/^    name: [^\n]+\n/m,"    name: Original host and source staging only (no VM)\n");else body=body.replace("    runs-on:","    name: Original host and source checks only (no VM)\n    runs-on:");
 require(!hasVM(body),"VM retained "+path);
 const jobBody=p.jobs.map(j=>j.id===id?body:j.body).join(""),event=pushEvent(s);require(event?.paths?.includes(path),"missing self path "+path);
 const manual=p.header.includes("  workflow_dispatch:\n");let automatic,manualSource;
 if(kind==="credential"){
  require(!manual&&companion===path,"push-only credential");automatic=norm(p.header+"jobs:\n"+jobBody).replace(/^name: [^\n]+\n/,"name: Round084 pinned original credential host and stage only NO_AUTH\n");manualSource=s;
 }else{
  require(manual&&companion!==path,"manual contract "+path);
  const self=event.raw.split("\n").find(l=>l.includes(path));require(self,"self line "+path);
  const ae=event.raw.replace(self+"\n",self+"\n"+self.replace(path,companion)+"\n"),title=p.header.split("\n")[0].slice(6).replace(/^"|"$/g,"");
  automatic=norm(p.header.replace(/^name: [^\n]+\n/,`name: "${title} (automatic source-only; no VM)"\n`).replace(event.raw,ae).replace("  workflow_dispatch:\n","")+"jobs:\n"+jobBody);
  manualSource=p.header.replace(event.raw,"  # Historical native lane: explicit dispatch only.\n")+"jobs:\n"+p.jobs.map(j=>j.body).join("");
  require(jobs(manualSource).jobs.map(j=>j.body).join("")===p.jobs.map(j=>j.body).join("")&&!pushEvent(manualSource)&&manualSource.includes("  workflow_dispatch:\n"),"manual drift "+path);
 }
 const ap=pushEvent(automatic);require(ap?.paths&&event.paths.every(x=>ap.paths.includes(x))&&!automatic.includes("  workflow_dispatch:\n")&&!hasVM(automatic),"auto drift "+path);
 return {automatic,manualSource,oldPaths:event.paths,retainedJobs:p.jobs.length};
}

function generateMixed(before,plan){
 const out=new Map();let witnesses=0,preserved=0;
 for(const e of plan.mixed){const s=before.get(e.path);require(s,"missing "+e.path);const r=transform(s,e);out.set(e.companion,r.automatic);out.set(e.kind==="credential"?plan.archive:e.path,r.manualSource);preserved+=r.retainedJobs;const auto=pushEvent(r.automatic);for(const pattern of r.oldPaths){const w=pattern.replaceAll("**","nested/example.c").replaceAll("*","example");require(pathMatches(pattern,w)&&auto.paths.some(p=>pathMatches(p,w)),"witness "+e.path+":"+pattern);++witnesses}}
 return {out,witnesses,preserved};
}

function verifyMixed(before,after,plan){const g=generateMixed(before,plan);for(const [p,c] of g.out){require(after.get(p)===c,"generated bytes "+p);if(p.startsWith(".github/workflows/")&&pushEvent(c))require(c.endsWith("\n")&&!c.endsWith("\n\n")&&!hasVM(c),"auto EOF/VM "+p)}return {mixed:plan.mixed.length,manual:plan.mixed.filter(x=>x.kind!=="credential").length,archived:1,preservedJobs:g.preserved,witnesses:g.witnesses}}

function verify(before,after,plan){const result=verifyMixed(before,after,plan);for(const p of plan.eof){const old=before.get(p);require(old&&old.endsWith("\n\n")&&norm(old)+"\n"===old&&after.get(p)===norm(old),"EOF "+p)}const mandatory=".github/workflows/project-goals.yml";require(before.get(mandatory)===after.get(mandatory)&&pushEvent(after.get(mandatory)),"mandatory drift");const vm=[...after].filter(([p,c])=>p.startsWith(".github/workflows/")&&pushEvent(c)&&hasVM(c)).map(([p])=>p);require(!vm.length,"automatic VM inventory "+vm.join(","));return {...result,eof:plan.eof.length,autoVM:vm.length}}

function negativeTests(before,after,plan,full=false){
 const labels=[],e=plan.mixed.find(x=>x.kind==="origin"),p=e.companion,other=plan.mixed.find(x=>x.kind==="ordinary").companion;
 function reject(label,file,change){const mutant=new Map(after);const prior=mutant.get(file),updated=change(prior);require(prior!==updated,"ineffective mutant "+label);mutant.set(file,updated);let killed=false;try{(full?verify:verifyMixed)(before,mutant,plan)}catch(x){killed=String(x.message).startsWith("ROUND091_ROUTING_FIRST_ERROR")}require(killed,"surviving negative "+label);labels.push(label)}
 reject("restore-automatic-VM",p,()=>before.get(e.path));reject("lose-manual",e.path,x=>x.replace("  workflow_dispatch:\n",""));reject("lose-rootless",p,x=>x.replace("run_checked rootless ","run_checked missing "));reject("lose-source-filter",other,x=>x.replace(/^      - [^\n]+\n/m,""));reject("alter-compile-job",p,x=>x.replace("modified_objects make","modified_objects false"));reject("mutate-archive",plan.archive,x=>x+"\n");reject("blank-new-companion",other,x=>x+"\n");if(full){reject("restore-EOF",plan.eof[0],x=>x+"\n");reject("weaken-mandatory",".github/workflows/project-goals.yml",x=>x.replace(" --enforce",""))}return labels;
}


// Exact changed-path witnesses are separate from real GitHub run registration.
function census(map, paths) {
 const selected=[];
 for(const [path, content] of map){
  if(!path.startsWith(".github/workflows/")) continue;
  const event=pushEvent(content);
  if(!event) continue;
  if(event.paths===null||paths.some(changed=>event.paths.some(pattern=>pathMatches(pattern,changed)))){
   const parsed=jobs(content);
   selected.push({path,jobs:parsed.jobs.length,vmJobs:parsed.jobs.filter(job=>hasVM(job.body)).length});
  }
 }
 return {workflows:selected.length,jobs:selected.reduce((n,x)=>n+x.jobs,0),vmJobs:selected.reduce((n,x)=>n+x.vmJobs,0),paths:selected.map(x=>x.path)};
}

try {
 const git = args => execFileSync("git",args,{encoding:"utf8",maxBuffer:32*1024*1024});
 const sha = process.argv[2];
 require(process.argv.length===3 && /^[0-9a-f]{40}$/.test(sha??""),"exact revision required");
 const show = (revision,path) => git(["show",revision+":"+path]);
 const plan = JSON.parse(show(sha,"docs/handoff/zswapz/round091/agent2-workflow-manifest.json")).plan;
 require(/^[0-9a-f]{40}$/.test(plan.baseline),"baseline");
 const load = revision => new Map(git(["ls-tree","-r","--name-only",revision,"--",".github/workflows"]).trim().split("\n").map(path=>[path,show(revision,path)]));
 const before=load(plan.baseline),after=load(sha);after.set(plan.archive,show(sha,plan.archive));
 const result=verify(before,after,plan), negatives=negativeTests(before,after,plan,true);
 const changed=git(["diff","--name-only",sha+"^",sha]).trim().split("\n");
 const scenarios=[
  ["ordinary-DM",["src/kernel/dm-target.c"]],
  ["codec",["src/kernel/codec.c"]],
  ["original-composer",["tests/tools/stage-pinned-linux-zswap-composed.py"]],
  ["standards",["docs/testing_standards.md"]],
  ["physical-helper",["tests/tools/physical-swap-probe.py"]],
  ["exact-push",changed]
 ].map(([name,paths])=>({name,before:census(before,paths),after:census(after,paths)}));
 require(scenarios.every(s=>s.after.vmJobs===0),"automatic VM witness");
 console.log(JSON.stringify({status:"PASS_ROOTLESS_PHYSICAL_FIRST_ROUTING",...result,negatives,before_workflows:before.size,after_workflows:after.size-1,scenarios}));
} catch(error) { console.error(String(error.message).slice(0,400));process.exitCode=1; }
