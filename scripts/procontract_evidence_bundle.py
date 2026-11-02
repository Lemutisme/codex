"""Import operator-declared evidence, without deriving lessons or installing policy."""
import argparse
import json
from pathlib import Path

from procontract_operations import Operations,atomic


def ingest(host, bundle):
    if bundle.get('schema')!='procontract-evidence-bundle-v1':raise ValueError('unknown evidence bundle')
    identities={}
    for key,source in bundle.get('sources',{}).items():
        identities[key]=host.capture_source(source['path'],expected_sha256=source['sha256'],
            label=source.get('label',key),media_type=source.get('media_type','text/plain'))
    for entry in bundle.get('records',[]):
        if entry['key'] in identities:raise ValueError('duplicate bundle identity')
        refs=[identities[key] for key in entry['sources']]
        identities[entry['key']]=host.observation(entry['subject'],refs,entry.get('conditions',{}),
            entry['outcome'],entry.get('costs',{}),source=bundle['source'],claim=entry.get('claim',False))
    return {'schema':'procontract-evidence-import-v1','source':bundle['source'],'identities':identities}


def export_objects(host, identities):
    """Retain the cited record closure; this exports no execution/adoption authority."""
    records=[];visited=set()
    def visit(identity):
        if identity in visited:return
        body=host.get(identity)
        with host.tx() as db:
            kind=db.execute('SELECT kind FROM objects WHERE id=?',(identity,)).fetchone()[0]
            event=db.execute('SELECT source FROM events WHERE object_id=? ORDER BY seq LIMIT 1',(identity,)).fetchone()
        refs=[]
        if kind in ('observation','claim','knowledge'):
            refs.extend(body.get('sources',[]));refs.extend(body.get('counterevidence',[]))
            if body.get('supersedes'):refs.append(body['supersedes'])
        for ref in refs:visit(ref)
        record={'id':identity,'kind':kind,'body':body,'source':event[0] if event else 'retained'}
        if kind=='source':record['retained_path']=str(host.root/'sources'/body['sha256'])
        records.append(record);visited.add(identity)
    for identity in identities:visit(identity)
    return {'schema':'procontract-evidence-export-v1','roots':list(identities),'records':records}


def import_objects(host, bundle):
    if bundle.get('schema')!='procontract-evidence-export-v1':raise ValueError('unknown evidence export')
    for record in bundle['records']:
        body=record['body'];kind=record['kind']
        if kind=='source':
            identity=host.capture_source(record['retained_path'],expected_sha256=body['sha256'],
                label=body['label'],media_type=body['media_type'],origin=body['origin'])
        elif kind=='knowledge':identity=host.knowledge(**body)
        else:identity=host.put(kind,body,source=record['source'])
        if identity!=record['id']:raise ValueError('retained evidence identity changed')
    return list(bundle['roots'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',required=True,type=Path)
    parser.add_argument('--bundle',required=True,type=Path)
    parser.add_argument('--receipt',required=True,type=Path)
    args=parser.parse_args()
    receipt=ingest(Operations(args.host),json.loads(args.bundle.read_text()))
    atomic(args.receipt,receipt)
    print(json.dumps({'source':receipt['source'],'objects':len(receipt['identities'])}))


if __name__=='__main__':main()
