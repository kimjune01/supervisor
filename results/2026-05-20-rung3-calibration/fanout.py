#!/usr/bin/env python3
"""Generalized round fan-out: one ephemeral EC2 box per instance.
Phases (each resumable; state in /tmp/swebench-abduction/fanout_<tag>.json):
  up    <tasks.json> <tag>   provision N boxes + bootstrap + golden-screen -> records survivors
  solve <tag>                run rung3_driver.py per survivor box, throttled to 3 concurrent
  grade <tag>                eval.py per survivor box -> verdicts
  down  <tag>                terminate all boxes + key + SG

Survivors = instances whose gold patch grades (passed_match & no P2P regressions).
"""
import json, subprocess, sys, time, pathlib, concurrent.futures as cf

HERE = pathlib.Path("/tmp/swebench-abduction")
REGION="us-west-2"; AMI="ami-00563078bca04e287"; ITYPE="m7i.xlarge"; VPC="vpc-02c2ac734b774000f"
DRIVER=str(HERE/"rung3_driver.py")

def aws(*a, timeout=400):
    return subprocess.run(["aws",*a,"--region",REGION],capture_output=True,text=True,timeout=timeout)
def myip(): return subprocess.run(["curl","-s","https://checkip.amazonaws.com"],capture_output=True,text=True).stdout.strip()
def statef(tag): return HERE/f"fanout_{tag}.json"
def pem(tag): return f"/tmp/rung3-{tag}-key.pem"
def ssh(tag, ip, remote, timeout=600, inp=None):
    return subprocess.run(["ssh","-o","StrictHostKeyChecking=no","-o","ConnectTimeout=10","-i",pem(tag),f"ec2-user@{ip}",remote],
                          capture_output=True,text=True,timeout=timeout,input=inp)
def scp_to(tag, ip, local, remote):
    subprocess.run(["scp","-o","StrictHostKeyChecking=no","-i",pem(tag),local,f"ec2-user@{ip}:{remote}"],capture_output=True)
def scp_from(tag, ip, remote, local):
    subprocess.run(["scp","-o","StrictHostKeyChecking=no","-i",pem(tag),f"ec2-user@{ip}:{remote}",local],capture_output=True)

BOOT = """set -e
sudo shutdown -h +180 || true   # self-terminate watchdog: hard-kill after 3h no matter what
sudo dnf install -y -q docker git python3.11 >/dev/null 2>&1
sudo systemctl enable --now docker >/dev/null 2>&1
sudo usermod -aG docker ec2-user
cd ~ && git clone --depth 1 https://github.com/SWE-rebench/SWE-rebench-V2.git swerebench-v2 >/dev/null 2>&1
cd swerebench-v2 && python3.11 -m venv .venv && . .venv/bin/activate && pip install -q -U pip >/dev/null 2>&1
[ -f requirements.txt ] && pip install -q -r requirements.txt >/dev/null 2>&1
[ -f pyproject.toml ] && pip install -q -e . >/dev/null 2>&1
echo BOOTSTRAPPED
"""

def up(tasks_path, tag):
    KEY=f"rung3-{tag}-key"; SG_NAME=f"rung3-{tag}-sg"
    instances=[r["instance_id"] for r in json.load(open(tasks_path))]
    km=aws("ec2","create-key-pair","--key-name",KEY,"--query","KeyMaterial","--output","text")
    pathlib.Path(pem(tag)).write_text(km.stdout); pathlib.Path(pem(tag)).chmod(0o400)
    sg=aws("ec2","create-security-group","--group-name",SG_NAME,"--description",f"rung3 {tag}","--vpc-id",VPC,"--query","GroupId","--output","text").stdout.strip()
    aws("ec2","authorize-security-group-ingress","--group-id",sg,"--protocol","tcp","--port","22","--cidr",f"{myip()}/32")
    r=aws("ec2","run-instances","--image-id",AMI,"--instance-type",ITYPE,"--key-name",KEY,"--security-group-ids",sg,
          "--count",str(len(instances)),
          "--instance-initiated-shutdown-behavior","terminate",  # watchdog: shutdown -h => terminate (not stop)
          "--block-device-mappings",'[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":120,"VolumeType":"gp3","DeleteOnTermination":true}}]',
          "--tag-specifications",f'ResourceType=instance,Tags=[{{Key=Name,Value=rung3-{tag}}}]',
          "--query","Instances[].InstanceId","--output","text")
    iids=r.stdout.split(); aws("ec2","wait","instance-running","--instance-ids",*iids,timeout=400)
    desc=aws("ec2","describe-instances","--instance-ids",*iids,"--query","Reservations[].Instances[].[InstanceId,PublicIpAddress]","--output","json")
    pairs={p[0]:p[1] for p in json.loads(desc.stdout)}
    # pair instances to boxes by index (order of iids is arbitrary; just zip)
    boxes={instances[i]:{"iid":iids[i],"ip":pairs[iids[i]]} for i in range(len(instances))}
    st={"tag":tag,"sg":sg,"key":KEY,"tasks":tasks_path,"boxes":boxes,"survivors":[]}
    json.dump(st,open(statef(tag),"w"),indent=1)
    print("provisioned",len(boxes),"boxes")
    def boot(iid,info):
        ip=info["ip"]
        for _ in range(45):
            if ssh(tag,ip,"echo up",timeout=12).stdout.strip()=="up": break
            time.sleep(8)
        else: return iid,"SSH_TIMEOUT"
        r=ssh(tag,ip,BOOT,timeout=700)
        if "BOOTSTRAPPED" not in r.stdout: return iid,f"BOOT_FAIL {(r.stdout+r.stderr)[-150:]}"
        scp_to(tag,ip,tasks_path,"~/swerebench-v2/tasks.json")
        return iid,"ok"
    print("=== bootstrap ===")
    with cf.ThreadPoolExecutor(max_workers=len(boxes)) as ex:
        for iid,res in ex.map(lambda kv: boot(*kv), boxes.items()): print(f"  boot {iid}: {res}")
    def golden(iid,info):
        ip=info["ip"]; t=iid.replace('/','_')
        cmd=(f"cd ~/swerebench-v2 && . .venv/bin/activate && sg docker -c "
             f"\"python3.11 scripts/eval.py --json tasks.json --golden-eval --instance-ids {iid} "
             f"--max-workers 1 --report-json golden_{t}.json\" >golden_{t}.log 2>&1; echo done")
        ssh(tag,ip,cmd,timeout=2600)
        scp_from(tag,ip,f"~/swerebench-v2/golden_{t}.json",str(HERE/f"{tag}_golden_{t}.json"))
        try:
            d=json.load(open(HERE/f"{tag}_golden_{t}.json")); it=d["items"][0]
            valid=bool(it.get("passed_match")) and len(it.get("failed_from_pass_to_pass",[]))==0
            return iid,("VALID" if valid else f"DEFECT(reg={len(it.get('failed_from_pass_to_pass',[]))})")
        except Exception as e: return iid,f"GOLDEN_ERR {e}"
    print("=== golden-screen ===")
    survivors=[]
    with cf.ThreadPoolExecutor(max_workers=len(boxes)) as ex:
        for iid,res in ex.map(lambda kv: golden(*kv), boxes.items()):
            print(f"  golden {iid}: {res}");
            if res=="VALID": survivors.append(iid)
    st["survivors"]=survivors; json.dump(st,open(statef(tag),"w"),indent=1)
    print(f"survivors ({len(survivors)}):", survivors)

