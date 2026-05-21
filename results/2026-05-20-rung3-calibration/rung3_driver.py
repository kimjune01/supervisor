#!/usr/bin/env python3
"""Rung 3 driver — clean-room patch PRODUCTION only. Grading is the official eval.py.

Per instance (model runs LOCALLY on the plan; SUT is an offline container on the box):
  pull image -> run -> git apply test_patch -> COMMIT it (so model_patch is impl-only,
  since eval.py re-applies test_patch itself) -> warm online (caches deps, captures
  fail-on-base) -> cut net -> clean Sonnet 4.5 /investigate loop via box-sh, gate-grounded
  via a `gate` helper running the official test_cmd -> capture model_patch = `git diff HEAD`
  -> teardown container.

Emits patches_<box>.jsonl ({instance_id, patch}) + a per-run log. NO bespoke grading.

Usage: rung3_driver.py <box_env_file> <round_tasks.json> <instance_id> [<instance_id> ...]
"""
import json, subprocess, sys, time, pathlib, os, shutil

HERE = pathlib.Path("/tmp/swebench-abduction")
HYGRAPH_SRC = pathlib.Path.home()/"Documents/sweep/repo-hypotheses"
SKILL_PATH = "/Users/junekim/Documents/june.kim/skills/investigate/skill.md"
SKILL_TEXT = open(SKILL_PATH).read()

def plan_env():
    e = os.environ.copy(); e.pop("ANTHROPIC_API_KEY", None); return e

BOXENV = dict(l.strip().split("=",1) for l in open(sys.argv[1]) if "=" in l)
TASKS = {d["instance_id"]: d for d in json.load(open(sys.argv[2]))}
PEM = f"/tmp/{BOXENV['KEY']}.pem"; HOST = f"ec2-user@{BOXENV['PUBIP']}"
STEM = pathlib.Path(sys.argv[1]).stem
LEDGER = HERE/f"rung3_results_{STEM}.jsonl"
PATCHES = HERE/f"rung3_patches_{STEM}.jsonl"

def ssh(remote, timeout=600, inp=None):
    return subprocess.run(["ssh","-o","StrictHostKeyChecking=no","-o","ConnectTimeout=10","-i",PEM,HOST,remote],
                          capture_output=True,text=True,timeout=timeout,input=inp)

def log(obj):
    with open(LEDGER,"a") as f: f.write(json.dumps(obj)+"\n")
    sys.stderr.write(f"[{obj.get('instance')}] {obj.get('stage')}: {obj.get('msg','')}\n"); sys.stderr.flush()

def evacuate_hygraphs(iid, since):
    dest = HERE/"hygraphs"/iid.replace("/","_"); dest.mkdir(parents=True, exist_ok=True)
    moved=0
    for f in HYGRAPH_SRC.glob("*.md"):
        try:
            if f.stat().st_mtime >= since: shutil.move(str(f), str(dest/f.name)); moved+=1
        except Exception: pass
    return moved

def setup(inst):
    """pull, run, apply test_patch, COMMIT it. return (cid, root, applied)."""
    iid = inst["instance_id"]; img = inst["image_name"].replace("docker.io/","")
    ssh(f"sudo docker pull {img} 2>&1 | tail -1", timeout=1200)
    cid = ssh(f"sudo docker run -d {img} sleep infinity").stdout.strip()
    if not cid or len(cid) < 12:
        log({"instance":iid,"stage":"setup","msg":f"run failed: {cid[:80]}"}); return None
    root = ssh(f"sudo docker exec {cid} pwd").stdout.strip() or "/"
    ssh(f"cat > /tmp/tp.patch && sudo docker cp /tmp/tp.patch {cid}:{root}/tp.patch", inp=inst["test_patch"])
    # apply test_patch, then commit it so `git diff HEAD` later = impl-only
    ap = ssh(f"sudo docker exec {cid} bash -lc 'cd {root} && git apply tp.patch && "
             f"git -c user.email=r3@x -c user.name=r3 add -A && "
             f"git -c user.email=r3@x -c user.name=r3 commit -q -m testpatch && "
             f"echo APPLIED $(git rev-parse HEAD)'")
    if "APPLIED" not in ap.stdout:
        log({"instance":iid,"stage":"setup","msg":f"git apply/commit failed: {(ap.stdout+ap.stderr)[:200]}"})
        return (cid, root, False, None)
    tsha = ap.stdout.split("APPLIED")[1].strip().split()[0]
    return (cid, root, True, tsha)

