//! Ordered remote publication of one committed generation (PR 13).
//!
//! The remote commit state machine is:
//!
//! ```text
//! CLEAN(remote base or ABSENT)
//!  -> LOCAL_COMMITTED(candidate)
//!  -> UPLOAD_IMMUTABLE_SEGMENTS
//!  -> UPLOAD_MUTATION_STATE
//!  -> UPLOAD_IMMUTABLE_MANIFEST
//!  -> VERIFY_ALL_REFERENCES
//!  -> CAS_REMOTE_CURRENT   (last, provider-enforced)
//!       -> PUBLISHED | CONFLICT | RECOVERY_REQUIRED
//! ```
//!
//! `CURRENT` is the only mutable authoritative key. Every other object is
//! immutable and content-addressed, uploaded with create-if-absent so an
//! existing byte-identical object is idempotent and a different object under
//! the same key is a typed conflict that is never overwritten.
//!
//! No orphan remote object is ever deleted on failure; online remote garbage
//! collection is deferred.

use quervant_objectstore::{
    ContentDescriptor, ContentDigest, ObjectStore, ObjectStoreError, PutOutcome, PutPrecondition,
    TransferLimits,
};

use crate::index::support;
use crate::index::{CURRENT_KEY, CurrentPointer, IndexError, IndexLimits, IndexResult};
use crate::segment::Manifest;
use crate::storage::{Directory, StorageError, StorageKey};

use super::config::RemoteKeyPrefix;

/// The authoritative remote base a writer last observed.
#[derive(Debug, Clone)]
pub(crate) struct RemoteBase {
    /// Raw bytes of the base `CURRENT`, absent on a first commit.
    pub(crate) current_bytes: Option<Vec<u8>>,
}

impl RemoteBase {
    /// The digest of the base `CURRENT` bytes, if any.
    #[must_use]
    pub(crate) fn digest(&self) -> Option<ContentDigest> {
        self.current_bytes
            .as_ref()
            .map(|bytes| ContentDigest::sha256_v1(bytes))
    }
}

/// One immutable object to publish.
#[derive(Debug)]
pub(crate) struct ImmutableObject {
    /// Logical (unprefixed) key.
    pub(crate) logical_key: StorageKey,
    /// Exact content identity.
    pub(crate) descriptor: ContentDescriptor,
    /// Verified bytes.
    pub(crate) bytes: Vec<u8>,
}

/// The locally committed generation to publish.
#[derive(Debug)]
pub(crate) struct Candidate {
    /// Raw candidate `CURRENT` bytes.
    pub(crate) current_bytes: Vec<u8>,
    /// Candidate generation.
    pub(crate) generation: u64,
    /// Manifest logical key.
    pub(crate) manifest_key: StorageKey,
    /// `CURRENT` descriptor for the manifest.
    pub(crate) manifest_descriptor: ContentDescriptor,
    /// Manifest bytes.
    pub(crate) manifest_bytes: Vec<u8>,
    /// Segments and mutation state, in upload order.
    pub(crate) immutables: Vec<ImmutableObject>,
}

