use std::io;
use std::path::Path;
use std::path::PathBuf;

use codex_pro_contract::Digest;

/// Content-addressed SHA-256 blob store. A blob lives at `<root>/<first two hex>/<hex>` and
/// is verified against its digest on every read.
#[derive(Clone, Debug)]
pub struct BlobStore {
    root: PathBuf,
}

impl BlobStore {
    pub fn open(root: &Path) -> io::Result<Self> {
        std::fs::create_dir_all(root)?;
        Ok(Self {
            root: root.to_path_buf(),
        })
    }

    fn path_of(&self, digest: &Digest) -> PathBuf {
        let hex = digest.to_string();
        self.root.join(&hex[..2]).join(hex)
    }

    /// Stores `bytes` durably and returns their digest. Storing existing content is a no-op.
    pub fn put(&self, bytes: &[u8]) -> io::Result<Digest> {
        let digest = Digest::of(bytes);
        let path = self.path_of(&digest);
        if path.exists() {
            return Ok(digest);
        }
        let dir = path
            .parent()
            .ok_or_else(|| io::Error::other("blob path has no parent"))?;
        std::fs::create_dir_all(dir)?;
        let mut staged = tempfile_in(dir)?;
        std::io::Write::write_all(&mut staged.file, bytes)?;
        staged.file.sync_all()?;
        std::fs::rename(&staged.path, &path)?;
        staged.keep = true;
        Ok(digest)
    }

    /// Returns the blob's bytes, failing if they no longer match the digest.
    pub fn get(&self, digest: &Digest) -> io::Result<Vec<u8>> {
        let bytes = std::fs::read(self.path_of(digest))?;
        if Digest::of(&bytes) != *digest {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("blob {digest} does not match its content"),
            ));
        }
        Ok(bytes)
    }
}

/// A uniquely named staging file that is removed unless it was renamed into place.
struct Staged {
    path: PathBuf,
    file: std::fs::File,
    keep: bool,
}

impl Drop for Staged {
    fn drop(&mut self) {
        if !self.keep {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

fn tempfile_in(dir: &Path) -> io::Result<Staged> {
    static COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let unique = COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let path = dir.join(format!(".staging-{}-{unique}", std::process::id()));
    let file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)?;
    Ok(Staged {
        path,
        file,
        keep: false,
    })
}

#[cfg(test)]
#[path = "blobs_tests.rs"]
mod tests;
