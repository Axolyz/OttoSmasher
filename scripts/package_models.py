"""Package the explicit standard model inventory; never archive models/ wholesale."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from ottosmasher.model_inventory import MODELS, model_path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package(output):
    expected = json.loads((ROOT/'dependencies/models.lock.json').read_text())
    for item in json.loads((ROOT/'dependencies/model-support.json').read_text())['files']:
        expected[item['path']] = item
    for manifest in ('features-models.json','flatten-model.json'):
        data=json.loads((ROOT/'dependencies'/manifest).read_text())
        for item in ([data] if 'path' in data else data.values()):
            expected[item['path']]=item
    ts=json.loads((ROOT/'dependencies/model-support.json').read_text())['tsqyomi']
    expected.update({f'models/tsqyomi/{name}':{'sha256':sha} for name,sha in ts['sha256'].items()})
    expected.update(json.loads((ROOT/'dependencies/standard-models.json').read_text()))
    entries=[]
    for relative in sorted({p for files in MODELS.values() for p in files}):
        source=model_path(relative)
        if not source.is_file():
            raise ValueError('Missing required model resource: '+relative)
        sha=digest(source)
        if relative in expected and expected[relative]['sha256'] != sha:
            raise ValueError('Model checksum mismatch: '+relative)
        entries.append({'path':relative,'bytes':source.stat().st_size,'sha256':sha,'source':source})
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_suffix('.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for item in entries:
            print('Packing '+item['path'],flush=True)
            z.write(item['source'],item['path'])
        manifest={'edition':'standard','version':'1.0.0','files':[{k:v for k,v in e.items() if k!='source'} for e in entries]}
        z.writestr('MODEL_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        z.writestr('INSTALL.txt','将 models 目录合并到 OttoSmasher 工作区根目录。设置中的模型状态列出实际路径。不要放入应用资源，不要套两层 models。\n权重与第三方组件保留上游许可；本包不包含旧实验或 PyMSS Studio 模型。\n')
        z.write(ROOT/'THIRD_PARTY_NOTICES.md','THIRD_PARTY_NOTICES.md')
    with zipfile.ZipFile(temp) as z:
        if z.testzip() is not None:
            raise ValueError('Model ZIP CRC verification failed')
    os.replace(temp,output)
    checksum=digest(output)
    output.with_suffix('.zip.sha256').write_text(f'{checksum}  {output.name}\n')
    print(json.dumps({'path':str(output.resolve()),'bytes':output.stat().st_size,'sha256':checksum,'models':list(MODELS),'files':len(entries)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist/OttoSmasher-1.0.0-models.zip')
    package(parser.parse_args().output)
