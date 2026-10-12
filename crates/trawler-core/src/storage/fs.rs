//! Real filesystem [`Directory`] with explicit durability semantics.
//!
//! On the initial supported target (Linux local filesystems that honor
//! `fsync` and same-directory atomic `rename`), [`FsDirectory::atomic_write`]
//! writes a same-directory temporary file, syncs it, renames it over the
//! destination, then syncs the containing directory. Success is acknowledged
//! only after that last sync. Other platforms fail closed with
//! [`StorageError::Unsupported`].

use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};

use trawler_objectstore::KeyError;

use super::{
    CorruptionKind, Directory, ReadHandle, StorageError, StorageKey, StorageOp, WriteHandle,
};

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

/// A filesystem-backed directory rooted at one canonicalized directory.
pub struct FsDirectory {
    root: PathBuf,
}

impl FsDirectory {
    /// Open (creating if necessary) a filesystem directory root.
    ///
    /// The root directory is created for convenience; per-key parent
    /// directories are **not** created by writes (S03).
    pub fn open(root: impl AsRef<Path>) -> Result<Self, StorageError> {
        let root = root.as_ref();
        std::fs::create_dir_all(root).map_err(|error| io_err(StorageOp::Create, error))?;
        let root = std::fs::canonicalize(root).map_err(|error| io_err(StorageOp::Open, error))?;
        Ok(Self { root })
    }

    /// The canonicalized root directory.
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Resolve a key to a path, rejecting any symlinked component.
    ///
    /// This is not race-free under concurrent hostile mutation; PR 3's threat
    /// model is a trusted, access-controlled managed root (S01).
    fn resolve(&self, key: &StorageKey) -> Result<PathBuf, StorageError> {
        let mut path = self.root.clone();
        for component in key.components() {
            path.push(component);
            match std::fs::symlink_metadata(&path) {
                Ok(metadata) => {
                    if metadata.file_type().is_symlink() {
                        return Err(StorageError::InvalidKey {
                            reason: KeyError::SymlinkComponent,
                        });
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => return Err(io_err(StorageOp::Open, error)),
            }
        }
        Ok(path)
    }

    /// Resolve a key for writing, requiring the destination parent to exist.
    fn resolve_writable(&self, key: &StorageKey) -> Result<PathBuf, StorageError> {
        let path = self.resolve(key)?;
        let parent = path
            .parent()
            .ok_or_else(|| StorageError::NotFound { key: key.clone() })?;
        match std::fs::symlink_metadata(parent) {
            Ok(metadata) if metadata.file_type().is_dir() => Ok(path),
            Ok(_) => Err(StorageError::NotFound { key: key.clone() }),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                Err(StorageError::NotFound { key: key.clone() })
            }
            Err(error) => Err(io_err(StorageOp::Open, error)),
        }
    }
}

impl Directory for FsDirectory {
    fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
        let path = self.resolve_writable(key)?;
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .map_err(|error| match error.kind() {
                std::io::ErrorKind::AlreadyExists => {
                    StorageError::AlreadyExists { key: key.clone() }
                }
                std::io::ErrorKind::NotFound => StorageError::NotFound { key: key.clone() },
                _ => io_err(StorageOp::Create, error),
            })?;
        Ok(Box::new(FsWriteHandle { file }))
    }

