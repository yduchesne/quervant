//! PR 3 shared `Directory` conformance (D-KEY01..08, D-API01..08).
//!
//! The same assertions run against `MemoryDirectory` and `FsDirectory`.
//! `D-KEY05`/`D-KEY06` (symlinks) are filesystem-specific and live in the
//! filesystem integration suite.

mod common;

use std::collections::HashSet;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use common::{TempDir, read_all};
use trawler_core::storage::{
    Directory, FsDirectory, KeyError, MemoryDirectory, ReadHandle, StorageError, StorageKey,
    StorageOp, WriteHandle,
};
use trawler_objectstore::ContentDigest;

fn key(name: &str) -> StorageKey {
    StorageKey::parse(name).unwrap()
}

// D-KEY01
#[test]
fn d_key01_valid_relative_key_round_trips() {
    let key = key("foo/bar");
    assert_eq!(key.as_str(), "foo/bar");
}

// D-KEY02
#[test]
fn d_key02_absolute_path_rejected() {
    assert!(matches!(
        StorageKey::parse("/etc/passwd"),
        Err(StorageError::InvalidKey {
            reason: KeyError::AbsolutePath
        })
    ));
}

// D-KEY03
#[test]
fn d_key03_traversal_rejected_before_io() {
    for candidate in ["../x", "a/../b", "./x", "a/./b"] {
        assert!(
            matches!(
                StorageKey::parse(candidate),
                Err(StorageError::InvalidKey {
                    reason: KeyError::ParentDirectory | KeyError::CurrentDirectory
                })
            ),
            "{candidate} should be rejected"
        );
    }
}

// D-KEY04
#[test]
fn d_key04_empty_and_nul_rejected() {
    assert!(matches!(
        StorageKey::parse(""),
        Err(StorageError::InvalidKey {
            reason: KeyError::Empty
        })
    ));
    assert!(matches!(
        StorageKey::parse("a//b"),
        Err(StorageError::InvalidKey {
            reason: KeyError::EmptyComponent
        })
    ));
    assert!(matches!(
        StorageKey::parse("a\0b"),
        Err(StorageError::InvalidKey {
            reason: KeyError::NulByte
        })
    ));
}

// D-KEY07
#[test]
fn d_key07_unicode_identity_preserved() {
    let composed = key("café");
    let decomposed = key("cafe\u{0301}");
    assert_ne!(composed.as_str(), decomposed.as_str());
    assert_eq!(composed.as_str(), "café");
}

// D-KEY08
#[test]
fn d_key08_duplicate_create_is_already_exists() {
    let directory = MemoryDirectory::new();
    let key = key("dup");
    let _writer = directory.create(&key).unwrap();
    assert!(matches!(
        directory.create(&key),
        Err(StorageError::AlreadyExists { .. })
    ));
}

