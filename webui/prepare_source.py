"""Copy only audited package files into a separate Git checkout."""
import json
from pathlib import Path
import shutil
from release import build

root=Path(__file__).resolve().parents[1]
destination=root.parent/'breeze-studio-source'
manifest=build(root,root/'dist')
for name in manifest['files']:
    target=destination/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(root/name,target)
(destination/'.gitignore').write_text('''venv/
outputs/
models/
translation-model/
tools/
tmp/
dist/
pip-cache/
hf-cache/
.update-backups/
__pycache__/
.pytest_cache/
*.pyc
*.log
*.wav
*.mp3
*.flac
*.bin
*.safetensors
.env
.env.*
update-settings.json
!app/models/
!app/models/**
''',encoding='utf-8')
print(json.dumps({'source':str(destination),'files':len(manifest['files']),'bytes':sum((root/n).stat().st_size for n in manifest['files'])}))