    fn open_read(&self, key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError> {
        let path = self.resolve(key)?;
        let file = File::open(&path).map_err(|error| match error.kind() {
            std::io::ErrorKind::NotFound => StorageError::NotFound { key: key.clone() },
            _ => io_err(StorageOp::Open, error),
        })?;
        let length = file
            .metadata()
            .map_err(|error| io_err(StorageOp::Open, error))?
            .len();
        Ok(Box::new(FsReadHandle {
            file: Mutex::new(file),
            length,
        }))
    }

    fn exists(&self, key: &StorageKey) -> Result<bool, StorageError> {
        let path = self.resolve(key)?;
        match std::fs::symlink_metadata(&path) {
            Ok(metadata) => Ok(metadata.file_type().is_file()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(io_err(StorageOp::Exists, error)),
        }
    }

    fn delete(&self, key: &StorageKey) -> Result<(), StorageError> {
        let path = self.resolve(key)?;
        match std::fs::remove_file(&path) {
            Ok(()) => {
                #[cfg(unix)]
                if let Some(parent) = path.parent() {
                    sync_dir(parent).map_err(|error| io_err(StorageOp::DirSync, error))?;
                }
                Ok(())
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(io_err(StorageOp::Delete, error)),
        }
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        #[cfg(unix)]
        {
            self.atomic_write_impl(key, data, |_| Ok(()))
        }
        #[cfg(not(unix))]
        {
            let _ = (key, data);
            Err(StorageError::Unsupported {
                operation: StorageOp::AtomicWrite,
                platform: std::env::consts::OS,
            })
        }
    }

    fn sync(&self) -> Result<(), StorageError> {
        sync_dir(&self.root).map_err(|error| io_err(StorageOp::DirSync, error))
    }

    fn list(&self, prefix: &str, limit: usize) -> Result<Vec<StorageKey>, StorageError> {
        let directory_path = if prefix.is_empty() {
            self.root.clone()
        } else {
            let prefix_key = StorageKey::parse(prefix)?;
            self.resolve(&prefix_key)?
        };
        let scope_key = if prefix.is_empty() {
            StorageKey::parse("cache-root").expect("synthetic scope key is valid")
        } else {
            StorageKey::parse(prefix)?
        };
        let read_dir = match std::fs::read_dir(&directory_path) {
            Ok(read_dir) => read_dir,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
            Err(error) => return Err(io_err(StorageOp::Open, error)),
        };
        let mut keys = Vec::new();
        for entry in read_dir {
            let entry = entry.map_err(|error| io_err(StorageOp::Open, error))?;
            let file_type = entry
                .file_type()
                .map_err(|error| io_err(StorageOp::Open, error))?;
            // Never follow symlinks; only regular files are cache-owned.
            if file_type.is_symlink() || !file_type.is_file() {
                continue;
            }
            let file_name = entry.file_name();
            let Some(name) = file_name.to_str() else {
                return Err(StorageError::Corrupt {
                    key: scope_key.clone(),
                    detail: CorruptionKind::UnexpectedContent,
                });
            };
            let full = if prefix.is_empty() {
                name.to_string()
            } else {
                format!("{prefix}/{name}")
            };
            let key = StorageKey::parse(full).map_err(|_| StorageError::Corrupt {
                key: scope_key.clone(),
                detail: CorruptionKind::UnexpectedContent,
            })?;
            keys.push(key);
            if keys.len() > limit {
                return Err(StorageError::LimitExceeded {
                    limit: limit as u64,
                    requested: keys.len() as u64,
                });
            }
        }
        keys.sort();
        Ok(keys)
    }

    fn file_len(&self, key: &StorageKey) -> Result<u64, StorageError> {
        let path = self.resolve(key)?;
        let metadata = std::fs::symlink_metadata(&path).map_err(|error| match error.kind() {
            std::io::ErrorKind::NotFound => StorageError::NotFound { key: key.clone() },
            _ => io_err(StorageOp::Open, error),
        })?;
        if metadata.file_type().is_symlink() || !metadata.file_type().is_file() {
            return Err(StorageError::Corrupt {
                key: key.clone(),
                detail: CorruptionKind::UnexpectedContent,
            });
        }
        Ok(metadata.len())
    }
}

impl FsDirectory {
    #[cfg(unix)]
    fn atomic_write_impl<F>(
        &self,
        key: &StorageKey,
        data: &[u8],
        mut hook: F,
    ) -> Result<(), StorageError>
    where
        F: FnMut(AtomicWriteStep) -> Result<(), StorageError>,
    {
        let destination = self.resolve_writable(key)?;
        let parent = destination
            .parent()
            .ok_or_else(|| StorageError::NotFound { key: key.clone() })?
            .to_path_buf();

        hook(AtomicWriteStep::BeforeTempWrite)?;
        let temp_path = temp_path(&parent);
        let mut guard = TempGuard {
            path: temp_path.clone(),
            renamed: false,
        };
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp_path)
            .map_err(|error| io_err(StorageOp::Create, error))?;
        file.write_all(data)
            .map_err(|error| io_err(StorageOp::Write, error))?;
        hook(AtomicWriteStep::MidTempWrite)?;
        file.sync_all()
            .map_err(|error| io_err(StorageOp::Sync, error))?;
        drop(file);
        hook(AtomicWriteStep::AfterTempSync)?;
        std::fs::rename(&temp_path, &destination)
            .map_err(|error| io_err(StorageOp::Rename, error))?;
        guard.renamed = true;
        hook(AtomicWriteStep::AfterRename)?;
        sync_dir(&parent).map_err(|error| io_err(StorageOp::DirSync, error))?;
        hook(AtomicWriteStep::AfterParentSync)?;
        Ok(())
    }

    /// Test-only: `atomic_write` with a step hook, used to observe the real
    /// temporary/destination overlap during a promotion.
    #[cfg(all(test, unix))]
    pub(crate) fn atomic_write_with_hook<F>(
        &self,
        key: &StorageKey,
        data: &[u8],
        hook: F,
    ) -> Result<(), StorageError>
    where
        F: FnMut(AtomicWriteStep) -> Result<(), StorageError>,
    {
        self.atomic_write_impl(key, data, hook)
    }
}

/// A crash-point / failure-injection step inside `atomic_write`.
#[cfg(unix)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum AtomicWriteStep {
    BeforeTempWrite,
    MidTempWrite,
    AfterTempSync,
    AfterRename,
    AfterParentSync,
}

#[cfg(unix)]
struct TempGuard {
    path: PathBuf,
    renamed: bool,
}

#[cfg(unix)]
impl Drop for TempGuard {
    fn drop(&mut self) {
        if !self.renamed {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

#[cfg(unix)]
fn temp_path(parent: &Path) -> PathBuf {
    let counter = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
    parent.join(format!(".trawler-tmp-{}-{counter}", std::process::id()))
}

fn io_err(operation: StorageOp, error: std::io::Error) -> StorageError {
    StorageError::io(operation, error)
}

#[cfg(unix)]
fn sync_dir(directory: &Path) -> std::io::Result<()> {
    File::open(directory)?.sync_all()
}

#[cfg(not(unix))]
fn sync_dir(_directory: &Path) -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "directory sync is unsupported on this platform",
    ))
}

struct FsReadHandle {
    file: Mutex<File>,
    length: u64,
}

impl ReadHandle for FsReadHandle {
    fn len(&self) -> u64 {
        self.length
    }

    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, StorageError> {
        let mut file = self.file.lock().expect("file lock");
        file.seek(SeekFrom::Start(offset))
            .map_err(|error| io_err(StorageOp::Read, error))?;
        file.read(buf)
            .map_err(|error| io_err(StorageOp::Read, error))
    }
}

struct FsWriteHandle {
    file: File,
}

impl WriteHandle for FsWriteHandle {
    fn write_all(&mut self, buf: &[u8]) -> Result<(), StorageError> {
        Write::write_all(&mut self.file, buf).map_err(|error| io_err(StorageOp::Write, error))
    }

