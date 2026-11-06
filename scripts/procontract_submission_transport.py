"""Restore submission objects without flattening names or following archive links."""
from pathlib import Path
import shlex
import subprocess


# Execute inside the already isolated compilation container. Relative directory
# descriptors avoid adding the destination prefix to every filesystem syscall.
# FIFOs are filesystem objects, not regular streams to open or discard.
EXTRACT = r'''import collections,hashlib,json,os,pathlib,stat,sys,tarfile
from decimal import Decimal
root=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY)
counts=collections.Counter();directories={};deferred=[];content=hashlib.sha256()
def parts(name):
    path=pathlib.PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:raise ValueError('unsafe submission member: '+name)
    return path.parts
def directory(names,create=False):
    fd=os.dup(root)
    try:
        for name in names:
            if create:
                try:os.mkdir(name,0o700,dir_fd=fd)
                except FileExistsError:pass
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        return fd
    except BaseException:
        os.close(fd);raise
def remove(fd,name):
    try:info=os.stat(name,dir_fd=fd,follow_symlinks=False)
    except FileNotFoundError:return
    if stat.S_ISDIR(info.st_mode):os.rmdir(name,dir_fd=fd)
    else:os.unlink(name,dir_fd=fd)
def metadata(fd,name,member):
    if not stat.S_ISLNK(os.stat(name,dir_fd=fd,follow_symlinks=False).st_mode):os.chmod(name,member.mode,dir_fd=fd,follow_symlinks=False)
    stamp=int(Decimal(member.pax_headers.get('mtime',str(member.mtime)))*1000000000)
    os.utime(name,ns=(stamp,stamp),dir_fd=fd,follow_symlinks=False)
def link(member):
    names=parts(member.name);target=parts(member.linkname)
    if not names or not target:raise ValueError('empty hardlink path')
    source=directory(target[:-1]);dest=directory(names[:-1],True)
    try:
        os.stat(target[-1],dir_fd=source,follow_symlinks=False)
        remove(dest,names[-1])
        os.link(target[-1],names[-1],src_dir_fd=source,dst_dir_fd=dest,follow_symlinks=False)
        metadata(dest,names[-1],member)
    finally:os.close(source);os.close(dest)
try:
    with tarfile.open(fileobj=sys.stdin.buffer,mode='r|gz') as archive:
        for member in archive:
            names=parts(member.name);kind=member.type.decode('ascii','replace')
            counts[kind]+=1
            content.update(json.dumps([member.name,kind,member.mode,member.size,member.linkname],ensure_ascii=True).encode()+b'\n')
            if member.isdir():
                fd=directory(names,True)
                os.fchmod(fd,member.mode|0o700);os.close(fd)
                directories[names]=member
                continue
            if not names:raise ValueError('non-directory root member')
            if member.islnk():
                try:link(member)
                except FileNotFoundError:deferred.append(member)
                continue
            fd=directory(names[:-1],True)
            try:
                name=names[-1];remove(fd,name)
                if member.isfile():
                    target=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
                    with os.fdopen(target,'wb') as output,archive.extractfile(member) as source:
                        while True:
                            block=source.read(1024*1024)
                            if not block:break
                            output.write(block);content.update(block)
                elif member.issym():os.symlink(member.linkname,name,dir_fd=fd)
                elif member.isfifo():os.mkfifo(name,member.mode,dir_fd=fd)
                else:raise ValueError('unsupported submission object type: '+repr(member.type))
                metadata(fd,name,member)
            finally:os.close(fd)
    while deferred:
        remaining=[]
        for member in deferred:
            try:link(member)
            except FileNotFoundError:remaining.append(member)
        if len(remaining)==len(deferred):raise ValueError('unresolved submission hardlink')
        deferred=remaining
    for names,member in sorted(directories.items(),key=lambda item:len(item[0]),reverse=True):
        fd=directory(names)
        try:
            os.fchmod(fd,member.mode)
            stamp=int(Decimal(member.pax_headers.get('mtime',str(member.mtime)))*1000000000)
            os.utime(fd,ns=(stamp,stamp))
        finally:os.close(fd)
    print(json.dumps({'members':sum(counts.values()),'types':dict(counts),'content_sha256':content.hexdigest(),
        'scope':'All archive members restored; link targets preserved without traversing them during extraction.'}))
finally:os.close(root)
'''


