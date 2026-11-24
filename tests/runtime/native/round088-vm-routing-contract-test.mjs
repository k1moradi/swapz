#!/usr/bin/env node
// SPDX-License-Identifier: GPL-2.0-only
// Rootless offline replay of the frozen and migrated Git workflow trees.
import {execFileSync} from "node:child_process";
import {createHash} from "node:crypto";
function regression(before,after,archiveText,plan) {
    let checks=0;
    function require(condition, reason) {
        if(!condition) throw Error("ROUND088_VM_ROUTING_FIRST_ERROR "+reason);
        ++checks;
    }
    const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
    const sorted=x=>[...x].sort();
    const vm=/(?:kunit\.py\s+(?:run|exec)|qemu-system-|--arch[= ](?:um|uml))/i;
    const old=new Map(before.map(r=>[r.path,r])),next=new Map(after.map(r=>[r.path,r]));
    function parse(row) {
        const s=row.content;
        require(!s.includes("\r"),"unexpected-newline:"+row.path);
        const block=/^on:\n([\s\S]*?)(?=^[^\s#])/m.exec(s);
        require(block!==null,"event-block:"+row.path);
        const lines=block[1].split("\n").filter(l=>l.trim()&&!l.trimStart().startsWith("#"));
        let i=0,push=false,main=false,paths=null,manual=false;
        if(lines[i]==="  push:"){
            push=true;++i;
            if(lines[i]==="    branches: [main]"){main=true;++i;}
            if(lines[i]==="    paths:"){
                paths=[];++i;
                while(i<lines.length&&lines[i].startsWith("      - ")){
                    const line=lines[i++],quoted=/^      - (['"])([A-Za-z0-9_./*-]+)\1$/.exec(line),plain=/^      - ([A-Za-z0-9_./-]+)$/.exec(line);
                    require(Boolean(quoted||plain),"unsupported-path:"+row.path);
                    const p=quoted?quoted[2]:plain[1];
                    require(!paths.includes(p),"duplicate-path:"+row.path);
                    paths.push(p);
                }
                require(paths.length>0,"empty-filter:"+row.path);
            }
        }
        if(lines[i]==="  workflow_dispatch:"){manual=true;++i;}
        require(i===lines.length&&(push||manual),"unsupported-event:"+row.path);
        const jobIndex=s.indexOf("\njobs:\n")+1;
        require(jobIndex>0,"missing-jobs:"+row.path);
        const body=s.slice(jobIndex+6);
        const marks=[...body.matchAll(/^  ([A-Za-z0-9_-]+):\n/gm)];
        const jobs=marks.map((m,i)=>({id:m[1],body:body.slice(m.index,i+1<marks.length?marks[i+1].index:undefined)}));
        require(jobs.length>0&&new Set(jobs.map(j=>j.id)).size===jobs.length,"job-census:"+row.path);
        return {push,main,paths,manual,jobs,body,header:s.slice(0,jobIndex)};
    }
    function match(pattern,path){
        require(/^[A-Za-z0-9_./*-]+$/.test(pattern),"unsupported-pattern:"+pattern);
        const parts=pattern.split("/");
        require(parts.every((p,i)=>!p.includes("**")||(p==="**"&&i===parts.length-1)),"unsupported-globstar:"+pattern);
        return new RegExp("^"+parts.map(p=>p==="**"?".*":p.replaceAll(".","\\.").replaceAll("*","[^/]*")).join("/")+"$").test(path);
    }
    const matches=(t,paths)=>t.push&&(t.paths===null||paths.some(p=>t.paths.some(q=>match(q,p))));
    const expectedPaths=sorted([...old.keys(),...plan.selected.map(p=>p.replace(/\.yml$/,"-source-push.yml"))]);
    require(equal(sorted(next.keys()),expectedPaths)&&old.size===before.length&&next.size===after.length,"inventory-drift");
    const op=new Map(before.map(r=>[r.path,parse(r)])),np=new Map(after.map(r=>[r.path,parse(r)]));
    const changed=new Set([...plan.selected,plan.archivedQemu]);
    let witnesses=0,manuals=0,autoJobs=0,vmJobs=0;
    function verifySplit(path,manualRow,pushRow){
        const b=op.get(path),m=parse(manualRow),a=parse(pushRow),companion=pushRow.path;
        require(b.push&&b.manual&&!m.push&&m.manual&&a.push&&!a.manual&&a.main===b.main,"event-routing:"+path);
        require(m.body===b.body,"manual-job-body-drift:"+path);
        const selected=b.jobs.filter(j=>!vm.test(j.body)),removed=b.jobs.filter(j=>vm.test(j.body));
        require(removed.length===1&&selected.length>0&&equal(a.jobs,selected),"automatic-job-body-drift:"+path);
        require(!a.jobs.some(j=>vm.test(j.body)),"VM-on-automatic:"+path);
        require(equal(a.paths,b.paths.flatMap(p=>p===path?[p,companion]:[p])),"automatic-source-path-drift:"+path);
        for(const job of selected) require(!job.body.split("\n").some(l=>/^    needs:/.test(l)&&l.includes(removed[0].id)),"automatic-depends-on-VM:"+path);
        // Compare every other header byte, apart from display name and event routing.
        const push=b.header.slice(b.header.indexOf("  push:\n"),b.header.indexOf("  workflow_dispatch:\n"));
        const expectedManual=b.header.replace(push,"  # Archived native lane; explicit dispatch only (owner physical-first).\n");
        require(m.header===expectedManual,"manual-header-drift:"+path);
        const self=push.split("\n").find(l=>l.includes(path));
        require(Boolean(self),"original-self-missing:"+path);
        const pushWithSelf=push.replace(self+"\n",self+"\n"+self.replace(path,companion)+"\n");
        const nameLine=b.header.split("\n")[0],name=nameLine.slice(6).replace(/^"|"$/g,"");
        const expectedAuto=b.header.replace(nameLine,`name: "${name} (automatic non-VM source)"`).replace(push+"  workflow_dispatch:\n",pushWithSelf);
        require(a.header===expectedAuto,"automatic-header-drift:"+path);
        return {selected,removed};
    }
    for(const [path,row] of old){
        if(!changed.has(path))require(next.get(path).content===row.content,"unleased-workflow-change:"+path);
        if(plan.selected.includes(path)){
            const companion=path.replace(/\.yml$/,"-source-push.yml");
            const {selected,removed}=verifySplit(path,next.get(path),next.get(companion));
            ++manuals;autoJobs+=selected.length;vmJobs+=removed.length;
        }
    }
    function verifyQemu(row,archived){
        const q=old.get(plan.archivedQemu),b=op.get(plan.archivedQemu),a=parse(row);
        require(archived===q.content,"QEMU-archive-bytes-drift");
        require(b.push&&!b.manual&&a.push&&!a.manual&&equal(b.paths,a.paths)&&b.main===a.main,"QEMU-source-route-drift");
        const stop="      - name: Provision ephemeral runner tools and prove usable rootless TCG firmware\n";
        const upload="      - name: Retain exact build identity, stage hashes and actual JSON/KTAP\n";
        const original=q.content,expected=original.slice(0,original.indexOf(stop))
            .replace(original.split("\n")[0],"name: Original ticket stage and diagnostic regressions (no VM)")
            .replace("  original-ticket-pinned-smp-qemu-tcg:\n","  original-ticket-rootless-stage:\n")+
            original.slice(original.indexOf(upload))
                .replace(upload,"      - name: Retain rootless stage and diagnostic evidence\n")
                .replace("name: round087-agent11-actual-qemu-tcg-ticket","name: original-ticket-rootless-stage-no-vm");
        require(row.content===expected&&!vm.test(row.content),"QEMU-rootless-prefix-drift");
        require(row.content.includes("github.event.before")&&row.content.includes("repository-policy-test.py --enforce")&&row.content.includes(" diagnostic-regressions")&&row.content.includes("verify-only stage verify-stage"),"QEMU-rootless-gate-missing");
    }
    verifyQemu(next.get(plan.archivedQemu),archiveText);
    const mandatory=".github/workflows/project-goals.yml";
    require(next.get(mandatory).content===old.get(mandatory).content&&np.get(mandatory).push&&np.get(mandatory).paths===null&&np.get(mandatory).manual&&next.get(mandatory).content.includes("repository-policy-test.py --enforce"),"mandatory-policy-drift");
    for(const [path,b] of op){
        if(!b.push)continue;
        const mapped=plan.selected.includes(path)?path.replace(/\.yml$/,"-source-push.yml"):path;
        const a=np.get(mapped);
        if(b.paths===null){require(a.push&&a.paths===null,"unfiltered-drift:"+path);continue;}
        for(const pattern of b.paths){
            const witness=pattern.replaceAll("**","nested/file.c").replaceAll("*","witness");
            require(matches(b,[witness])&&matches(a,[witness]),"source-witness-lost:"+path+":"+pattern);
            ++witnesses;
        }
        if(b.manual)require(np.get(path).manual,"manual-lost:"+path);
    }
    const census=(map,paths)=>{
        const started=[...map].filter(([,t])=>matches(t,paths));
        return {workflows:started.length,jobs:started.reduce((n,[,t])=>n+t.jobs.length,0),vm_jobs:started.flatMap(([path,t])=>t.jobs.filter(j=>vm.test(j.body)).map(j=>path+":"+j.id)).sort()};
    };
    const migrationPaths=[...changed,...plan.selected.map(p=>p.replace(/\.yml$/,"-source-push.yml")),plan.archivePath,plan.physicalSource,plan.physicalTest,plan.testPath,plan.manifestPath,"docs/testing_standards.md","docs/handoff/zswapz/round088/agent9-evidence.md","docs/handoff/zswapz/round088/agent9-results.json"];
    const scenarios=[
        ["ordinary-DM",["src/kernel/dm-target.c"]],
        ["codec",["src/kernel/codec.c","src/kernel/codec.h"]],
        ["ticket",["src/kernel/zswap-original-ticket.c"]],
        ["authority",["src/kernel/authority.c"]],
        ["original-composer",["tests/tools/stage-pinned-linux-zswap-composed.py"]],
        ["standards-only",["docs/testing_standards.md"]],
        ["physical-helper",[plan.physicalSource,plan.physicalTest]],
        ["evidence-only",["docs/handoff/zswapz/round088/agent9-evidence.md","docs/handoff/zswapz/round088/agent9-results.json"]],
        ["migration",migrationPaths]
    ].map(([name,paths])=>({name,before:census(op,paths),after:census(np,paths)}));
    require(scenarios.find(s=>s.name==="migration").after.vm_jobs.length===0,"migration-would-launch-VM");
    for(const s of scenarios)require(s.after.vm_jobs.every(j=>s.before.vm_jobs.includes(j)),"new-VM-route:"+s.name);
    require(match("src/kernel/**","src/kernel/a/b.c")&&!match("src/kernel/*","src/kernel/a/b.c"),"glob-boundary");
    const negatives=[];
    function reject(label,fn){try{fn();}catch(e){require(String(e.message).startsWith("ROUND088_VM_ROUTING_FIRST_ERROR"),"wrong-negative:"+label);negatives.push(label);return;}throw Error("ROUND088_VM_ROUTING_FIRST_ERROR survived:"+label);}
    const path=plan.selected[0],m=next.get(path),a=next.get(path.replace(/\.yml$/,"-source-push.yml")),b=old.get(path);
    reject("restore-automatic-VM",()=>verifySplit(path,b,a));
    reject("lose-manual",()=>verifySplit(path,{...m,content:m.content.replace("  workflow_dispatch:\n","")},a));
    reject("mutate-archived-job",()=>verifySplit(path,{...m,content:m.content.replace("actions/checkout@v4","actions/checkout@v3")},a));
    reject("mutate-automatic-job",()=>verifySplit(path,m,{...a,content:a.content.replace("actions/checkout@v4","actions/checkout@v3")}));
    const realPath=parse(a).paths.find(p=>p.startsWith("tests/"));
    const line=a.content.split("\n").find(l=>l.includes(realPath)&&l.startsWith("      - "));
    reject("lose-source-path",()=>verifySplit(path,m,{...a,content:a.content.replace(line+"\n","")}));
    reject("lose-QEMU-stage-policy",()=>verifyQemu({...next.get(plan.archivedQemu),content:next.get(plan.archivedQemu).content.replace(" --enforce","")},archiveText));
    reject("change-QEMU-archive",()=>verifyQemu(next.get(plan.archivedQemu),archiveText+"\n"));
    const inventory=[...old].map(([path,row])=>({path,blob:row.sha,vm_jobs:op.get(path).jobs.filter(j=>vm.test(j.body)).map(j=>j.id),non_vm_jobs:op.get(path).jobs.filter(j=>!vm.test(j.body)).map(j=>j.id),decision:plan.selected.includes(path)?"manual-full-plus-push-non-VM":path===plan.archivedQemu?"archive-QEMU-preserve-rootless-stage":"retain"})).sort((a,b)=>a.path.localeCompare(b.path));
    return {status:"PASS_ROOTLESS_VM_ROUTING",before_workflows:old.size,after_workflows:next.size,manual_full_preserved:manuals,automatic_non_vm_jobs_preserved:autoJobs,automatic_vm_jobs_retired:vmJobs+1,source_path_witnesses:witnesses,negative_mutants:negatives,checks,scenarios,inventory};
}

try {
    const sha=process.argv[2];
    if(process.argv.length!==3||!/^[0-9a-f]{40}$/.test(sha??""))throw Error("provide exact migration SHA");
    const root=execFileSync("git",["rev-parse","--show-toplevel"],{encoding:"utf8"}).trim();
    const git=args=>execFileSync("git",["-C",root,...args],{encoding:"utf8",maxBuffer:16*1024*1024});
    const show=(revision,path)=>git(["show",revision+":"+path]);
    const manifest=JSON.parse(show(sha,"docs/handoff/zswapz/round088/agent9-workflow-manifest.json"));
    const read=revision=>git(["ls-tree","-r","--name-only",revision,"--",".github/workflows"]).trim().split("\n").map(path=>{
        const content=show(revision,path);
        const blob=createHash("sha1").update("blob "+Buffer.byteLength(content)+"\0").update(content).digest("hex");
        return {path,content,sha:blob};
    });
    const outcome=regression(read(manifest.plan.baseline),read(sha),show(sha,manifest.plan.archivePath),manifest.plan);
    if(JSON.stringify(outcome)!==JSON.stringify(manifest.regression))throw Error("immutable trigger replay differs");
    console.log(JSON.stringify({status:outcome.status,retired:outcome.automatic_vm_jobs_retired,
        preserved:outcome.automatic_non_vm_jobs_preserved,witnesses:outcome.source_path_witnesses,
        negatives:outcome.negative_mutants.length}));
} catch(error) {
    console.error(String(error.message).slice(0,300));
    process.exitCode=1;
}
