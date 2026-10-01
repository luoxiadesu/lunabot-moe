#!/bot/lunabot/venv/bin/python
"""Restore the previous engine, source and recommendation data as one unit."""
import pathlib,json,subprocess,shutil,os
root=pathlib.Path('/bot/lunabot');stage=pathlib.Path('/bot/lunabot-deck-migration-20261001');backup=stage/'backup';meta=json.loads((backup/'manifest.json').read_text())
subprocess.run(['systemctl','stop','lunabot.service','lunabot-deck-recommender.service'],check=True)
subprocess.run([str(root/'venv/bin/python'),'-m','pip','uninstall','-y','haruki-sekai-deck-recommend-cpp'],check=True)
for p in (backup/'old-engine').iterdir():shutil.copytree(p,pathlib.Path(meta['site_packages'])/p.name,dirs_exist_ok=True)
for rel in ['requirements.txt','src/plugins/sekai/modules/deck.py','src/services/deck_recommender/worker.py','src/services/deck_recommender/serve.py','src/services/deck_recommender/requirements.txt','src/services/deck_recommender/config.yaml']:
 shutil.copy2(backup/rel,root/rel)
subprocess.run(['tar','-xzf',str(backup/'deck-data.tar.gz'),'-C',str(root/'src/services/deck_recommender')],check=True)
# Extra optional master tables are ignored by the older native engine.
p=pathlib.Path('/etc/systemd/system/lunabot-deck-recommender.service.d/haruki-engine.conf')
if p.exists():p.unlink()
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','start','lunabot-deck-recommender.service','lunabot.service'],check=True)
print('Previous engine/source/config restored; user captures and MySekai webhook queue untouched.')
