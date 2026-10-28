//! Sorted doc-id permutation and total remapping (F09).

use super::decode_budget::DecodeBudget;
use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;
use super::metadata::{MetadataMeter, accumulate, capacity_bytes};

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
                if let Some(meter) = meter.as_deref_mut() {
                    meter.charge_vec::<u64>(doc_count_u64)?;
                    meter.charge_vec::<u64>(doc_count_u64)?;
                }
                Ok(Self::identity(doc_count))
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
                let mut physical_to_original = Vec::with_capacity(doc_count);
                for _ in 0..doc_count {
                    physical_to_original.push(reader.u64("remap physical")?);
                }
                let mut original_to_physical = Vec::with_capacity(doc_count);
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