    fn sync_all(&mut self) -> Result<(), StorageError> {
        self.file
            .sync_all()
            .map_err(|error| io_err(StorageOp::Sync, error))
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicU64 as TestCounter;

    static TEST_COUNTER: TestCounter = TestCounter::new(0);

    struct TestDir {
        path: PathBuf,
    }

    impl TestDir {
        fn new() -> Self {
            let counter = TEST_COUNTER.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir()
                .join(format!("trawler-fs-unit-{}-{counter}", std::process::id()));
            std::fs::create_dir_all(&path).unwrap();
            Self { path }
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.path);
        }
    }

    fn key(name: &str) -> StorageKey {
        StorageKey::parse(name).unwrap()
    }

    fn read_all(reader: &dyn ReadHandle) -> Vec<u8> {
        let mut buf = vec![0u8; reader.len() as usize];
        let mut filled = 0;
        while filled < buf.len() {
            let read = reader.read_at(filled as u64, &mut buf[filled..]).unwrap();
            if read == 0 {
                break;
            }
            filled += read;
        }
        buf.truncate(filled);
        buf
    }

    fn steps_to_fail(
        step: AtomicWriteStep,
    ) -> impl FnMut(AtomicWriteStep) -> Result<(), StorageError> {
        move |current| {
            if current == step {
                Err(StorageError::io(
                    StorageOp::Write,
                    std::io::Error::other("injected"),
                ))
            } else {
                Ok(())
            }
        }
    }

