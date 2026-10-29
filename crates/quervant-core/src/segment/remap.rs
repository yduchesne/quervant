//! Sorted doc-id permutation and total remapping (F09).

use super::decode_budget::DecodeBudget;
use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;
use super::metadata::{MetadataMeter, accumulate, capacity_bytes};

/// Fallibly reserve `count` `u64` slots on a retained mapping vector.
///
/// Replaces `Vec::with_capacity` on the cached construction path so an allocation
/// failure becomes the typed [`SegmentError::LimitExceeded`] that the snapshot
/// classifies as an optional cache failure instead of aborting the process. A zero
/// count reserves nothing.
fn reserve_exact_u64(target: &mut Vec<u64>, count: usize) -> SegmentResult<()> {
    if count == 0 {
        return Ok(());
    }
    target
        .try_reserve_exact(count)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::try_from(count)
                .ok()
                .and_then(|elements| elements.checked_mul(std::mem::size_of::<u64>() as u64))
                .unwrap_or(u64::MAX),
        })
}

/// An identity or explicit bijective permutation between original and physical doc ids.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DocRemap {
    physical_to_original: Vec<u64>,
    original_to_physical: Vec<u64>,
    identity: bool,
}

impl DocRemap {
    /// The identity permutation over `doc_count` documents.
    #[must_use]
    pub fn identity(doc_count: usize) -> Self {
        Self {
            physical_to_original: (0..doc_count as u64).collect(),
            original_to_physical: (0..doc_count as u64).collect(),
            identity: true,
        }
    }