def warm_and_failbase(inst, cid, root):
    """Run the official test_cmd ONCE online: caches deps AND captures fail-on-base."""
    tc = (inst.get("install_config") or {}).get("test_cmd","")
    if not tc: return ""
    r = ssh(f"sudo docker exec {cid} bash -lc 'cd {root} && {tc} 2>&1 | tail -60'", timeout=1800)
    (HERE/f"r3_warm_failbase_{inst['instance_id'].replace('/','_')}.txt").write_text(f"$ {tc}\n\n{r.stdout}{r.stderr}")
    return r.stdout

def helpers(inst, cid, root):
    """LOCAL box-sh (run cmd in container) + LOCAL gate (run official test_cmd, print tail)."""
    iid = inst["instance_id"]; tag = iid.replace("/","_").replace("__","_")
    box = f"/tmp/box-sh-{tag}"
    s = (f"#!/bin/bash\n"
         f"printf '%s' \"$*\" | ssh -o StrictHostKeyChecking=no -i {PEM} {HOST} "
         f"\"cat >/tmp/_bc_{tag} && sudo docker cp /tmp/_bc_{tag} {cid}:/tmp/_bc >/dev/null && "
         f"sudo docker exec {cid} bash -lc 'cd {root} && bash /tmp/_bc'\"\n")
    pathlib.Path(box).write_text(s); subprocess.run(["chmod","+x",box])
    tc = (inst.get("install_config") or {}).get("test_cmd","").replace("'","'\\''")
    gate = f"/tmp/gate-{tag}"
    g = (f"#!/bin/bash\n"
         f"ssh -o StrictHostKeyChecking=no -i {PEM} {HOST} "
         f"\"sudo docker exec {cid} bash -lc 'cd {root} && {tc} 2>&1 | tail -80'\"\n")
    pathlib.Path(gate).write_text(g); subprocess.run(["chmod","+x",gate])
    return box, gate

def run_agent(inst, box, gate, timeout=3000):
    iid = inst["instance_id"]
    added = "\n".join(l[1:] for l in inst["test_patch"].splitlines() if l.startswith("+") and not l.startswith("+++"))
    testfiles = [l[6:] for l in inst['test_patch'].splitlines() if l.startswith('+++ b/')]
    iso_hg = HERE/f"r3_hygraph_iso/{iid.replace('/','_')}_{int(time.time()*1000)}"
    iso_hg.mkdir(parents=True, exist_ok=True)
    adapter = f"""You will follow the /investigate skill below — IN WHOLE, verbatim — as your method. Honor its hypothesis-graph discipline: do NOT give up early; the frontier stays open until the failing tests pass or you have genuinely exhausted the graph.

Exactly FOUR environment adaptations (everything else: follow the skill literally):
1. The system-under-test is an OFFLINE container reached ONLY via this local helper: `{box} '<cmd>'` (runs at the repo root in the container). Every file read / edit / grep / build the skill tells you to do, route through it (sed/python3/cat/git inside it). The code is NOT on this machine. Do NOT clone. Do NOT spawn subagents.
2. BENCH MODE: skip Phase 8 (ship) and all gh / context-pack steps — there is no PR and no gh. Your sole goal is that the FAIL_TO_PASS tests pass. Do not stop to ask.
3. Phase-7 bug-hunt adversary: codex/gemini are unavailable — act as your own adversary (the documented Sonnet fallback).
4. HYGRAPH ISOLATION: write your hypothesis-graph document ONLY to {iso_hg}/HYPOTHESIS_GRAPH.md. The path ~/Documents/sweep/ is STRICTLY OFF-LIMITS — do not read or write it (prior diagnoses there would contaminate this clean-room run).
CLEAN ROOM: no web, no fetching the issue/PR/commit, no reading prior hypothesis graphs. Diagnose from the code alone.

GATE (this is how you know you are done): run `{gate}` — it runs the project's official test command in the container and prints the tail. You are RESOLVED only when the FAIL_TO_PASS tests show as passing in that output. Never declare RESOLVED from your own prose — only from gate output. When the gate shows the failing tests pass, print RESOLVED + a one-line fix summary. If you exhaust the graph without passing, print NOT-RESOLVED.

The failing tests are already applied (and committed), in: {testfiles}
FAIL_TO_PASS (must pass): {str(inst['FAIL_TO_PASS'])[:600]}

ISSUE:
{inst['problem_statement'][:4000]}

ADDED FAILING TESTS:
{added[:2500]}

===================== THE /investigate SKILL (follow in whole) =====================
{SKILL_TEXT}
"""
    pf = HERE/f"r3_prompt_{iid.replace('/','_')}.txt"; pf.write_text(adapter)
    cwd = HERE/f"r3_cwd_{iid.replace('/','_')}"; cwd.mkdir(exist_ok=True)
    t0=time.time()
    p = subprocess.run(["claude","--print","--model","claude-sonnet-4-5","--dangerously-skip-permissions",
                        "--disallowedTools","WebSearch","WebFetch","Task"],
                       stdin=open(pf), capture_output=True,text=True,timeout=timeout,cwd=str(cwd),env=plan_env())
    dt=time.time()-t0
    (HERE/f"r3_out_{iid.replace('/','_')}.txt").write_text(p.stdout+"\n---STDERR---\n"+p.stderr)
    return p.stdout, dt

