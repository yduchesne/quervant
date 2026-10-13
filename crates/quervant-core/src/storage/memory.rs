//! Deterministic in-memory [`Directory`] backend.
//!
//! `MemoryDirectory` models atomic visibility and create-new semantics. It has
//! **no** durability: a process restart or power loss discards everything, and
//! it never claims otherwise.

use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};

use super::{Directory, ReadHandle, StorageError, StorageKey, StorageOp, WriteHandle};

/// A thread-safe in-memory directory.
#[derive(Clone, Default)]
pub struct MemoryDirectory {
    inner: Arc<Mutex<MemoryState>>,
}

#[derive(Default)]
struct MemoryState {
    files: HashMap<String, Arc<Vec<u8>>>,
    pending: HashSet<String>,
}

impl MemoryDirectory {
    /// Create an empty in-memory directory.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }
}

impl Directory for MemoryDirectory {
    fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
        let mut state = self.inner.lock().expect("memory directory lock");
        if state.files.contains_key(key.as_str()) || state.pending.contains(key.as_str()) {
            return Err(StorageError::AlreadyExists { key: key.clone() });
        }
        state.pending.insert(key.as_str().to_string());
        Ok(Box::new(MemoryWrite {
            inner: Arc::clone(&self.inner),
            key: key.as_str().to_string(),
            buffer: Vec::new(),
            committed: false,
        }))
    }

    fn create_dir_all(&self, prefix: &str) -> Result<(), StorageError> {
        // The in-memory backend has no directory hierarchy: keys are opaque
        // strings, so establishing a prefix is a validated no-op.
        if !prefix.is_empty() {
            StorageKey::parse(prefix)?;
        }
        Ok(())
    }

    fn open_read(&self, key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError> {
        let state = self.inner.lock().expect("memory directory lock");
        let data = state
            .files
            .get(key.as_str())
            .cloned()
            .ok_or_else(|| StorageError::NotFound { key: key.clone() })?;
        Ok(Box::new(MemoryRead { data }))
    }

    fn exists(&self, key: &StorageKey) -> Result<bool, StorageError> {
        let state = self.inner.lock().expect("memory directory lock");
        Ok(state.files.contains_key(key.as_str()))
    }

    fn delete(&self, key: &StorageKey) -> Result<(), StorageError> {
        let mut state = self.inner.lock().expect("memory directory lock");
        state.files.remove(key.as_str());
        state.pending.remove(key.as_str());
        Ok(())
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        let mut state = self.inner.lock().expect("memory directory lock");
        state
            .files
            .insert(key.as_str().to_string(), Arc::new(data.to_vec()));
        Ok(())
    }

    fn sync(&self) -> Result<(), StorageError> {
        Ok(())
    }

    fn list(&self, prefix: &str, limit: usize) -> Result<Vec<StorageKey>, StorageError> {
        if !prefix.is_empty() {
            // Validate the prefix grammar before returning an empty result.
            StorageKey::parse(prefix)?;
        }
        let state = self.inner.lock().expect("memory directory lock");
        let mut keys: Vec<StorageKey> = state
            .files
            .keys()
            .filter(|key| is_direct_child(prefix, key))
            .map(|key| StorageKey::parse(key.as_str()))
            .collect::<Result<_, _>>()?;
        keys.sort();
        if keys.len() > limit {
            return Err(StorageError::LimitExceeded {
                limit: limit as u64,
                requested: keys.len() as u64,
            });
        }
        Ok(keys)
    }

    fn file_len(&self, key: &StorageKey) -> Result<u64, StorageError> {
        let state = self.inner.lock().expect("memory directory lock");
        state
            .files
            .get(key.as_str())
            .map(|data| data.len() as u64)
            .ok_or_else(|| StorageError::NotFound { key: key.clone() })
    }
}

/// Whether `key` is a direct (single-component) child of `prefix`.
fn is_direct_child(prefix: &str, key: &str) -> bool {
    if prefix.is_empty() {
        return !key.contains('/');
    }
    key.strip_prefix(prefix)
        .and_then(|rest| rest.strip_prefix('/'))
        .is_some_and(|rest| !rest.is_empty() && !rest.contains('/'))
}

