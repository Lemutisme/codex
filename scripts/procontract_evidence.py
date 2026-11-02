"""Content custody and bounded evidence views; no interpretation or update policy."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid


def digest_file(stream):
    digest=hashlib.sha256()
    for block in iter(lambda:stream.read(1<<20),b''):digest.update(block)
    return digest.hexdigest()


class Evidence:
    def __init__(self, host):
        self.host=host
        self.directory=host.root/'sources'

    def capture(self, path, *, expected_sha256, label, media_type='text/plain', origin=None):
        """Provisioner-only import. Actors receive IDs, never a host-path reader."""
        self.host.allowed()
        path=Path(path)
        self.directory.mkdir(exist_ok=True,mode=0o700)
        temporary=self.directory/(uuid.uuid4().hex+'.partial')
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as source,temporary.open('xb') as target:
                before=os.fstat(source.fileno())
                if not stat.S_ISREG(before.st_mode):raise ValueError('source must be a regular file')
                digest=hashlib.sha256();size=0
                for block in iter(lambda:source.read(1<<20),b''):
                    digest.update(block);target.write(block);size+=len(block)
                after=os.fstat(source.fileno())
                if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                    raise ValueError('source changed during capture')
                identity=digest.hexdigest()
                if identity!=expected_sha256:raise ValueError('source identity differs')
                target.flush();os.fsync(target.fileno())
            destination=self.directory/identity
            if destination.exists():
                with destination.open('rb') as source:
                    if digest_file(source)!=identity:raise ValueError('retained source identity differs')
                temporary.unlink()
            else:
                temporary.chmod(0o400);temporary.replace(destination)
                fd=os.open(self.directory,os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(fd)
                finally:os.close(fd)
            return self.host.put('source',{'sha256':identity,'bytes':size,'media_type':media_type,
                'label':label,'origin':str(path.resolve()) if origin is None else origin})
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, identity, offset=0, length=8192):
        if type(offset) is not int or offset<0 or type(length) is not int or not 1<=length<=65536:
            raise ValueError('source view needs a nonnegative offset and 1..65536 bytes')
        descriptor=self.host.get(identity,'source')
        digest=descriptor.get('sha256')
        if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('invalid retained source digest')
        path=self.directory/descriptor['sha256']
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            before=os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size!=descriptor['bytes']:
                raise ValueError('retained source size/type differs')
            stamp=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)
            with self.host._source_lock:
                if self.host._source_verified.get(descriptor['sha256'])!=stamp:
                    if digest_file(stream)!=descriptor['sha256']:raise ValueError('retained source identity differs')
                    verified=os.fstat(stream.fileno())
                    if (verified.st_dev,verified.st_ino,verified.st_size,verified.st_mtime_ns,verified.st_ctime_ns)!=stamp:
                        raise ValueError('source changed during verification')
                    self.host._source_verified[descriptor['sha256']]=stamp
            if offset>before.st_size:raise ValueError('offset exceeds source')
            stream.seek(offset);data=stream.read(length);after=os.fstat(stream.fileno())
            if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                with self.host._source_lock:self.host._source_verified.pop(descriptor['sha256'],None)
                raise ValueError('source changed during view')
        result={'source':identity,'sha256':descriptor['sha256'],'offset':offset,'end':offset+len(data),
            'bytes':descriptor['bytes'],'eof':offset+len(data)==descriptor['bytes'],
            'slice_sha256':hashlib.sha256(data).hexdigest(),'base64':base64.b64encode(data).decode()}
        try:result['text']=data.decode('utf-8')
        except UnicodeDecodeError:result['text']=None
        return result

    def search(self, text='', kinds=None, after=0, snapshot=None, limit=10):
        """A stable, literal-text page. Corrections are relations, not truth labels."""
        if not isinstance(text,str) or type(after) is not int or after<0 or type(limit) is not int or not 1<=limit<=100:
            raise ValueError('invalid evidence query')
        if kinds is not None and (not isinstance(kinds,list) or not all(isinstance(k,str) for k in kinds)):
            raise ValueError('kinds must be a list')
        with self.host.tx() as db:
            maximum=db.execute('SELECT coalesce(max(rowid),0) FROM objects').fetchone()[0]
            if snapshot is None:snapshot=maximum
            if type(snapshot) is not int or not after<=snapshot<=maximum:raise ValueError('invalid evidence snapshot')
            query='SELECT rowid,id,kind,body FROM objects WHERE rowid>? AND rowid<=? AND instr(lower(body),lower(?))>0'
            params=[after,snapshot,text]
            if kinds is not None:
                query+=' AND kind IN ('+','.join('?' for _ in kinds)+')';params.extend(kinds)
            rows=db.execute(query+' ORDER BY rowid LIMIT ?',(*params,limit+1)).fetchall()
            matches=[]
            for row in rows[:limit]:
                body=json.loads(row['body'])
                encoded=json.dumps({'schema':1,'kind':row['kind'],'body':body},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
                if hashlib.sha256(encoded).hexdigest()!=row['id']:raise ValueError('object identity differs')
                corrections=[r[0] for r in db.execute("SELECT id FROM objects WHERE kind='knowledge' AND rowid<=? AND json_extract(body,'$.supersedes')=? ORDER BY rowid",(snapshot,row['id']))]
                matches.append({'id':row['id'],'kind':row['kind'],'preview':row['body'][:1024],
                    'preview_complete':len(row['body'])<=1024,'superseded_by':corrections})
        return {'snapshot':snapshot,'cursor':rows[min(len(rows),limit)-1]['rowid'] if rows else after,
                'more':len(rows)>limit,'matches':matches}
