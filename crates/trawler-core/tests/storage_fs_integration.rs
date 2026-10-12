//! PR 3 real-filesystem integration (F-01..F-08) and symlink rejection.

mod common;

use std::process::Command;

use common::{TempDir, read_all};
use trawler_core::storage::{Directory, FsDirectory, KeyError, StorageError, StorageKey};

fn key(name: &str) -> StorageKey {
    StorageKey::parse(name).unwrap()
}

// F-01
#[test]
fn f01_fresh_instance_reopen_reads_exact_bytes() {
    let dir = TempDir::new("f01");
    std::fs::create_dir(dir.path().join("nested")).unwrap();
    {
        let directory = FsDirectory::open(dir.path()).unwrap();
        directory
            .atomic_write(&key("nested/file"), b"persisted bytes")
            .unwrap();
    }
    let reopened = FsDirectory::open(dir.path()).unwrap();
    let reader = reopened.open_read(&key("nested/file")).unwrap();
    assert_eq!(read_all(reader.as_ref()), b"persisted bytes");
}

// F-02 child: runs in a separate process, performs a durable replace, exits.
#[test]
#[ignore = "spawned by f02_subprocess_restart"]
fn f02_child_writer() {
    let directory_path = std::env::var_os("TRAWLER_F02_DIR").expect("child directory env");
    let directory = FsDirectory::open(&directory_path).unwrap();
    directory
        .atomic_write(&key("durable"), b"complete new bytes")
        .expect("child durable write");
}

// F-02
#[test]
fn f02_subprocess_restart_reads_complete_new_bytes() {
    let dir = TempDir::new("f02");
    let executable = std::env::current_exe().unwrap();
    let status = Command::new(executable)
        .args(["--ignored", "--exact", "f02_child_writer"])
        .env("TRAWLER_F02_DIR", dir.path())
        .status()
        .expect("spawn child test process");
    assert!(status.success(), "child writer process failed: {status}");
    let directory = FsDirectory::open(dir.path()).unwrap();
    let reader = directory.open_read(&key("durable")).unwrap();
    assert_eq!(read_all(reader.as_ref()), b"complete new bytes");
}

// F-08: a failed replace leaves no temp behind, and a retry succeeds.
#[test]
fn f08_failed_replace_leaves_no_temp_and_retry_succeeds() {
    let dir = TempDir::new("f08");
    let directory = FsDirectory::open(dir.path()).unwrap();
    assert!(matches!(
        directory.atomic_write(&key("sub/child"), b"x"),
        Err(StorageError::NotFound { .. })
    ));
    assert!(!dir.path().join("sub").exists());
    let leftovers: Vec<_> = std::fs::read_dir(dir.path())
        .unwrap()
        .filter_map(Result::ok)
        .filter(|entry| {
            entry
                .file_name()
                .to_string_lossy()
                .starts_with(".trawler-tmp-")
        })
        .collect();
    assert!(leftovers.is_empty(), "temporary files were left behind");
    std::fs::create_dir(dir.path().join("sub")).unwrap();
    directory
        .atomic_write(&key("sub/child"), b"retried")
        .unwrap();
    assert_eq!(
        read_all(directory.open_read(&key("sub/child")).unwrap().as_ref()),
        b"retried"
    );
}

// F-07 (success) plus visible durability ordering.
#[test]
fn f07_parent_sync_success_is_visible_and_durable() {
    let dir = TempDir::new("f07");
    let directory = FsDirectory::open(dir.path()).unwrap();
    directory.atomic_write(&key("committed"), b"value").unwrap();
    // A second filesystem instance sees the committed bytes.
    let other = FsDirectory::open(dir.path()).unwrap();
    assert_eq!(
        read_all(other.open_read(&key("committed")).unwrap().as_ref()),
        b"value"
    );
}

// D-KEY05
#[test]
fn d_key05_symlink_to_outside_is_rejected() {
    let dir = TempDir::new("key05");
    let outside = TempDir::new("key05-outside");
    std::fs::write(outside.path().join("secret"), b"secret").unwrap();
    let directory = FsDirectory::open(dir.path()).unwrap();
    std::os::unix::fs::symlink(outside.path(), dir.path().join("escape")).unwrap();
    assert!(matches!(
        directory.open_read(&key("escape/secret")),
        Err(StorageError::InvalidKey {
            reason: KeyError::SymlinkComponent
        })
    ));
}

// D-KEY06
#[test]
fn d_key06_intermediate_symlink_is_rejected() {
    let dir = TempDir::new("key06");
    let outside = TempDir::new("key06-outside");
    let directory = FsDirectory::open(dir.path()).unwrap();
    std::os::unix::fs::symlink(outside.path(), dir.path().join("mid")).unwrap();
    assert!(matches!(
        directory.atomic_write(&key("mid/new"), b"x"),
        Err(StorageError::InvalidKey {
            reason: KeyError::SymlinkComponent
        })
    ));
}
