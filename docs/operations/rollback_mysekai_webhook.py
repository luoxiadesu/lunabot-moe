#!/bot/lunabot/venv/bin/python
"""Rollback this deployment, preserving successful sends recorded in SQLite.
Run on the production host with /bot/lunabot/venv/bin/python.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

root=Path('/bot/lunabot')
backup=Path(Path('/root/lunabot-webhook-backup-path').read_text().strip())
manifest=json.loads((backup/'manifest.json').read_text())
ns=manifest['namespace'];name=manifest['deployment']
old=json.loads((backup/'upload-deployment.json').read_text())
old_container=next(c for c in old['spec']['template']['spec']['containers'] if c['name']=='sekai-upload')
patch={'spec':{'template':{'spec':{'containers':[{
    'name':'sekai-upload','image':old_container['image'],
    'imagePullPolicy':old_container.get('imagePullPolicy','IfNotPresent'),
    'readinessProbe':old_container.get('readinessProbe'),
    'env':[{'name':k,'$patch':'delete'} for k in ['SEKAI_UPLOAD_WEBHOOK_ENABLED','SEKAI_UPLOAD_WEBHOOK_URL','SEKAI_UPLOAD_WEBHOOK_SECRET']]
}]}}}}
subprocess.run(['k3s','kubectl','patch','deployment',name,'-n',ns,'--type=strategic','-p',json.dumps(patch)],check=True)
subprocess.run(['systemctl','stop','lunabot.service'],check=True)
try:
    dbpath=root/'data/sekai/msr_delivery.sqlite3'
    if dbpath.exists():
        con=sqlite3.connect(str(dbpath));dbfile=root/'data/sekai/db.json'
        data=json.loads(dbfile.read_text())
        for region,uid,qid,cycle in con.execute("SELECT region,uid,qid,cycle FROM jobs WHERE state='done'"):
            mapping=data.setdefault(f'{region}_msr_last_push_time',{})
            key=f'{uid}-{qid}';mapping[key]=max(mapping.get(key,0),cycle)
        con.close()
        fd,tmp=tempfile.mkstemp(dir=dbfile.parent,prefix='.msr-rollback-')
        with os.fdopen(fd,'w') as f:
            json.dump(data,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,dbfile.stat().st_mode & 0o777)
        os.replace(tmp,dbfile)
    for rel in ['src/plugins/sekai/modules/mysekai.py','config/sekai/sekai.yaml','config/sekai/gameapi.yaml']:
        shutil.copy2(backup/rel,root/rel)
finally:
    subprocess.run(['systemctl','start','lunabot.service'],check=True)
subprocess.run(['k3s','kubectl','rollout','status','deployment/'+name,'-n',ns,'--timeout=60s'],check=True)
print('Rollback complete. Existing captures, SQLite delivery records and outbox retained.')
