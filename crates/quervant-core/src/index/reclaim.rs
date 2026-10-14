//! Conservative reclamation planning (PR 9, Phase 5).
//!
//! PR 9 deliberately ships **no online deletion API**. Independent `Index`
//! handles have independent `PinCounter`s, there is no cross-process
//! reader-exclusion protocol, and `Directory::list` is bounded and may not be
//! complete. Checking a single PIT counter or the writer lock cannot prove that
//! no reader needs an old object.
//!
//! [`plan_reclamation`] therefore produces a dry-run classification only:
//!
//! * `CURRENT_REACHABLE` — the current manifest, its referenced segments and
//!   its mutation-state sidecar.
//! * `HISTORICAL_REACHABLE` — objects referenced by an older but still-present
//!   manifest.
//! * `ORPHAN_CANDIDATE` — an unreferenced object whose exact generation lineage
//!   is independently verifiable. Because PR 9 does not persist a complete
//!   generation/object inventory, this classification is never produced here;
//!   unreferenced objects are `UNKNOWN` instead.
//! * `UNKNOWN` — anything not provably reachable or provably orphaned. Unknown
//!   objects are never deletable.

use std::collections::BTreeSet;

use crate::segment::Manifest;
use crate::storage::{Directory, StorageError, StorageKey};

use super::current::CURRENT_KEY;
use super::error::{IndexError, IndexResult};
use super::limits::IndexLimits;
use super::support;

/// Bounded inventory scan limit per prefix. Exceeding it makes the inventory
/// incomplete (conservative `UNKNOWN`, never `ORPHAN_CANDIDATE`).
pub const INVENTORY_LIMIT: usize = 100_000;

/// Classification of one generation object.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ObjectClass {
    /// Reachable from the authoritative `CURRENT` generation.
    CurrentReachable,
    /// Reachable from a still-present older generation manifest.
    HistoricalReachable,
    /// An unreferenced object with independently verified lineage.
    OrphanCandidate,
    /// Not provably reachable or provably orphaned. Never deletable.
    Unknown,
}

/// One classified object.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObjectRef {
    /// Authoritative object key.
    pub key: String,
    /// Generation lineage when known.
    pub generation: Option<u64>,
}

impl ObjectRef {
    fn new(key: impl Into<String>, generation: Option<u64>) -> Self {
        Self {
            key: key.into(),
            generation,
        }
    }
}

/// A dry-run reclamation plan. No deletion is performed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReclamationPlan {
    /// Objects reachable from the current generation.
    pub current_reachable: Vec<ObjectRef>,
    /// Objects reachable only from historical generations.
    pub historical_reachable: Vec<ObjectRef>,
    /// Objects with independently verified orphan lineage (always empty in PR 9).
    pub orphan_candidates: Vec<ObjectRef>,
    /// Objects that cannot be classified safely. Never deletable.
    pub unknown: Vec<ObjectRef>,
    /// Whether the bounded inventory was complete.
    pub complete_inventory: bool,
    /// Whether online deletion is supported by this build (always `false`).
    pub online_deletion_supported: bool,
}