WORKSPACE_ARCHIVE = "/opt/procontract-workspace-transfer/workspace.tar.gz"
PACK_WORKSPACE = r'''import hashlib,json,os,stat,tarfile
from pathlib import Path
folder=Path('/opt/procontract-workspace-transfer');folder.mkdir(exist_ok=False)
archive=folder/'workspace.tar.gz';content=hashlib.sha256();inodes={};members=0
class Reader:
    def __init__(self,source):self.source=source
    def read(self,size=-1):
        data=self.source.read(size);content.update(data);return data
def info(name,data):
    member=tarfile.TarInfo(name);member.mode=stat.S_IMODE(data.st_mode)
    member.uid=data.st_uid;member.gid=data.st_gid
    member.mtime=data.st_mtime
    member.pax_headers['mtime']=str(data.st_mtime_ns//1000000000)+'.'+str(data.st_mtime_ns%1000000000).zfill(9)
    return member
def append(stream,member,source=None):
    global members
    members+=1
    content.update(json.dumps([member.name,member.type.decode('ascii','replace'),member.mode,member.size,member.linkname],ensure_ascii=True).encode()+b'\n')
    stream.addfile(member,Reader(source) if source is not None else None)
root_info=os.stat('/workspace');os.chmod('/workspace',stat.S_IMODE(root_info.st_mode)|0o700)
root=os.open('/workspace',os.O_RDONLY|os.O_DIRECTORY)
stack=[(root,'.',iter(sorted(os.listdir(root))),root_info)]
with tarfile.open(archive,'w:gz',format=tarfile.PAX_FORMAT) as output:
    member=info('.',root_info);member.type=tarfile.DIRTYPE;append(output,member)
    while stack:
        fd,prefix,entries,original=stack[-1]
        try:name=next(entries)
        except StopIteration:
            stack.pop();os.fchmod(fd,stat.S_IMODE(original.st_mode));os.close(fd);continue
        data=os.stat(name,dir_fd=fd,follow_symlinks=False);relative=prefix+'/'+name
        member=info(relative,data)
        if stat.S_ISDIR(data.st_mode):
            member.type=tarfile.DIRTYPE;append(output,member)
            os.chmod(name,member.mode|0o700,dir_fd=fd,follow_symlinks=False)
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            stack.append((child,relative,iter(sorted(os.listdir(child))),data))
        elif stat.S_ISREG(data.st_mode):
            key=(data.st_dev,data.st_ino)
            if key in inodes:
                member.type=tarfile.LNKTYPE;member.linkname=inodes[key];append(output,member)
            else:
                inodes[key]=relative;member.type=tarfile.REGTYPE;member.size=data.st_size
                os.chmod(name,member.mode|0o400,dir_fd=fd,follow_symlinks=False)
                source_fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
                try:
                    with os.fdopen(source_fd,'rb',closefd=False) as source:append(output,member,source)
                finally:os.fchmod(source_fd,member.mode);os.close(source_fd)
        elif stat.S_ISLNK(data.st_mode):
            member.type=tarfile.SYMTYPE;member.linkname=os.readlink(name,dir_fd=fd);append(output,member)
        elif stat.S_ISFIFO(data.st_mode):member.type=tarfile.FIFOTYPE;append(output,member)
        else:raise ValueError('unsupported workspace object: '+relative)
digest=hashlib.sha256()
with archive.open('rb') as source:
    for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
os.chmod('/workspace',stat.S_IMODE(root_info.st_mode)|0o700)
root=os.open('/workspace',os.O_RDONLY|os.O_DIRECTORY)
stack=[(root,None,None,iter(os.listdir(root)))]
while stack:
    fd,parent,name,entries=stack[-1]
    try:entry=next(entries)
    except StopIteration:
        stack.pop();os.close(fd)
        if parent is not None:os.rmdir(name,dir_fd=parent)
        continue
    data=os.stat(entry,dir_fd=fd,follow_symlinks=False)
    if stat.S_ISDIR(data.st_mode):
        os.chmod(entry,stat.S_IMODE(data.st_mode)|0o700,dir_fd=fd,follow_symlinks=False)
        child=os.open(entry,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
        stack.append((child,fd,entry,iter(os.listdir(child))))
    else:os.unlink(entry,dir_fd=fd)
os.chmod('/workspace',stat.S_IMODE(root_info.st_mode))
receipt={'archive_sha256':digest.hexdigest(),'members':members,'content_sha256':content.hexdigest(),
    'scope':'Lossless post-compile workspace transport; member identities and bytes verified on restoration.'}
(folder/'receipt.json').write_text(json.dumps(receipt))
print(json.dumps(receipt))
'''