    /// Fallible identity permutation for the metered verified-state path.
    ///
    /// Both arrays are reserved with `try_reserve_exact` **before** any value is
    /// written, so an allocation failure yields a typed resource error (which the
    /// snapshot routes to the verified uncached fallback) instead of aborting, and
    /// no capacity is grown implicitly. `doc_count == 0` reserves nothing.
    fn identity_fallible(doc_count: usize) -> SegmentResult<Self> {
        let (mut physical_to_original, mut original_to_physical) = Self::reserve_pair(doc_count)?;
        for index in 0..doc_count {
            let value = u64::try_from(index).map_err(|_| SegmentError::LimitExceeded {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
            physical_to_original.push(value);
            original_to_physical.push(value);
        }
        Ok(Self {
            physical_to_original,
            original_to_physical,
            identity: true,
        })
    }

    /// Reservations for the two doc-id mapping arrays, sized `first`/`second`.
    ///
    /// The first vector is dropped if the second reservation fails, so no
    /// partially allocated remap can escape. Exposed only inside this module and
    /// its tests; production callers always pass equal counts via
    /// [`Self::reserve_pair`].
    fn reserve_pair_with(first: usize, second: usize) -> SegmentResult<(Vec<u64>, Vec<u64>)> {
        let mut forward: Vec<u64> = Vec::new();
        reserve_exact_u64(&mut forward, first)?;
        let mut inverse: Vec<u64> = Vec::new();
        reserve_exact_u64(&mut inverse, second)?;
        Ok((forward, inverse))
    }

    /// Fallibly reserve both `doc_count`-long `u64` mapping arrays before any
    /// value is read or written, with no implicit `push` growth afterwards.
    fn reserve_pair(doc_count: usize) -> SegmentResult<(Vec<u64>, Vec<u64>)> {
        Self::reserve_pair_with(doc_count, doc_count)
    }

    /// Identity remap with retained-metadata charging and capacity reconciliation.
    ///
    /// Charges the two `doc_count`-long `u64` arrays exactly once, allocates them
    /// fallibly, then charges any allocator capacity excess before returning the
    /// remap. Both the explicit `SortedRemap` state `0` and the absent-section
    /// branch of the cached reader use this constructor.
    pub(crate) fn identity_metered(
        doc_count: usize,
        meter: &mut Option<&mut MetadataMeter>,
    ) -> SegmentResult<Self> {
        let doc_count_u64 = u64::try_from(doc_count).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
        if let Some(meter) = meter.as_deref_mut() {
            meter.charge_vec::<u64>(doc_count_u64)?;
            meter.charge_vec::<u64>(doc_count_u64)?;
        }
        let remap = Self::identity_fallible(doc_count)?;
        if let Some(meter) = meter.as_deref_mut() {
            for capacity in [
                remap.physical_to_original.capacity(),
                remap.original_to_physical.capacity(),
            ] {
                let excess = capacity.saturating_sub(doc_count);
                if excess > 0 {
                    let excess_u64 =
                        u64::try_from(excess).map_err(|_| SegmentError::LimitExceeded {
                            limit: u64::MAX,
                            requested: u64::MAX,
                        })?;
                    meter.charge_vec::<u64>(excess_u64)?;
                }
            }
        }
        Ok(remap)
    }

    /// Build a remap from a physical order, where `order[physical] = original`.
    pub fn from_order(order: Vec<u64>) -> SegmentResult<Self> {
        let doc_count = order.len();
        let mut original_to_physical = vec![u64::MAX; doc_count];
        for (physical, original) in order.iter().enumerate() {
            let original_index =
                usize::try_from(*original).map_err(|_| SegmentError::InvalidRemap {
                    context: "original id out of range",
                })?;
            if original_index >= doc_count {
                return Err(SegmentError::InvalidRemap {
                    context: "original id out of range",
                });
            }
            if original_to_physical[original_index] != u64::MAX {
                return Err(SegmentError::InvalidRemap {
                    context: "duplicate original id",
                });
            }
            original_to_physical[original_index] = physical as u64;
        }
        if original_to_physical.contains(&u64::MAX) {
            return Err(SegmentError::InvalidRemap {
                context: "missing original id",
            });
        }
        let identity = order
            .iter()
            .enumerate()
            .all(|(physical, original)| physical as u64 == *original);
        Ok(Self {
            physical_to_original: order,
            original_to_physical,
            identity,
        })
    }

    /// Whether this is the identity permutation.
    #[must_use]
    pub const fn is_identity(&self) -> bool {
        self.identity
    }

    /// Number of documents.
    #[must_use]
    pub fn doc_count(&self) -> usize {
        self.physical_to_original.len()
    }

    /// Measured retained-metadata charge of both permutation vectors.
    pub(crate) fn metadata_charge(&self) -> SegmentResult<u64> {
        let forward = capacity_bytes::<u64>(self.physical_to_original.capacity())?;
        let inverse = capacity_bytes::<u64>(self.original_to_physical.capacity())?;
        accumulate(forward, inverse)
    }

    /// Map a physical doc id to its original id.
    pub fn physical_to_original(&self, physical: u64) -> SegmentResult<u64> {
        self.physical_to_original
            .get(
                usize::try_from(physical).map_err(|_| SegmentError::InvalidRemap {
                    context: "physical id out of range",
                })?,
            )
            .copied()
            .ok_or(SegmentError::InvalidRemap {
                context: "physical id out of range",
            })
    }

    /// Map an original doc id to its physical id.
    pub fn original_to_physical(&self, original: u64) -> SegmentResult<u64> {
        self.original_to_physical
            .get(
                usize::try_from(original).map_err(|_| SegmentError::InvalidRemap {
                    context: "original id out of range",
                })?,
            )
            .copied()
            .ok_or(SegmentError::InvalidRemap {
                context: "original id out of range",
            })
    }

    /// Encode the SORTED_REMAP section body.
    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        let mut writer = ByteWriter::new();
        if self.identity {
            writer.u8(0);
        } else {
            writer.u8(1);
            for value in &self.physical_to_original {
                writer.u64(*value);
            }
            for value in &self.original_to_physical {
                writer.u64(*value);
            }
        }
        writer.into_vec()
    }

    /// Decode and validate the SORTED_REMAP section body.
    ///
    /// Both permutation arrays are charged cumulatively before either is
    /// allocated; no third inverse vector is constructed.
    pub fn decode(bytes: &[u8], doc_count: usize, limits: &SegmentLimits) -> SegmentResult<Self> {
        Self::decode_metered(bytes, doc_count, limits, &mut None)
    }

    /// Decode and validate the SORTED_REMAP section body, charging retained
    /// allocations before they are made.
    pub(crate) fn decode_metered(
        bytes: &[u8],
        doc_count: usize,
        limits: &SegmentLimits,
        meter: &mut Option<&mut MetadataMeter>,
    ) -> SegmentResult<Self> {
        let mut reader = ByteReader::new(bytes);
        let doc_count_u64 = doc_count as u64;
        match reader.u8("remap state")? {
            0 => {
                reader.expect_end("remap")?;
                let mut budget = DecodeBudget::new(limits);
                budget.reserve_vec::<u64>(doc_count_u64)?;
                budget.reserve_vec::<u64>(doc_count_u64)?;
                // `identity_metered` performs the two retained-array charges once.
                Self::identity_metered(doc_count, meter)
            }
            1 => {
                let doubled = doc_count_u64
                    .checked_mul(2)
                    .ok_or(SegmentError::LimitExceeded {
                        limit: limits.max_decoded_entries(),
                        requested: u64::MAX,
                    })?;
                limits.check_entries(doubled)?;
                super::format::count_min_bytes(
                    "sorted remap",
                    doc_count_u64,
                    16,
                    reader.remaining() as u64,
                )?;
                let mut budget = DecodeBudget::new(limits);
                budget.reserve_vec::<u64>(doc_count_u64)?;
                budget.reserve_vec::<u64>(doc_count_u64)?;
                if let Some(meter) = meter.as_deref_mut() {
                    meter.charge_vec::<u64>(doc_count_u64)?;
                    meter.charge_vec::<u64>(doc_count_u64)?;
                }
                // Both arrays are reserved fallibly before any value is read, so a
                // failed reservation cannot leave a partially decoded remap.
                let (mut physical_to_original, mut original_to_physical) =
                    Self::reserve_pair(doc_count)?;
                for _ in 0..doc_count {
                    physical_to_original.push(reader.u64("remap physical")?);
                }
                for _ in 0..doc_count {
                    original_to_physical.push(reader.u64("remap original")?);
                }
                reader.expect_end("remap")?;
                // Every forward value is in range and agrees with the inverse,
                // which (with equal lengths) proves a bijection.
                for (physical, &original) in physical_to_original.iter().enumerate() {
                    let original_index = usize::try_from(original)
                        .ok()
                        .filter(|index| *index < doc_count)
                        .ok_or(SegmentError::InvalidRemap {
                            context: "original id out of range",
                        })?;
                    if original_to_physical[original_index] != physical as u64 {
                        return Err(SegmentError::InvalidRemap {
                            context: "inverse permutation disagrees",
                        });
                    }
                }
                let identity = physical_to_original
                    .iter()
                    .enumerate()
                    .all(|(physical, original)| physical as u64 == *original);
                Ok(Self {
                    physical_to_original,
                    original_to_physical,
                    identity,
                })
            }
            value => Err(SegmentError::Corrupt {
                context: "remap state",
                detail: format!("invalid {value}"),
            }),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::segment::metadata::{MetadataBudget, MetadataMeter};

    fn directions(remap: &DocRemap) -> (Vec<u64>, Vec<u64>) {
        let count = remap.doc_count() as u64;
        (
            (0..count)
                .map(|id| remap.physical_to_original(id).unwrap())
                .collect(),
            (0..count)
                .map(|id| remap.original_to_physical(id).unwrap())
                .collect(),
        )
    }

    // FX-T06 / FX-I04 / FX-I05 — the fallible identity constructor is byte-for-byte
    // equivalent to the public infallible constructor, reserves exactly
    // `doc_count` slots per array, and preserves both lookup directions.
    #[test]
    fn c15a03_t06_identity_fallible_matches_public_identity() {
        for doc_count in [0usize, 1, 5, 1024] {
            let fallible = DocRemap::identity_fallible(doc_count).expect("identity");
            let public = DocRemap::identity(doc_count);
            assert_eq!(fallible, public, "doc_count {doc_count}");
            assert!(fallible.is_identity());
            assert_eq!(fallible.doc_count(), doc_count);
            assert_eq!(fallible.physical_to_original.capacity(), doc_count);
            assert_eq!(fallible.original_to_physical.capacity(), doc_count);

            // Independent integer identity oracle.
            let expected: Vec<u64> = (0..doc_count as u64).collect();
            let (forward, inverse) = directions(&fallible);
            assert_eq!(forward, expected);
            assert_eq!(inverse, expected);
            for index in 0..doc_count as u64 {
                assert_eq!(fallible.physical_to_original(index).unwrap(), index);
                assert_eq!(fallible.original_to_physical(index).unwrap(), index);
            }
            assert!(fallible.physical_to_original(doc_count as u64).is_err());
        }
    }

    // FX-T07 / FX-I04 — an impossible request fails with a typed resource error
    // instead of panicking or aborting, and never retains a partial reservation.
    #[test]
    fn c15a03_t07_identity_fallible_overflow_is_typed() {
        let error = DocRemap::identity_fallible(usize::MAX).expect_err("capacity overflow");
        assert!(matches!(
            error,
            SegmentError::LimitExceeded {
                requested,
                ..
            } if requested == u64::MAX
        ));
        // The metered wrapper fails closed too, with the candidate allowance
        // refunded.
        let budget = MetadataBudget::new(u64::MAX);
        let mut meter = MetadataMeter::reserve(&budget, u64::MAX).expect("allowance");
        assert!(matches!(
            DocRemap::identity_metered(usize::MAX, &mut Some(&mut meter)),
            Err(SegmentError::LimitExceeded { .. })
        ));
        drop(meter);
        assert_eq!(budget.used(), 0);

        // Pre-allocation charge rejection: an allowance below the two retained
        // arrays fails before any allocation and refunds everything.
        let tight_budget = MetadataBudget::new(u64::MAX);
        let element = std::mem::size_of::<u64>() as u64;
        let mut tight =
            MetadataMeter::reserve(&tight_budget, 2 * 5 * element - 1).expect("allowance");
        assert!(matches!(
            DocRemap::identity_metered(5, &mut Some(&mut tight)),
            Err(SegmentError::LimitExceeded { .. })
        ));
        drop(tight);
        assert_eq!(tight_budget.used(), 0);

        // Exact allowance admits and charges exactly two arrays.
        let exact_budget = MetadataBudget::new(u64::MAX);
        let mut exact = MetadataMeter::reserve(&exact_budget, 2 * 5 * element).expect("allowance");
        let remap = DocRemap::identity_metered(5, &mut Some(&mut exact)).expect("identity");
        assert_eq!(remap, DocRemap::identity(5));
        let reservation = exact.finalize(2 * 5 * element).expect("finalize");
        assert_eq!(exact_budget.used(), 2 * 5 * element);
        drop(reservation);
        assert_eq!(exact_budget.used(), 0);
    }

    // Pre-fix counterexample (FX-I04): the metered identity paths previously used
    // the public infallible constructor, which panics with a capacity-overflow
    // abort on an unrepresentable request instead of returning a typed resource
    // error that the snapshot could route to the verified uncached fallback.
    // The cached path must therefore use `identity_fallible`.
    #[test]
    fn c15a03_t07b_infallible_constructor_would_panic() {
        let infallible = std::panic::catch_unwind(|| DocRemap::identity(usize::MAX));
        assert!(
            infallible.is_err(),
            "the infallible constructor must be observably unsafe for the cache path"
        );
        let fallible = DocRemap::identity_fallible(usize::MAX);
        assert!(matches!(fallible, Err(SegmentError::LimitExceeded { .. })));
    }

    // FX-T08 / FX-I05 — the explicit `SortedRemap` state `0` payload and the
    // implicit identity path build the same mapping, through the public and the
    // metered constructors.
    #[test]
    fn c15a03_t08_state_zero_and_absent_section_agree() {
        let limits = SegmentLimits::default();
        for doc_count in [0usize, 1, 7] {
            let payload = [0u8];
            let decoded = DocRemap::decode(&payload, doc_count, &limits).expect("decode");
            assert_eq!(decoded, DocRemap::identity(doc_count));
            let metered = DocRemap::decode_metered(&payload, doc_count, &limits, &mut None)
                .expect("metered decode");
            assert_eq!(metered, DocRemap::identity_fallible(doc_count).unwrap());
            assert_eq!(metered, DocRemap::identity(doc_count));
            assert_eq!(metered.doc_count(), doc_count);

            let budget = MetadataBudget::new(u64::MAX);
            let element = std::mem::size_of::<u64>() as u64;
            let mut meter =
                MetadataMeter::reserve(&budget, 2 * doc_count as u64 * element).expect("allowance");
            let charged =
                DocRemap::decode_metered(&payload, doc_count, &limits, &mut Some(&mut meter))
                    .expect("metered decode with allowance");
            assert_eq!(charged, DocRemap::identity(doc_count));
        }
        // A non-zero state is still a real permutation, not identity.
        let payload = {
            let remap = DocRemap::from_order(vec![1, 0]).expect("permutation");
            remap.encode()
        };
        let decoded = DocRemap::decode(&payload, 2, &limits).expect("decode explicit");
        assert!(!decoded.is_identity());
        assert_eq!(decoded.physical_to_original(0).unwrap(), 1);
    }

    // T05 / F6 — both encodings reserve exactly `doc_count` slots per array, and
    // the explicit (state 1) permutation round-trips against a hand-authored
    // mapping.
    #[test]
    fn f6_t05_reserve_pair_and_explicit_permutation() {
        for doc_count in [0usize, 1, 5, 1024] {
            let (forward, inverse) = DocRemap::reserve_pair(doc_count).expect("pair");
            assert_eq!(forward.capacity(), doc_count);
            assert_eq!(inverse.capacity(), doc_count);
            assert!(forward.is_empty());
            assert!(inverse.is_empty());
        }

        // Explicit non-identity permutation: physical -> original = [2, 0, 1].
        let limits = SegmentLimits::default();
        let expected_forward = vec![2u64, 0, 1];
        let expected_inverse = vec![1u64, 2, 0];
        let payload = {
            let mut writer = ByteWriter::new();
            writer.u8(1);
            for value in &expected_forward {
                writer.u64(*value);
            }
            for value in &expected_inverse {
                writer.u64(*value);
            }
            writer.into_vec()
        };
        let budget = MetadataBudget::new(u64::MAX);
        let element = std::mem::size_of::<u64>() as u64;
        let mut meter = MetadataMeter::reserve(&budget, 2 * 3 * element).expect("allowance");
        let decoded = DocRemap::decode_metered(&payload, 3, &limits, &mut Some(&mut meter))
            .expect("explicit remap");
        assert!(!decoded.is_identity());
        assert_eq!(decoded.doc_count(), 3);
        for physical in 0..3u64 {
            assert_eq!(
                decoded.physical_to_original(physical).expect("forward"),
                expected_forward[physical as usize]
            );
            assert_eq!(
                decoded.original_to_physical(physical).expect("inverse"),
                expected_inverse[physical as usize]
            );
        }
        // Round-trip through the encoder.
        let reencoded = decoded.encode();
        let again = DocRemap::decode(&reencoded, 3, &limits).expect("re-decode");
        assert_eq!(again, decoded);

        // A truncated explicit payload still fails closed.
        assert!(DocRemap::decode(&payload[..payload.len() - 1], 3, &limits).is_err());
    }

    // T06 / F6 — unrepresentable requests are typed errors, and a failed second
    // reservation drops the first vector without leaking or panicking.
    #[test]
    fn f6_t06_reserve_pair_failures_are_typed() {
        assert!(matches!(
            DocRemap::reserve_pair(usize::MAX),
            Err(SegmentError::LimitExceeded { .. })
        ));
        // First reservation succeeds, second fails: the first vector must be
        // dropped and a typed error returned.
        let error =
            DocRemap::reserve_pair_with(4, usize::MAX).expect_err("second reservation fails");
        assert!(matches!(error, SegmentError::LimitExceeded { .. }));
        // Sanity: the same helper succeeds when both are representable.
        let (forward, inverse) = DocRemap::reserve_pair_with(4, 6).expect("both fit");
        assert_eq!(forward.capacity(), 4);
        assert_eq!(inverse.capacity(), 6);
        assert!(forward.is_empty() && inverse.is_empty());

        // The old infallible constructors panic on capacity overflow; the
        // fallible ones return typed errors.
        assert!(std::panic::catch_unwind(|| Vec::<u64>::with_capacity(usize::MAX)).is_err());
        assert!(matches!(
            DocRemap::identity_fallible(usize::MAX),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    // The public infallible constructor is unchanged (X20) and remains the only
    // constructor for non-cached callers; its identity semantics are intact.
    #[test]
    fn c15a03_public_identity_contract_unchanged() {
        let remap = DocRemap::identity(3);
        assert!(remap.is_identity());
        assert_eq!(remap.doc_count(), 3);
        let (forward, inverse) = directions(&remap);
        assert_eq!(forward, vec![0, 1, 2]);
        assert_eq!(inverse, vec![0, 1, 2]);
        assert_eq!(remap, DocRemap::identity(3));
        assert_eq!(DocRemap::identity(0).doc_count(), 0);
    }
}