struct MemoryRead {
    data: Arc<Vec<u8>>,
}

impl ReadHandle for MemoryRead {
    fn len(&self) -> u64 {
        self.data.len() as u64
    }

    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, StorageError> {
        if offset >= self.data.len() as u64 {
            return Ok(0);
        }
        let start = offset as usize;
        let available = self.data.len() - start;
        let count = available.min(buf.len());
        buf[..count].copy_from_slice(&self.data[start..start + count]);
        Ok(count)
    }
}

struct MemoryWrite {
    inner: Arc<Mutex<MemoryState>>,
    key: String,
    buffer: Vec<u8>,
    committed: bool,
}

impl WriteHandle for MemoryWrite {
    fn write_all(&mut self, buf: &[u8]) -> Result<(), StorageError> {
        if self.committed {
            return Err(StorageError::io(
                StorageOp::Write,
                std::io::Error::other("writer already committed"),
            ));
        }
        self.buffer.extend_from_slice(buf);
        Ok(())
    }

    fn sync_all(&mut self) -> Result<(), StorageError> {
        let mut state = self.inner.lock().expect("memory directory lock");
        state
            .files
            .insert(self.key.clone(), Arc::new(self.buffer.clone()));
        state.pending.remove(&self.key);
        self.committed = true;
        Ok(())
    }
}

impl Drop for MemoryWrite {
    fn drop(&mut self) {
        if !self.committed {
            let mut state = self.inner.lock().expect("memory directory lock");
            state.pending.remove(&self.key);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(name: &str) -> StorageKey {
        StorageKey::parse(name).unwrap()
    }

    #[test]
    fn create_commit_and_read() {
        let directory = MemoryDirectory::new();
        let key = key("a");
        let mut writer = directory.create(&key).unwrap();
        writer.write_all(b"hello ").unwrap();
        writer.write_all(b"world").unwrap();
        assert!(!directory.exists(&key).unwrap());
        writer.sync_all().unwrap();
        assert!(directory.exists(&key).unwrap());
        let reader = directory.open_read(&key).unwrap();
        assert_eq!(reader.len(), 11);
        assert!(!reader.is_empty());
        let mut buf = [0u8; 5];
        assert_eq!(reader.read_at(6, &mut buf).unwrap(), 5);
        assert_eq!(&buf, b"world");
        assert_eq!(reader.read_at(11, &mut buf).unwrap(), 0);
        assert_eq!(reader.read_at(0, &mut []).unwrap(), 0);
    }

    #[test]
    fn duplicate_create_and_drop_releases_reservation() {
        let directory = MemoryDirectory::new();
        let key = key("a");
        let writer = directory.create(&key).unwrap();
        assert!(matches!(
            directory.create(&key),
            Err(StorageError::AlreadyExists { .. })
        ));
        drop(writer);
        assert!(directory.create(&key).is_ok());
    }

    #[test]
    fn atomic_write_replaces_and_delete_is_idempotent() {
        let directory = MemoryDirectory::new();
        let key = key("a");
        directory.atomic_write(&key, b"old").unwrap();
        directory.atomic_write(&key, b"new").unwrap();
        let reader = directory.open_read(&key).unwrap();
        assert_eq!(reader.len(), 3);
        directory.delete(&key).unwrap();
        directory.delete(&key).unwrap();
        assert!(!directory.exists(&key).unwrap());
        assert!(matches!(
            directory.open_read(&key),
            Err(StorageError::NotFound { .. })
        ));
        directory.sync().unwrap();
    }

    #[test]
    fn committed_writer_rejects_further_writes() {
        let directory = MemoryDirectory::new();
        let key = key("a");
        let mut writer = directory.create(&key).unwrap();
        writer.write_all(b"x").unwrap();
        writer.sync_all().unwrap();
        assert!(writer.write_all(b"y").is_err());
    }
}