def solve(tag):
    st=json.load(open(statef(tag))); tasks=st["tasks"]
    def one(iid):
        info=st["boxes"][iid]; t=iid.replace('/','_')
        env=f"/tmp/{tag}box_{t}.env"; pathlib.Path(env).write_text(f"KEY={st['key']}\nPUBIP={info['ip']}\n")
        subprocess.run(["python3",DRIVER,env,tasks,iid],
                       stdout=open(HERE/f"{tag}_drv_{t}.log","w"),stderr=subprocess.STDOUT,timeout=4000)
        return iid
    print(f"=== solving {len(st['survivors'])} survivors (throttle 3) ===")
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        for iid in ex.map(one, st["survivors"]): print(f"  solved {iid}")

def grade(tag):
    st=json.load(open(statef(tag))); tasks=st["tasks"]
    results={}
    tdict={t["instance_id"]:t for t in json.load(open(tasks))}
    def one(iid):
        info=st["boxes"][iid]; ip=info["ip"]; t=iid.replace('/','_')
        # build patches.json from the driver's per-box patch jsonl
        env_stem=f"{tag}box_{t}"
        pj=HERE/f"rung3_patches_{env_stem}.jsonl"
        if not pj.exists(): return iid,"NO_PATCH"
        L=[json.loads(l) for l in open(pj)]; json.dump(L,open(HERE/f"{tag}_patches_{t}.json","w"))
        scp_to(tag,ip,str(HERE/f"{tag}_patches_{t}.json"),"~/swerebench-v2/patches.json")
        cmd=(f"cd ~/swerebench-v2 && . .venv/bin/activate && sg docker -c "
             f"\"python3.11 scripts/eval.py --json tasks.json --patches patches.json --instance-ids {iid} "
             f"--max-workers 1 --report-json grade_{t}.json\" >grade_{t}.log 2>&1; echo done")
        ssh(tag,ip,cmd,timeout=2600)
        scp_from(tag,ip,f"~/swerebench-v2/grade_{t}.json",str(HERE/f"{tag}_grade_{t}.json"))
        d=json.load(open(HERE/f"{tag}_grade_{t}.json")); it=d["items"][0]
        F2P=set(tdict[iid]["FAIL_TO_PASS"]); got=set(it["from_fail_to_pass"])
        ok=F2P.issubset(got) and len(it["failed_from_pass_to_pass"])==0
        return iid,f"{'RESOLVED' if ok else 'NOT-RESOLVED'} (F2P {len(F2P&got)}/{len(F2P)}, reg={len(it['failed_from_pass_to_pass'])})"
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for iid,res in ex.map(one, st["survivors"]): print(f"  {iid} [{tdict[iid]['language']}]: {res}"); results[iid]=res
    json.dump(results,open(HERE/f"{tag}_verdicts.json","w"),indent=1)

def down(tag):
    st=json.load(open(statef(tag)))
    iids=[b["iid"] for b in st["boxes"].values()]
    aws("ec2","terminate-instances","--instance-ids",*iids); aws("ec2","wait","instance-terminated","--instance-ids",*iids,timeout=400)
    aws("ec2","delete-key-pair","--key-name",st["key"]); aws("ec2","delete-security-group","--group-id",st["sg"])
    pathlib.Path(pem(tag)).unlink(missing_ok=True); print("torn down",len(iids),"boxes + key + sg")

if __name__=="__main__":
    cmd=sys.argv[1]
    if cmd=="up": up(sys.argv[2],sys.argv[3])
    elif cmd=="solve": solve(sys.argv[2])
    elif cmd=="grade": grade(sys.argv[2])
    elif cmd=="down": down(sys.argv[2])