    #[test]
    fn crash_points_preserve_old_or_expose_complete_new() {
        let dir = TestDir::new();
        let directory = FsDirectory::open(&dir.path).unwrap();
        let target = key("target");
        directory.atomic_write(&target, b"old").unwrap();

        for step in [
            AtomicWriteStep::BeforeTempWrite,
            AtomicWriteStep::MidTempWrite,
            AtomicWriteStep::AfterTempSync,
        ] {
            let mut hook = steps_to_fail(step);
            let result = directory.atomic_write_impl(&target, b"new", &mut hook);
            assert!(result.is_err(), "step {step:?} should fail");
            let reader = directory.open_read(&target).unwrap();
            assert_eq!(
                read_all(reader.as_ref()),
                b"old",
                "step {step:?} must keep old bytes"
            );
            assert!(std::fs::read_dir(&dir.path).unwrap().all(|entry| {
                !entry
                    .unwrap()
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".trawler-tmp-")
            }));
        }

        // Failure after rename but before parent sync: no false durability and
        // only complete old/new bytes, never partial.
        let mut hook = steps_to_fail(AtomicWriteStep::AfterRename);
        let result = directory.atomic_write_impl(&target, b"new", &mut hook);
        assert!(result.is_err());
        let reader = directory.open_read(&target).unwrap();
        assert_eq!(read_all(reader.as_ref()), b"new");

        // Success reaches the final step.
        let mut observed = false;
        let mut hook = |step: AtomicWriteStep| {
            if step == AtomicWriteStep::AfterParentSync {
                observed = true;
            }
            Ok(())
        };
        directory
            .atomic_write_impl(&target, b"final", &mut hook)
            .unwrap();
        assert!(observed);
    }

    #[test]
    fn rejects_symlinked_components() {
        let dir = TestDir::new();
        let outside = dir
            .path
            .join("..")
            .join(format!("outside-{}", std::process::id()));
        std::fs::create_dir_all(&outside).unwrap();
        std::fs::write(outside.join("secret"), b"secret").unwrap();

        let directory = FsDirectory::open(&dir.path).unwrap();
        std::os::unix::fs::symlink(&outside, dir.path.join("link")).unwrap();
        std::os::unix::fs::symlink(outside.join("secret"), dir.path.join("filelink")).unwrap();

        assert!(matches!(
            directory.open_read(&key("link/secret")),
            Err(StorageError::InvalidKey {
                reason: KeyError::SymlinkComponent
            })
        ));
        assert!(matches!(
            directory.create(&key("link/new")),
            Err(StorageError::InvalidKey {
                reason: KeyError::SymlinkComponent
            })
        ));
        assert!(matches!(
            directory.atomic_write(&key("filelink"), b"x"),
            Err(StorageError::InvalidKey {
                reason: KeyError::SymlinkComponent
            })
        ));
        let _ = std::fs::remove_dir_all(&outside);
    }

    #[test]
    fn missing_parent_is_not_created() {
        let dir = TestDir::new();
        let directory = FsDirectory::open(&dir.path).unwrap();
        assert!(matches!(
            directory.atomic_write(&key("missing/child"), b"x"),
            Err(StorageError::NotFound { .. })
        ));
        assert!(!dir.path.join("missing").exists());
    }

    #[test]
    fn create_sync_delete_and_read() {
        let dir = TestDir::new();
        let directory = FsDirectory::open(&dir.path).unwrap();
        let target = key("a");
        let mut writer = directory.create(&target).unwrap();
        writer.write_all(b"hello").unwrap();
        writer.sync_all().unwrap();
        directory.sync().unwrap();
        assert!(directory.exists(&target).unwrap());
        assert!(matches!(
            directory.create(&target),
            Err(StorageError::AlreadyExists { .. })
        ));
        let reader = directory.open_read(&target).unwrap();
        assert_eq!(reader.len(), 5);
        let mut buf = [0u8; 2];
        assert_eq!(reader.read_at(1, &mut buf).unwrap(), 2);
        assert_eq!(&buf, b"el");
        assert_eq!(reader.read_at(5, &mut buf).unwrap(), 0);
        directory.delete(&target).unwrap();
        directory.delete(&target).unwrap();
        assert!(!directory.exists(&target).unwrap());
        assert!(matches!(
            directory.open_read(&target),
            Err(StorageError::NotFound { .. })
        ));
    }

    #[test]
    fn reopen_sees_atomic_write() {
        let dir = TestDir::new();
        {
            let directory = FsDirectory::open(&dir.path).unwrap();
            directory.atomic_write(&key("k"), b"persisted").unwrap();
        }
        let reopened = FsDirectory::open(&dir.path).unwrap();
        let reader = reopened.open_read(&key("k")).unwrap();
        assert_eq!(read_all(reader.as_ref()), b"persisted");
    }
}
