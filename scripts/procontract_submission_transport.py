"""Restore submission objects without flattening names or following archive links."""
from pathlib import Path
import subprocess


# Execute inside the already isolated compilation container. Relative directory
# descriptors avoid adding the destination prefix to every filesystem syscall.
# FIFOs are filesystem objects, not regular streams to open or discard.
EXTRACT = r'''import collections,hashlib,json,os,pathlib,stat,sys,tarfile
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
    if not member.issym():os.chmod(name,member.mode,dir_fd=fd,follow_symlinks=False)
    os.utime(name,(member.mtime,member.mtime),dir_fd=fd,follow_symlinks=False)
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
        try:os.fchmod(fd,member.mode);os.utime(fd,(member.mtime,member.mtime))
        finally:os.close(fd)
    print(json.dumps({'members':sum(counts.values()),'types':dict(counts),'content_sha256':content.hexdigest(),
        'scope':'All archive members restored; link targets preserved without traversing them during extraction.'}))
finally:os.close(root)
'''


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
    return env
