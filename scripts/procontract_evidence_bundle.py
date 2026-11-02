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