/// Build a conservative dry-run reclamation plan from the authoritative
/// `CURRENT` generation and a bounded inventory.
pub fn plan_reclamation(
    directory: &dyn Directory,
    limits: &IndexLimits,
) -> IndexResult<ReclamationPlan> {
    let mut complete = true;
    let mut current = BTreeSet::new();
    let mut historical = BTreeSet::new();

    let pointer = support::read_current(directory)?;
    if let Some(pointer) = &pointer {
        current.insert(pointer.manifest_key().as_str().to_owned());
        let descriptor = quervant_objectstore::ContentDescriptor::new(
            pointer.manifest_length(),
            pointer.manifest_digest(),
        );
        let manifest_bytes = support::read_verified(
            directory,
            pointer.manifest_key(),
            descriptor,
            limits.max_manifest_bytes(),
        )?;
        let manifest = Manifest::decode(&manifest_bytes, limits.segment_limits())?;
        for reference in &manifest.segments {
            current.insert(reference.object_key.clone());
        }
        if let Some(state) = &manifest.mutation_state {
            current.insert(state.object_key.clone());
        }
        // Historical manifests.
        let (manifest_keys, manifest_complete) =
            list_or_incomplete(directory, "index/manifests", INVENTORY_LIMIT)?;
        complete &= manifest_complete;
        for key in manifest_keys {
            if key.as_str() == pointer.manifest_key().as_str() {
                continue;
            }
            let generation = generation_from_manifest_key(key.as_str());
            let bytes = match support::read_bounded(directory, &key, limits.max_manifest_bytes()) {
                Ok(bytes) => bytes,
                Err(_) => {
                    complete = false;
                    historical.insert(key.as_str().to_owned());
                    continue;
                }
            };
            match Manifest::decode(&bytes, limits.segment_limits()) {
                Ok(manifest) => {
                    historical.insert(key.as_str().to_owned());
                    for reference in &manifest.segments {
                        historical.insert(reference.object_key.clone());
                    }
                    if let Some(state) = &manifest.mutation_state {
                        historical.insert(state.object_key.clone());
                    }
                    let _ = generation;
                }
                Err(_) => {
                    complete = false;
                    historical.insert(key.as_str().to_owned());
                }
            }
        }
    }

    // Inventory every object prefix. `CURRENT` itself is current-reachable.
    let current_key = StorageKey::parse(CURRENT_KEY)?;
    current.insert(current_key.as_str().to_owned());
    let mut inventory: Vec<(String, Option<u64>)> = Vec::new();
    for prefix in ["index/segments", "index/state", "index"] {
        let (keys, prefix_complete) = list_or_incomplete(directory, prefix, INVENTORY_LIMIT)?;
        complete &= prefix_complete;
        for key in keys {
            // `index` yields immediate files such as `CURRENT`; directories are
            // not listed by the contract.
            inventory.push((key.as_str().to_owned(), None));
        }
    }

    let mut plan = ReclamationPlan {
        current_reachable: Vec::new(),
        historical_reachable: Vec::new(),
        orphan_candidates: Vec::new(),
        unknown: Vec::new(),
        complete_inventory: complete,
        online_deletion_supported: false,
    };
    let mut seen = BTreeSet::new();
    for (key, generation) in inventory {
        if !seen.insert(key.clone()) {
            continue;
        }
        if current.contains(&key) {
            plan.current_reachable.push(ObjectRef::new(key, generation));
        } else if historical.contains(&key) {
            plan.historical_reachable
                .push(ObjectRef::new(key, generation));
        } else {
            // No persisted generation/object inventory exists yet, so lineage
            // cannot be verified: the conservative classification is UNKNOWN.
            plan.unknown.push(ObjectRef::new(key, generation));
        }
    }
    for key in &current {
        if !seen.contains(key) {
            plan.current_reachable
                .push(ObjectRef::new(key.clone(), None));
        }
    }
    for key in &historical {
        if !seen.contains(key) && !current.contains(key) {
            plan.historical_reachable
                .push(ObjectRef::new(key.clone(), None));
        }
    }
    plan.current_reachable.sort_by(|a, b| a.key.cmp(&b.key));
    plan.current_reachable.dedup();
    plan.historical_reachable.sort_by(|a, b| a.key.cmp(&b.key));
    plan.historical_reachable.dedup();
    plan.unknown.sort_by(|a, b| a.key.cmp(&b.key));
    plan.unknown.dedup();
    Ok(plan)
}

impl ReclamationPlan {
    /// Whether any object is currently deletable. Always `false` in PR 9.
    #[must_use]
    pub const fn has_deletable_objects(&self) -> bool {
        false
    }

    /// Total classified objects.
    #[must_use]
    pub fn object_count(&self) -> usize {
        self.current_reachable.len()
            + self.historical_reachable.len()
            + self.orphan_candidates.len()
            + self.unknown.len()
    }
}

fn list_or_incomplete(
    directory: &dyn Directory,
    prefix: &str,
    limit: usize,
) -> IndexResult<(Vec<StorageKey>, bool)> {
    match directory.list(prefix, limit) {
        Ok(keys) => Ok((keys, true)),
        Err(StorageError::LimitExceeded { .. }) => Ok((Vec::new(), false)),
        Err(error) => Err(IndexError::Storage(error)),
    }
}

fn generation_from_manifest_key(key: &str) -> Option<u64> {
    let name = key.strip_prefix("index/manifests/g-")?;
    let name = name.strip_suffix(".manifest")?;
    if name.len() != 16 {
        return None;
    }
    u64::from_str_radix(name, 16).ok()
}