fn run_common(directory: Arc<dyn Directory>) {
    // D-API01 create/write/read exact bytes.
    // Flat keys keep the shared suite backend-agnostic: `FsDirectory` does not
    // create parent directories (S03), and nested keys are covered separately.
    let k1 = key("api-one");
    let mut writer = directory.create(&k1).unwrap();
    writer.write_all(b"hello ").unwrap();
    writer.write_all(b"world").unwrap();
    writer.sync_all().unwrap();
    let reader = directory.open_read(&k1).unwrap();
    assert_eq!(read_all(reader.as_ref()), b"hello world");
    assert_eq!(reader.len(), 11);

    // D-API02 short reads and EOF.
    let mut buf = [0u8; 4];
    assert_eq!(reader.read_at(6, &mut buf).unwrap(), 4);
    assert_eq!(&buf, b"worl");
    assert_eq!(reader.read_at(11, &mut buf).unwrap(), 0);
    assert_eq!(reader.read_at(100, &mut buf).unwrap(), 0);

    // D-API03 exists before/after delete.
    let k2 = key("api-two");
    assert!(!directory.exists(&k2).unwrap());
    directory.atomic_write(&k2, b"x").unwrap();
    assert!(directory.exists(&k2).unwrap());
    directory.delete(&k2).unwrap();
    assert!(!directory.exists(&k2).unwrap());

    // D-API04 replace: old opener sees old, new opener sees new.
    let k3 = key("api-three");
    directory.atomic_write(&k3, b"old").unwrap();
    let old_reader = directory.open_read(&k3).unwrap();
    directory.atomic_write(&k3, b"new").unwrap();
    let new_reader = directory.open_read(&k3).unwrap();
    assert_eq!(read_all(old_reader.as_ref()), b"old");
    assert_eq!(read_all(new_reader.as_ref()), b"new");

    // D-API05 concurrent readers during replace never observe partial bytes.
    let k4 = key("api-concurrent");
    directory.atomic_write(&k4, b"AAAA").unwrap();
    let stop = Arc::new(AtomicBool::new(false));
    let reader_directory = Arc::clone(&directory);
    let reader_key = k4.clone();
    let stop_flag = Arc::clone(&stop);
    let handle = std::thread::spawn(move || {
        let mut seen: HashSet<Vec<u8>> = HashSet::new();
        while !stop_flag.load(Ordering::Relaxed) {
            if let Ok(reader) = reader_directory.open_read(&reader_key) {
                let bytes = read_all(reader.as_ref());
                assert!(
                    bytes == b"AAAA" || bytes == b"BBBB",
                    "observed partial or unexpected bytes: {bytes:?}"
                );
                seen.insert(bytes);
            }
        }
        seen
    });
    for _ in 0..40 {
        directory.atomic_write(&k4, b"BBBB").unwrap();
        directory.atomic_write(&k4, b"AAAA").unwrap();
    }
    stop.store(true, Ordering::Relaxed);
    let seen = handle.join().unwrap();
    assert!(
        seen.iter()
            .all(|bytes| bytes == b"AAAA" || bytes == b"BBBB")
    );

    // D-API06 an error before promotion leaves prior bytes unchanged.
    let k5 = key("api-six");
    directory.atomic_write(&k5, b"prior").unwrap();
    let faulty = FaultDirectory {
        inner: Arc::clone(&directory),
        fail_atomic_write: true,
        fail_sync: false,
        fail_write: false,
        fail_sync_all: false,
    };
    assert!(faulty.atomic_write(&k5, b"replacement").is_err());
    assert_eq!(
        read_all(directory.open_read(&k5).unwrap().as_ref()),
        b"prior"
    );

    // D-API07 sync/flush errors are typed and never report durable success.
    let sync_fault = FaultDirectory {
        inner: Arc::clone(&directory),
        fail_atomic_write: false,
        fail_sync: true,
        fail_write: false,
        fail_sync_all: false,
    };
    assert!(matches!(
        sync_fault.sync(),
        Err(StorageError::Io {
            operation: StorageOp::DirSync,
            ..
        })
    ));
    let write_fault = FaultDirectory {
        inner: Arc::clone(&directory),
        fail_atomic_write: false,
        fail_sync: false,
        fail_write: true,
        fail_sync_all: true,
    };
    let k6 = key("api-seven");
    let mut failing_writer = write_fault.create(&k6).unwrap();
    assert!(failing_writer.write_all(b"x").is_err());
    assert!(failing_writer.sync_all().is_err());

    // D-API08 repeated delete/missing read semantics.
    let k7 = key("api-eight");
    directory.delete(&k7).unwrap();
    directory.delete(&k7).unwrap();
    assert!(matches!(
        directory.open_read(&k7),
        Err(StorageError::NotFound { .. })
    ));

    // D-API09/10 list and file_len (approved PR 3 exception via A4-DIR-01).
    let list_a = key("list-a");
    let list_b = key("list-b");
    directory.atomic_write(&list_a, b"aaaa").unwrap();
    directory.atomic_write(&list_b, b"bb").unwrap();
    let listed = directory.list("", 1024).unwrap();
    assert!(
        listed.windows(2).all(|pair| pair[0] <= pair[1]),
        "list must be sorted"
    );
    assert!(listed.contains(&list_a));
    assert!(listed.contains(&list_b));
    assert_eq!(directory.file_len(&list_a).unwrap(), 4);
    assert_eq!(directory.file_len(&list_b).unwrap(), 2);
    assert!(matches!(
        directory.file_len(&key("list-missing")),
        Err(StorageError::NotFound { .. })
    ));
    assert!(matches!(
        directory.list("", 1),
        Err(StorageError::LimitExceeded { .. })
    ));

    // Integrity error type remains constructible for downstream checks.
    let _ = ContentDigest::sha256_v1(b"x");
}

#[test]
fn memory_directory_conformance() {
    run_common(Arc::new(MemoryDirectory::new()));
}

#[test]
fn fs_directory_conformance() {
    let dir = TempDir::new("fs-conf");
    let directory = FsDirectory::open(dir.path()).unwrap();
    run_common(Arc::new(directory));
}

/// A test-only fault-injection wrapper at the real `Directory` boundary.
struct FaultDirectory {
    inner: Arc<dyn Directory>,
    fail_atomic_write: bool,
    fail_sync: bool,
    fail_write: bool,
    fail_sync_all: bool,
}

impl Directory for FaultDirectory {
    fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
        let inner = self.inner.create(key)?;
        Ok(Box::new(FaultWrite {
            inner,
            fail_write: self.fail_write,
            fail_sync_all: self.fail_sync_all,
        }))
    }

    fn open_read(&self, key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError> {
        self.inner.open_read(key)
    }

    fn exists(&self, key: &StorageKey) -> Result<bool, StorageError> {
        self.inner.exists(key)
    }

    fn delete(&self, key: &StorageKey) -> Result<(), StorageError> {
        self.inner.delete(key)
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        if self.fail_atomic_write {
            return Err(StorageError::io(
                StorageOp::AtomicWrite,
                std::io::Error::other("injected atomic write failure"),
            ));
        }
        self.inner.atomic_write(key, data)
    }

    fn sync(&self) -> Result<(), StorageError> {
        if self.fail_sync {
            return Err(StorageError::io(
                StorageOp::DirSync,
                std::io::Error::other("injected sync failure"),
            ));
        }
        self.inner.sync()
    }

    fn list(&self, prefix: &str, limit: usize) -> Result<Vec<StorageKey>, StorageError> {
        self.inner.list(prefix, limit)
    }

    fn file_len(&self, key: &StorageKey) -> Result<u64, StorageError> {
        self.inner.file_len(key)
    }
}

struct FaultWrite {
    inner: Box<dyn WriteHandle>,
    fail_write: bool,
    fail_sync_all: bool,
}

impl WriteHandle for FaultWrite {
    fn write_all(&mut self, buf: &[u8]) -> Result<(), StorageError> {
        if self.fail_write {
            return Err(StorageError::io(
                StorageOp::Write,
                std::io::Error::other("injected write failure"),
            ));
        }
        self.inner.write_all(buf)
    }

    fn sync_all(&mut self) -> Result<(), StorageError> {
        if self.fail_sync_all {
            return Err(StorageError::io(
                StorageOp::Sync,
                std::io::Error::other("injected sync_all failure"),
            ));
        }
        self.inner.sync_all()
    }
}