/// Collect the verified candidate generation from the local writer workspace.
pub(crate) fn collect_candidate(
    directory: &dyn Directory,
    pointer: &CurrentPointer,
    limits: &IndexLimits,
) -> IndexResult<Candidate> {
    let manifest_descriptor =
        ContentDescriptor::new(pointer.manifest_length(), pointer.manifest_digest());
    let manifest_key = pointer.manifest_key().clone();
    let manifest_bytes = support::read_verified(
        directory,
        &manifest_key,
        manifest_descriptor,
        limits.max_manifest_bytes(),
    )?;
    let manifest = Manifest::decode(&manifest_bytes, limits.segment_limits())?;
    let segment_max = limits.segment_limits().accepted_segment_bytes();
    let mut immutables = Vec::new();
    for reference in &manifest.segments {
        let logical_key = StorageKey::parse(&reference.object_key)?;
        let descriptor = ContentDescriptor::new(
            reference.content_length,
            ContentDigest::from_sha256_v1_bytes(reference.content_digest),
        );
        let bytes = support::read_verified(directory, &logical_key, descriptor, segment_max)?;
        immutables.push(ImmutableObject {
            logical_key,
            descriptor,
            bytes,
        });
    }
    if let Some(state_ref) = &manifest.mutation_state {
        let logical_key = StorageKey::parse(&state_ref.object_key)?;
        let descriptor = ContentDescriptor::new(
            state_ref.content_length,
            ContentDigest::from_sha256_v1_bytes(state_ref.content_digest),
        );
        let bytes = support::read_verified(
            directory,
            &logical_key,
            descriptor,
            limits.max_mutation_state_bytes(),
        )?;
        immutables.push(ImmutableObject {
            logical_key,
            descriptor,
            bytes,
        });
    }
    let current_bytes = pointer.encode()?;
    Ok(Candidate {
        current_bytes,
        generation: pointer.generation(),
        manifest_key,
        manifest_descriptor,
        manifest_bytes,
        immutables,
    })
}

fn conflict(detail: impl Into<String>) -> IndexError {
    IndexError::RemoteConflict {
        detail: detail.into(),
    }
}

/// Upload immutable objects, then the manifest, then verify all references.
async fn upload_immutables<S: ObjectStore>(
    store: &S,
    prefix: &RemoteKeyPrefix,
    candidate: &Candidate,
) -> IndexResult<()> {
    for object in &candidate.immutables {
        put_immutable(
            store,
            prefix,
            &object.logical_key,
            &object.descriptor,
            &object.bytes,
        )
        .await?;
    }
    put_immutable(
        store,
        prefix,
        &candidate.manifest_key,
        &candidate.manifest_descriptor,
        &candidate.manifest_bytes,
    )
    .await
}

async fn put_immutable<S: ObjectStore>(
    store: &S,
    prefix: &RemoteKeyPrefix,
    logical_key: &StorageKey,
    descriptor: &ContentDescriptor,
    bytes: &[u8],
) -> IndexResult<()> {
    let physical = prefix.key_for(logical_key)?;
    let limits = TransferLimits::new(descriptor.length.max(1));
    match store
        .put(
            &physical,
            descriptor,
            bytes,
            PutPrecondition::IfAbsent,
            &limits,
        )
        .await
    {
        Ok(PutOutcome::Created | PutOutcome::AlreadyPresent) => Ok(()),
        Ok(_) => Ok(()),
        Err(ObjectStoreError::Conflict { .. }) => Err(conflict(format!(
            "immutable object already exists with different bytes: {}",
            logical_key.as_str()
        ))),
        Err(error) => Err(IndexError::Storage(map_object_error(error, logical_key))),
    }
}

async fn verify_references<S: ObjectStore>(
    store: &S,
    prefix: &RemoteKeyPrefix,
    candidate: &Candidate,
) -> IndexResult<()> {
    let mut objects: Vec<(&StorageKey, &ContentDescriptor)> = candidate
        .immutables
        .iter()
        .map(|object| (&object.logical_key, &object.descriptor))
        .collect();
    objects.push((&candidate.manifest_key, &candidate.manifest_descriptor));
    for (logical_key, descriptor) in objects {
        let physical = prefix.key_for(logical_key)?;
        let metadata = match store.head(&physical).await {
            Ok(metadata) => metadata,
            Err(error) => {
                return Err(IndexError::Storage(map_object_error(error, logical_key)));
            }
        };
        if metadata.length != descriptor.length || metadata.digest != descriptor.digest {
            return Err(conflict(format!(
                "published object does not match its declared identity: {}",
                logical_key.as_str()
            )));
        }
    }
    Ok(())
}

fn map_object_error(error: ObjectStoreError, key: &StorageKey) -> StorageError {
    StorageError::from_object_store(error, key)
}