def capture_patch(inst, cid, root, tsha):
    """model_patch = impl diff since the test-patch commit (covers staged/unstaged AND any
    commits the agent made after T; test_patch itself is in T so it's excluded)."""
    iid = inst["instance_id"]
    r = ssh(f"sudo docker exec {cid} bash -lc 'cd {root} && git add -A >/dev/null 2>&1; "
            f"git -c core.fileMode=false diff {tsha}'", timeout=120)
    # diagnostic snapshot so an empty patch is debuggable without the container
    diag = ssh(f"sudo docker exec {cid} bash -lc 'cd {root} && "
               f"echo ===STATUS===; git status --short | head -40; "
               f"echo ===LOG===; git log --oneline -4; "
               f"echo ===STAT===; git diff {tsha} --stat | tail -20'", timeout=120)
    (HERE/f"r3_capture_diag_{iid.replace('/','_')}.txt").write_text(diag.stdout+diag.stderr)
    if not r.stdout.strip():
        log({"instance":iid,"stage":"capture","msg":"EMPTY patch — see capture_diag"})
    return r.stdout

def teardown(inst, cid):
    img = inst["image_name"].replace("docker.io/","")
    ssh(f"sudo docker rm -f {cid} 2>/dev/null; sudo docker rmi {img} 2>/dev/null; echo cleaned")

def process(iid):
    inst = TASKS[iid]
    log({"instance":iid,"stage":"start"})
    s = setup(inst)
    if not s: return
    cid, root, applied, tsha = s
    if not applied: teardown(inst, cid); return
    warm_and_failbase(inst, cid, root)
    box, gate = helpers(inst, cid, root)
    ssh(f"sudo docker network disconnect bridge {cid} 2>/dev/null; echo done")  # offline
    t_agent = time.time()
    out, dt = run_agent(inst, box, gate)
    moved = evacuate_hygraphs(iid, t_agent)
    if moved: log({"instance":iid,"stage":"evacuated","msg":f"moved {moved} stray hygraph(s)"})
    claim = ("RESOLVED" in out) and ("NOT-RESOLVED" not in out)
    patch = capture_patch(inst, cid, root, tsha)
    pf = HERE/f"r3_patch_{iid.replace('/','_')}.diff"; pf.write_text(patch)
    with open(PATCHES,"a") as f: f.write(json.dumps({"instance_id":iid,"patch":patch})+"\n")
    log({"instance":iid,"stage":"done","agent_claim":claim,"wall_s":round(dt),
         "patch_bytes":len(patch),"agent_log":str(HERE/f"r3_out_{iid.replace('/','_')}.txt"),
         "patch_file":str(pf)})
    teardown(inst, cid)

if __name__ == "__main__":
    for iid in sys.argv[3:]:
        try: process(iid)
        except Exception as e:
            log({"instance":iid,"stage":"ERROR","msg":f"{type(e).__name__}: {str(e)[:200]}"})
    sys.stderr.write("rung3 driver done\n")