def restore_workspace_transport(env):
    """Decode an image's workspace before any official branch overlays or runs."""
    verify = ("import hashlib,json; from pathlib import Path; "
              f"p=Path({WORKSPACE_ARCHIVE!r}); h=hashlib.sha256(); "
              "f=p.open('rb'); "
              "[h.update(b) for b in iter(lambda:f.read(1048576),b'')]; f.close(); "
              "assert h.hexdigest()==json.loads(p.with_name('receipt.json').read_text())['archive_sha256']")
    extract_verified = ("expected=json.loads(open('/opt/procontract-workspace-transfer/receipt.json').read()); "
                        + "exec(" + repr(EXTRACT) + "); "
                        + "assert content.hexdigest()==expected['content_sha256']; assert sum(counts.values())==expected['members']")
    extract_verified = "import json; " + extract_verified
    command = (f"if test -f {WORKSPACE_ARCHIVE}; then "
               + shlex.join(['python3', '-I', '-S', '-c', verify]) + " && "
               + shlex.join(['python3', '-I', '-S', '-c', extract_verified, '/workspace'])
               + f" < {WORKSPACE_ARCHIVE} && rm -rf /opt/procontract-workspace-transfer; fi")
    result = env.execute(command, timeout=300)
    if result['returncode']:
        raise RuntimeError('Cannot restore compiled workspace: ' + result['output'])
    if result['output'].strip():
        env._pc_restored_workspace = result
    return env


def install_submission_transport(env):
    """Replace only archive transfer; compilation and the submitted bytes stay intact."""
    def copy_submission(archive, destination):
        with Path(archive).open('rb') as source:
            result = subprocess.run([env.executable, 'exec', '-i', env.container_id,
                'python3', '-I', '-S', '-c', EXTRACT, destination], stdin=source,
                capture_output=True, text=True, timeout=300)
        env._pc_submission_transport = {'returncode': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr}
        if result.returncode:
            raise RuntimeError('Submission extraction failed: ' + result.stderr[:4000])
    env.copy_submission = copy_submission
    commit_original = env.commit

    def commit(image):
        try:
            return commit_original(image)
        except RuntimeError as error:
            if 'file name too long' not in str(error).lower():
                raise
            # Image backends may prepend a host snapshot path while walking an
            # otherwise valid container tree. Change its transport encoding;
            # retain the same workspace and compile result for every test.
            result = env.execute(shlex.join(['python3', '-I', '-S', '-c', PACK_WORKSPACE]), timeout=300)
            env._pc_encoded_workspace = {'original_commit_error':str(error), **result}
            if hasattr(env, '_pc_transport_log'):
                env._pc_transport_log.append({'step':'encode_compiled_workspace', **env._pc_encoded_workspace})
            if result['returncode']:
                raise RuntimeError('Cannot encode compiled workspace: ' + result['output']) from error
            return commit_original(image)
    env.commit = commit
    return env
