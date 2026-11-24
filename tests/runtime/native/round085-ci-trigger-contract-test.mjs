#!/usr/bin/env node
// SPDX-License-Identifier: GPL-2.0-only
// Rootless, offline replay of immutable before/after Git trees.
// Usage: node tests/runtime/native/round085-ci-trigger-contract-test.mjs <migration-sha>
import {execFileSync} from "node:child_process";
import {createHash} from "node:crypto";

function runRegression(beforeRows, afterRows, plan, policyBefore, policyAfter) {
    // Deliberately limited to the actual frozen positive-filter YAML grammar.
    // Reject unsupported events, negation and globstars rather than guess.
    let checks = 0;
    function require(condition, reason) {
        if (!condition) throw new Error("ROUND085_TRIGGER_FIRST_ERROR " + reason);
        ++checks;
    }
    const standard = "docs/testing_standards.md";
    const policyPath = ".github/workflows/project-goals.yml";
    const sort = values => [...values].sort();
    const same = (a,b) => JSON.stringify(a) === JSON.stringify(b);
    function patternMatches(pattern, path) {
        require(/^[A-Za-z0-9_./*-]+$/.test(pattern) &&
            !pattern.startsWith("/") && !pattern.includes("//") &&
            !pattern.split("/").some(p => p === "." || p === ".."),
            "unsupported-pattern:" + pattern);
        const parts = pattern.split("/");
        require(parts.every((p,i) => !p.includes("**") ||
            (p === "**" && i === parts.length-1)),
            "unsupported-globstar:" + pattern);
        return new RegExp("^" + parts.map(p => p === "**" ? ".*" :
            p.replaceAll(".", "\\.").replaceAll("*", "[^/]*")).join("/") + "$").test(path);
    }
    function parse(row) {
        require(!row.content.includes("\r"), "unsupported-newline:" + row.path);
        const all = row.content.split("\n");
        const starts = all.flatMap((line,i) => line === "on:" ? [i] : []);
        require(starts.length === 1, "nonunique-on:" + row.path);
        let end = starts[0]+1;
        while (end < all.length && !/^[^\s#]/.test(all[end])) ++end;
        const lines = all.slice(starts[0]+1,end).filter(l => l.trim() &&
            !l.trimStart().startsWith("#"));
        let i=0;
        require(lines[i++] === "  push:", "unsupported-push:" + row.path);
        const main = lines[i] === "    branches: [main]";
        if (main) ++i;
        let paths = null, standardsLine = null;
        if (lines[i] === "    paths:") {
            ++i;
            paths = [];
            while (i < lines.length && /^      - /.test(lines[i])) {
                const line = lines[i++];
                // Plain literals occur in the unchanged R073 FUA workflow.
                // A plain leading wildcard is not a YAML string.
                const quoted = /^      - (['"])([A-Za-z0-9_./*-]+)\1$/.exec(line);
                const plain = /^      - ([A-Za-z0-9_./-]+)$/.exec(line);
                require(Boolean(quoted || plain), "unsupported-yaml-path:" + row.path);
                const path = quoted ? quoted[2] : plain[1];
                patternMatches(path,"");
                require(!paths.includes(path), "duplicate-path:" + row.path);
                if (path === standard) standardsLine = line;
                paths.push(path);
            }
            require(paths.length > 0, "empty-paths:" + row.path);
        }
        const manual = lines[i] === "  workflow_dispatch:";
        if (manual) ++i;
        require(i === lines.length, "unsupported-event:" + row.path);
        return {main, paths, manual, standardsLine};
    }
    const matches = (trigger, paths) => trigger.paths === null ||
        paths.some(path => trigger.paths.some(pattern => patternMatches(pattern,path)));
    const edited = new Set(plan.edited);
    require(edited.size === plan.edited.length, "duplicate-edit");
    const before = new Map(beforeRows.map(r => [r.path,r]));
    const after = new Map(afterRows.map(r => [r.path,r]));
    require(before.size === beforeRows.length && after.size === afterRows.length &&
        same(sort(before.keys()),sort(after.keys())), "workflow-inventory-drift");
    const oldTriggers = new Map(), newTriggers = new Map();
    function checkPair(oldRow,newRow,edit) {
        const old = parse(oldRow), next = parse(newRow);
        let expected = oldRow.content;
        if (edit) {
            require(old.standardsLine !== null, "missing-standards-line:" + oldRow.path);
            const line = old.standardsLine + "\n";
            require(expected.split(line).length === 2, "nonunique-standards-line:" + oldRow.path);
            expected = expected.replace(line,"");
            require(old.main && old.manual && old.paths.includes(oldRow.path),
                "missing-existing-main-self-manual:" + oldRow.path);
        }
        require(newRow.content === expected, "nonminimal-edit:" + oldRow.path);
        require(same(next.paths,edit ? old.paths.filter(p => p !== standard) : old.paths) &&
            next.main === old.main && next.manual === old.manual,
            "trigger-order-or-dispatch-drift:" + oldRow.path);
        return [old,next];
    }
    for (const [path,row] of before) {
        const [old,next] = checkPair(row,after.get(path),edited.has(path));
        oldTriggers.set(path,old);
        newTriggers.set(path,next);
    }
    for (const path of edited) {
        require(before.has(path) && !path.includes("round084") && path !== policyPath &&
            plan.history.every(event => event.actualRuns.some(run => run.path === path)),
            "unleased-edit:" + path);
    }
    function checkPolicy(row,script) {
        require(row.content === before.get(policyPath).content && script === policyBefore,
            "mandatory-policy-bytes-changed");
        const t = parse(row);
        require(t.main && t.manual && t.paths === null &&
            row.content.includes("python3 -B tests/runtime/native/repository-policy-test.py --enforce") &&
            row.content.includes("cancel-in-progress: false") &&
            row.content.includes("SWAPZ_PUSH_BEFORE_SHA: ${{ github.event.before }}") &&
            row.content.includes("github.run_id") && script.includes(standard),
            "mandatory-policy-drift");
    }
    checkPolicy(after.get(policyPath),policyAfter);
    const evaluate = (map,paths) => sort([...map].filter(([,t]) => matches(t,paths)).map(([p]) => p));
    const scenarios = [];
    function scenario(name,paths,expectedBefore,expectedAfter) {
        const prior = evaluate(oldTriggers,paths), next = evaluate(newTriggers,paths);
        if (expectedBefore) require(same(prior,sort(expectedBefore)),"before-census:" + name);
        if (expectedAfter) require(same(next,sort(expectedAfter)),"after-census:" + name);
        require(next.includes(policyPath) && next.every(p=>prior.includes(p)),
            "policy-missed-or-new-trigger:" + name);
        scenarios.push({name,changedPaths:paths,before:prior,after:next});
        return {prior,next};
    }
    for (const event of plan.history) {
        require(event.actualRuns.length === 41 &&
            new Set(event.actualRuns.map(r=>r.path)).size === 41 &&
            event.actualRuns.every(r=>r.event === "push" && r.head_sha === event.sha),
            "historical-run-identity:" + event.sha);
        const actual = event.actualRuns.map(r=>r.path);
        const expected = actual.filter(path => !edited.has(path) ||
            matches(newTriggers.get(path),event.changedPaths.filter(p=>p!==standard)));
        scenario("actual-R084-" + event.sha,event.changedPaths,actual,expected);
    }
    const broad = sort([...oldTriggers].filter(([,t])=>t.paths===null).map(([p])=>p));
    require(broad.length===4,"broad-workflow-count");
    scenario("evidence-only",["docs/handoff/zswapz/round085/agent9-evidence.md",
        "docs/handoff/zswapz/round085/agent9-results.json"],broad,broad);
    const standardsBefore = [...oldTriggers].filter(([,t])=>t.paths===null ||
        t.paths.includes(standard)).map(([p])=>p);
    scenario("standards-only",[standard],standardsBefore,standardsBefore.filter(p=>!edited.has(p)));
    for (const [name,paths] of [
        ["ordinary-product-source",["src/kernel/dm-target.c"]],
        ["old-exact-helper",["tests/tools/round035-dm-lower-verify.py"]],
        ["old-wildcard-fixture",["tests/runtime/native/fixtures/round037-dm-async-lower-host.c"]],
        ["policy-self",[policyPath]]]) {
        const {prior,next}=scenario(name,paths);
        require(same(prior,next),"lost-nonstandards-trigger:" + name);
    }
    scenario("policy-script-plus-standards",
        ["tests/runtime/native/repository-policy-test.py",standard]);
    scenario("mixed-disjoint-multi-commit-net-change",sort(new Set([
        ...plan.history.slice(0,2).flatMap(event=>event.changedPaths),
        "docs/handoff/zswapz/round085/agent7-evidence.md"])));
    let witnesses=0,self=0;
    for (const [path,old] of oldTriggers) {
        const next = newTriggers.get(path);
        require(old.manual === next.manual,"manual-drift:" + path);
        if (old.paths===null) {
            require(matches(next,["unrelated/any-path"]),"lost-broad:" + path);
            continue;
        }
        for (const pattern of old.paths) {
            if (edited.has(path) && pattern===standard) continue;
            const witness = pattern.replaceAll("**","nested/file.c").replaceAll("*","witness");
            require(matches(old,[witness]) && matches(next,[witness]),
                "lost-pattern-witness:" + path + ":" + pattern);
            ++witnesses;
        }
        if (edited.has(path)) {
            require(matches(next,[path]) && next.manual,"lost-self-or-manual:" + path);
            ++self;
        }
    }
    scenario("one-time-migration-push",sort([...edited,standard,
        "tests/runtime/native/round085-ci-trigger-contract-test.mjs",
        "docs/handoff/zswapz/round085/agent9-workflow-manifest.json",
        "docs/handoff/zswapz/round085/agent9-evidence.md",
        "docs/handoff/zswapz/round085/agent9-results.json"]));
    require(patternMatches("src/kernel/**","src/kernel/a/b.c"),"globstar-directory");
    require(!patternMatches("src/kernel/*","src/kernel/a/b.c"),"star-crossed-directory");
    require(patternMatches("src/kernel/*","src/kernel/b.c"),"star-component");
    const negatives=[];
    function reject(name,reason,fn) {
        try { fn(); }
        catch(e) {
            require(String(e.message).includes(reason),"wrong-mutant-rejection:" + name);
            negatives.push(name);
            return;
        }
        throw new Error("ROUND085_TRIGGER_FIRST_ERROR mutant-survived:" + name);
    }
    const example=plan.edited[0], old=before.get(example), next=after.get(example);
    const editPath=(row,pattern)=>{
        const line=row.content.split("\n").find(l=>l==="      - '"+pattern+"'" ||
            l==='      - "'+pattern+'"' || l==="      - "+pattern);
        require(Boolean(line),"negative-input-absent:" + pattern);
        return {...row,content:row.content.replace(line+"\n","")};
    };
    const patterns=newTriggers.get(example).paths;
    for (const [name,pattern] of [["source",patterns.find(p=>p.startsWith("src/"))],
        ["helper",patterns.find(p=>p.startsWith("tests/tools/"))],["self",example]]) {
        reject("remove-"+name+"-trigger","nonminimal-edit",
            ()=>checkPair(old,editPath(next,pattern),true));
    }
    reject("remove-manual-dispatch","nonminimal-edit",()=>checkPair(old,{...next,
        content:next.content.replace("  workflow_dispatch:\n","")},true));
    reject("alter-job-logic","nonminimal-edit",()=>checkPair(old,{...next,
        content:next.content.replace("actions/checkout@v4","actions/checkout@v3")},true));
    reject("filter-mandatory-policy","mandatory-policy-bytes-changed",()=>checkPolicy({
        ...after.get(policyPath),content:after.get(policyPath).content.replace(
            "    branches: [main]\n","    branches: [main]\n    paths:\n      - 'src/kernel/**'\n")},policyAfter));
    reject("weaken-policy-script","mandatory-policy-bytes-changed",()=>checkPolicy(
        after.get(policyPath),policyAfter+"\n# altered\n"));
    reject("unsupported-negation","unsupported-pattern",()=>patternMatches("!src/kernel/**","src/kernel/a.c"));
    reject("unsupported-globstar-shape","unsupported-globstar",()=>patternMatches("src/**/a.c","src/kernel/a.c"));
    reject("unsupported-event","unsupported-push",()=>parse({path:"synthetic.yml",content:"on:\n  pull_request:\n"}));
    return {status:"PASS_ROOTLESS_TRIGGER_CONTRACT",workflow_count:before.size,edited_count:edited.size,
        scenarios,scenario_count:scenarios.length,preserved_trigger_witnesses:witnesses,
        preserved_edited_self_manual:self,negative_mutants:negatives,checks,
        unfiltered_workflows:broad,
        manual_dispatch_before:[...oldTriggers.values()].filter(t=>t.manual).length,
        manual_dispatch_after:[...newTriggers.values()].filter(t=>t.manual).length,
        per_workflow:sort(before.keys()).map(path=>({path,before_blob:before.get(path).sha,
            before_paths:oldTriggers.get(path).paths,after_paths:newTriggers.get(path).paths,
            main_only:newTriggers.get(path).main,manual_dispatch:newTriggers.get(path).manual,
            edited:edited.has(path)}))};
}

try {
    const revision=process.argv[2];
    if(process.argv.length!==3 || !/^[0-9a-f]{40}$/.test(revision??""))
        throw new Error("provide the exact migration commit SHA");
    const root=execFileSync("git",["rev-parse","--show-toplevel"],{encoding:"utf8"}).trim();
    const git=args=>execFileSync("git",["-C",root,...args],{encoding:"utf8",maxBuffer:16*1024*1024});
    const show=(sha,path)=>git(["show",sha+":"+path]);
    const manifest=JSON.parse(show(revision,"docs/handoff/zswapz/round085/agent9-workflow-manifest.json"));
    const rows=sha=>git(["ls-tree","-r","--name-only",sha,"--",".github/workflows"]).trim().split("\n").map(path=>{
        const content=show(sha,path);
        const blob=createHash("sha1").update("blob "+Buffer.byteLength(content)+"\0").update(content).digest("hex");
        return {path,sha:blob,content};
    });
    const before=rows(manifest.baseline),after=rows(revision);
    const hashes=new Map(manifest.regression.per_workflow.map(row=>[row.path,row.before_blob]));
    if(before.length!==hashes.size || before.some(row=>hashes.get(row.path)!==row.sha))
        throw new Error("immutable baseline workflow blob mismatch");
    for(const event of manifest.history) {
        const paths=git(["diff","--name-only","--no-renames",event.sha+"^1",event.sha,"--"]).trim().split("\n").sort();
        if(JSON.stringify(paths)!==JSON.stringify(event.changedPaths))
            throw new Error("historical changed-path mismatch:"+event.sha);
    }
    const policy="tests/runtime/native/repository-policy-test.py";
    const result=runRegression(before,after,manifest,show(manifest.baseline,policy),show(revision,policy));
    if(JSON.stringify(result)!==JSON.stringify(manifest.regression))
        throw new Error("replayed trigger matrix differs from pre-publication evidence");
    console.log(JSON.stringify({status:result.status,workflows:result.workflow_count,edited:result.edited_count,
        scenarios:result.scenario_count,witnesses:result.preserved_trigger_witnesses,
        negative_mutants:result.negative_mutants.length,checks:result.checks}));
} catch(error) {
    console.error(String(error.message).slice(0,300));
    process.exitCode=1;
}