/// Publish `candidate` and atomically advance remote `CURRENT` last.
///
/// Returns the durable remote generation on a definitive success, a reconciled
/// success after an ambiguous outcome, or a typed error. Every error path
/// poisons the calling writer (handled by the caller).
pub(crate) async fn publish<S: ObjectStore>(
    store: &S,
    prefix: &RemoteKeyPrefix,
    base: &RemoteBase,
    candidate: &Candidate,
    max_current_bytes: u64,
) -> IndexResult<u64> {
    upload_immutables(store, prefix, candidate).await?;
    verify_references(store, prefix, candidate).await?;

    let current_logical = StorageKey::parse(CURRENT_KEY)?;
    let physical = prefix.key_for(&current_logical)?;
    let descriptor = ContentDescriptor::of(&candidate.current_bytes);
    let limits = TransferLimits::new(max_current_bytes);
    let precondition = match base.digest() {
        Some(digest) => PutPrecondition::IfMatch(digest),
        None => PutPrecondition::IfAbsent,
    };
    match store
        .put(
            &physical,
            &descriptor,
            &candidate.current_bytes,
            precondition,
            &limits,
        )
        .await
    {
        Ok(PutOutcome::Created | PutOutcome::AlreadyPresent) => Ok(candidate.generation),
        Ok(_) => Ok(candidate.generation),
        Err(ObjectStoreError::PreconditionFailed { .. })
        | Err(ObjectStoreError::Conflict { .. }) => Err(conflict(
            "another writer advanced remote CURRENT before this publication".to_owned(),
        )),
        Err(error) if error.is_transient() => {
            // Ambiguous: the conditional PUT may or may not have applied.
            reconcile_ambiguous(store, prefix, base, candidate, max_current_bytes).await
        }
        Err(error) => Err(IndexError::Storage(map_object_error(
            error,
            &current_logical,
        ))),
    }
}

/// Reconcile an ambiguous `CURRENT` publication by re-reading authoritative
/// state. Never assumes success or failure.
async fn reconcile_ambiguous<S: ObjectStore>(
    store: &S,
    prefix: &RemoteKeyPrefix,
    base: &RemoteBase,
    candidate: &Candidate,
    max_current_bytes: u64,
) -> IndexResult<u64> {
    let current_logical = StorageKey::parse(CURRENT_KEY)?;
    let physical = prefix.key_for(&current_logical)?;
    let limits = TransferLimits::new(max_current_bytes);
    let observed = store.get(&physical, None, &limits).await;
    match observed {
        Ok(bytes) if bytes == candidate.current_bytes => {
            // The candidate pointer is visible; references were verified before
            // the CAS attempt, so this is a reconciled success.
            Ok(candidate.generation)
        }
        Ok(bytes) if base.current_bytes.as_deref() == Some(bytes.as_slice()) => {
            Err(IndexError::RecoveryRequired {
                detail:
                    "remote CURRENT publication outcome is ambiguous; base is still authoritative"
                        .to_owned(),
            })
        }
        Ok(_) => Err(conflict(
            "another writer won remote CURRENT while this publication was ambiguous".to_owned(),
        )),
        Err(ObjectStoreError::NotFound { .. }) => Err(IndexError::RecoveryRequired {
            detail: "remote CURRENT is unreadable or absent after an ambiguous publication"
                .to_owned(),
        }),
        Err(_) => Err(IndexError::RecoveryRequired {
            detail: "remote CURRENT is unreadable after an ambiguous publication".to_owned(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn remote_base_digest_is_sha256_of_bytes() {
        let base = RemoteBase {
            current_bytes: Some(b"abc".to_vec()),
        };
        assert_eq!(base.digest(), Some(ContentDigest::sha256_v1(b"abc")));
        assert!(
            RemoteBase {
                current_bytes: None
            }
            .digest()
            .is_none()
        );
    }
}
