#!/usr/bin/env python3
"""Round-2 fan-out orchestrator: one ephemeral EC2 box per instance.
Provision -> bootstrap (docker+harness) in parallel -> golden-screen each ->
report survivors. Solve + grade are driven separately (rung3_driver.py per box).
Teardown is a separate explicit step (fanout_round2.py teardown) for safety.

Usage:
  fanout_round2.py up      # provision + bootstrap + golden-screen
  fanout_round2.py teardown
"""
import json, subprocess, sys, time, pathlib, concurrent.futures as cf

HERE = pathlib.Path("/tmp/swebench-abduction")
REGION="us-west-2"; AMI="ami-00563078bca04e287"; ITYPE="m7i.xlarge"
VPC="vpc-02c2ac734b774000f"
KEY="rung3-r2-key"; SG_NAME="rung3-r2-sg"; PEM=f"/tmp/{KEY}.pem"
TASKS_LOCAL="/Users/junekim/Documents/supervisor/results/2026-05-20-rung3-calibration/round2_tasks.json"
INSTANCES=[r["instance_id"] for r in json.load(open(TASKS_LOCAL))]
STATE=HERE/"fanout_round2_boxes.json"

def aws(*a, timeout=300):
    return subprocess.run(["aws",*a,"--region",REGION],capture_output=True,text=True,timeout=timeout)

def myip():
    return subprocess.run(["curl","-s","https://checkip.amazonaws.com"],capture_output=True,text=True).stdout.strip()

def ssh(ip, remote, timeout=600, inp=None):
    return subprocess.run(["ssh","-o","StrictHostKeyChecking=no","-o","ConnectTimeout=10","-i",PEM,f"ec2-user@{ip}",remote],
                          capture_output=True,text=True,timeout=timeout,input=inp)

def up():
    # key-pair + SG
    km=aws("ec2","create-key-pair","--key-name",KEY,"--query","KeyMaterial","--output","text")
    pathlib.Path(PEM).write_text(km.stdout); pathlib.Path(PEM).chmod(0o400)
    sg=aws("ec2","create-security-group","--group-name",SG_NAME,"--description","rung3 r2 fanout","--vpc-id",VPC,"--query","GroupId","--output","text").stdout.strip()
    aws("ec2","authorize-security-group-ingress","--group-id",sg,"--protocol","tcp","--port","22","--cidr",f"{myip()}/32")
    # one instance per task
    r=aws("ec2","run-instances","--image-id",AMI,"--instance-type",ITYPE,"--key-name",KEY,
          "--security-group-ids",sg,"--count",str(len(INSTANCES)),
          "--block-device-mappings",'[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":120,"VolumeType":"gp3"}}]',
          "--tag-specifications",'ResourceType=instance,Tags=[{Key=Name,Value=rung3-r2-fanout}]',
          "--query","Instances[].InstanceId","--output","text")
    iids=r.stdout.split()
    print("launched",iids); aws("ec2","wait","instance-running","--instance-ids",*iids,timeout=300)
    desc=aws("ec2","describe-instances","--instance-ids",*iids,"--query","Reservations[].Instances[].[InstanceId,PublicIpAddress]","--output","json")
    pairs=json.loads(desc.stdout)
    boxes={INSTANCES[i]:{"iid":pairs[i][0],"ip":pairs[i][1]} for i in range(len(INSTANCES))}
    json.dump({"sg":sg,"boxes":boxes}, open(STATE,"w"), indent=1)
    print("box map:"); [print(f"  {k} -> {v['ip']} ({v['iid']})") for k,v in boxes.items()]
    return boxes

BOOT = """set -e
sudo dnf install -y -q docker git python3.11 >/dev/null 2>&1
sudo systemctl enable --now docker >/dev/null 2>&1
sudo usermod -aG docker ec2-user
cd ~ && git clone --depth 1 https://github.com/SWE-rebench/SWE-rebench-V2.git swerebench-v2 >/dev/null 2>&1
cd swerebench-v2 && python3.11 -m venv .venv && . .venv/bin/activate && pip install -q -U pip >/dev/null 2>&1
[ -f requirements.txt ] && pip install -q -r requirements.txt >/dev/null 2>&1
[ -f pyproject.toml ] && pip install -q -e . >/dev/null 2>&1
echo BOOTSTRAPPED
"""

def wait_ssh(ip, tries=40):
    for _ in range(tries):
        if ssh(ip,"echo up",timeout=12).stdout.strip()=="up": return True
        time.sleep(8)
    return False

def bootstrap_one(iid, info):
    ip=info["ip"]
    if not wait_ssh(ip): return iid,"SSH_TIMEOUT"
    r=ssh(ip,BOOT,timeout=600)
    if "BOOTSTRAPPED" not in r.stdout: return iid,f"BOOT_FAIL: {(r.stdout+r.stderr)[-200:]}"
    subprocess.run(["scp","-o","StrictHostKeyChecking=no","-i",PEM,TASKS_LOCAL,f"ec2-user@{ip}:~/swerebench-v2/round2_tasks.json"],capture_output=True)
    return iid,"ok"

def golden_one(iid, info):
    ip=info["ip"]
    cmd=(f"cd ~/swerebench-v2 && . .venv/bin/activate && "
         f"sg docker -c \"python3.11 scripts/eval.py --json round2_tasks.json --golden-eval "
         f"--instance-ids {iid} --max-workers 1 --report-json golden_{iid.replace('/','_')}.json\" "
         f">golden_{iid.replace('/','_')}.log 2>&1; tail -1 golden_{iid.replace('/','_')}.log | tr '\\r' '\\n' | tail -1")
    r=ssh(ip,cmd,timeout=2400)
    # pull report
    rep=f"golden_{iid.replace('/','_')}.json"
    subprocess.run(["scp","-o","StrictHostKeyChecking=no","-i",PEM,f"ec2-user@{ip}:~/swerebench-v2/{rep}",str(HERE/f"r2_{rep}")],capture_output=True)
    return iid, r.stdout.strip()

def teardown():
    st=json.load(open(STATE))
    iids=[b["iid"] for b in st["boxes"].values()]
    aws("ec2","terminate-instances","--instance-ids",*iids); aws("ec2","wait","instance-terminated","--instance-ids",*iids,timeout=300)
    aws("ec2","delete-key-pair","--key-name",KEY); aws("ec2","delete-security-group","--group-id",st["sg"])
    pathlib.Path(PEM).unlink(missing_ok=True)
    print("torn down:",iids,"+ key + sg")

if __name__=="__main__":
    if sys.argv[1]=="up":
        boxes=up()
        print("=== bootstrapping (parallel) ===")
        with cf.ThreadPoolExecutor(max_workers=len(boxes)) as ex:
            for iid,res in ex.map(lambda kv: bootstrap_one(*kv), boxes.items()): print(f"  boot {iid}: {res}")
        print("=== golden-screen (parallel) ===")
        with cf.ThreadPoolExecutor(max_workers=len(boxes)) as ex:
            for iid,res in ex.map(lambda kv: golden_one(*kv), boxes.items()): print(f"  golden {iid}: {res}")
    elif sys.argv[1]=="teardown":
        teardown()
