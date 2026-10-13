//! Manifest codec: schema, segment references and validation (F10).
//!
//! PR 5 serializes/validates a manifest but never publishes `CURRENT`, allocates
//! generations or implements PR 6 lifecycle/fencing.

use crate::storage::StorageKey;
use std::collections::BTreeSet;
use trawler_objectstore::ObjectKey;

use super::bounds::TimeBounds;
use super::error::{SegmentError, SegmentResult};
use super::format::{
    ByteReader, ByteWriter, ContainerBuilder, ContainerKind, SectionKind, parse_container,
};
use super::limits::SegmentLimits;
use super::schema::CodecSchema;

/// A segment reference within a manifest.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ManifestSegmentRef {
    /// Logical segment id.
    pub segment_id: String,
    /// Authoritative object key.
    pub object_key: String,
    /// Content digest algorithm (`0` = sha256-v1).
    pub content_algorithm: u8,
    /// Exact content length.
    pub content_length: u64,
    /// Content digest bytes.
    pub content_digest: [u8; 32],
    /// Optional temporal bounds.
    pub time_bounds: Option<TimeBounds>,
    /// Required features for the referenced segment.
    pub required_features: Vec<(u16, u16)>,
    /// Optional features for the referenced segment.
    pub optional_features: Vec<(u16, u16)>,
}

/// A decoded manifest.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Manifest {
    /// The index schema.
    pub schema: CodecSchema,
    /// Segment references in canonical id order.
    pub segments: Vec<ManifestSegmentRef>,
    /// Manifest-level required features.
    pub required_features: Vec<(u16, u16)>,
    /// Manifest-level optional features.
    pub optional_features: Vec<(u16, u16)>,
}

impl Manifest {
    /// Encode the manifest container.
    pub fn encode(&self) -> SegmentResult<Vec<u8>> {
        let schema_bytes = self.schema.encode()?;
        let mut payload = ByteWriter::new();
        payload.u16(1); // manifest_version
        payload.u32(u32::try_from(schema_bytes.len()).map_err(|_| {
            SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: schema_bytes.len() as u64,
            }
        })?);
        payload.bytes(&schema_bytes);
        payload.u32(u32::try_from(self.segments.len()).map_err(|_| {
            SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: self.segments.len() as u64,
            }
        })?);
        let mut previous: Option<&str> = None;
        let mut object_keys: BTreeSet<&str> = BTreeSet::new();
        for segment in &self.segments {
            if let Some(previous) = previous {
                if previous.as_bytes() >= segment.segment_id.as_bytes() {
                    return Err(SegmentError::InvalidManifest {
                        detail: "segment ids not strictly ascending".to_owned(),
                    });
                }
            }
            if !object_keys.insert(segment.object_key.as_str()) {
                return Err(SegmentError::InvalidManifest {
                    detail: "duplicate object key".to_owned(),
                });
            }
            previous = Some(&segment.segment_id);
            payload.len_prefixed_u16(segment.segment_id.as_bytes())?;
            payload.len_prefixed_u16(segment.object_key.as_bytes())?;
            payload.u8(segment.content_algorithm);
            payload.u64(segment.content_length);
            payload.bytes(&segment.content_digest);
            match segment.time_bounds {
                None => payload.u8(0),
                Some(bounds) => {
                    payload.u8(1);
                    payload.bytes(&bounds.encode());
                }
            }
            encode_features(&mut payload, &segment.required_features)?;
            encode_features(&mut payload, &segment.optional_features)?;
        }
        encode_features(&mut payload, &self.required_features)?;
        encode_features(&mut payload, &self.optional_features)?;

        let mut builder = ContainerBuilder::new(ContainerKind::Manifest, 0);
        for (id, version) in &self.required_features {
            builder.require_feature(*id, *version);
        }
        for (id, version) in &self.optional_features {
            builder.optional_feature(*id, *version);
        }
        builder.section(SectionKind::Manifest, 0, 0, payload.into_vec());
        builder.build()
    }

    /// Decode and validate a manifest container.
    pub fn decode(bytes: &[u8], limits: &SegmentLimits) -> SegmentResult<Self> {
        /// Conservative minimum encoded bytes for one segment reference.
        const MIN_SEGMENT_REF_BYTES: u64 = 2 + 1 + 2 + 1 + 1 + 8 + 32 + 1 + 4 + 4;
        let view = parse_container(bytes, limits)?;
        if view.kind() != ContainerKind::Manifest {
            return Err(SegmentError::InvalidManifest {
                detail: "not a manifest container".to_owned(),
            });
        }
        view.ensure_supported_features()?;
        let body = view
            .body(SectionKind::Manifest)
            .ok_or(SegmentError::MissingSection {
                kind: SectionKind::Manifest as u16,
            })?;
        let mut reader = ByteReader::new(body);
        let version = reader.u16("manifest version")?;
        if version != 1 {
            return Err(SegmentError::Corrupt {
                context: "manifest version",
                detail: format!("unsupported {version}"),
            });
        }
        let schema_len = reader.u32("schema length")?;
        limits.check_allocation_bytes(u64::from(schema_len))?;
        let schema_bytes = reader.bytes(schema_len as usize, "schema bytes")?;
        let schema = CodecSchema::decode(schema_bytes, limits)?;
        let segment_count = reader.u32("segment count")?;
        let segment_count_u64 = u64::from(segment_count);
        limits.check_entries(segment_count_u64)?;
        limits.check_alloc::<ManifestSegmentRef>(segment_count_u64)?;
        super::format::count_min_bytes(
            "manifest segment references",
            segment_count_u64,
            MIN_SEGMENT_REF_BYTES,
            reader.remaining() as u64,
        )?;
        let segment_capacity =
            usize::try_from(segment_count).map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: segment_count_u64,
            })?;
        let mut segments: Vec<ManifestSegmentRef> = Vec::new();
        segments
            .try_reserve_exact(segment_capacity)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: segment_count_u64,
            })?;
        let mut object_keys: BTreeSet<String> = BTreeSet::new();
        // The `segments` vector backing is charged once up front; per-reference
        // variable parts (strings, feature vectors, duplicate index) are charged
        // incrementally below.
        let mut retained_bytes = segment_count_u64
            .checked_mul(std::mem::size_of::<ManifestSegmentRef>() as u64)
            .ok_or(SegmentError::InvalidManifest {
                detail: "retained byte overflow".to_owned(),
            })?;
        limits.check_decoded_bytes(retained_bytes)?;
        for _ in 0..segment_count {
            let segment_id = decode_string(&mut reader, "segment id")?;
            if let Some(previous) = segments.last() {
                if previous.segment_id.as_bytes() >= segment_id.as_bytes() {
                    return Err(SegmentError::InvalidManifest {
                        detail: "segment ids not strictly ascending".to_owned(),
                    });
                }
            }
            StorageKey::parse(segment_id.clone()).map_err(|_| SegmentError::InvalidManifest {
                detail: "invalid segment id".to_owned(),
            })?;
            let object_key = decode_string(&mut reader, "object key")?;
            ObjectKey::parse(object_key.clone()).map_err(|_| SegmentError::InvalidManifest {
                detail: "invalid object key".to_owned(),
            })?;
            if !object_keys.insert(object_key.clone()) {
                return Err(SegmentError::InvalidManifest {
                    detail: "duplicate object key".to_owned(),
                });
            }
            let content_algorithm = reader.u8("content algorithm")?;
            if content_algorithm != 0 {
                return Err(SegmentError::InvalidManifest {
                    detail: "unsupported content digest algorithm".to_owned(),
                });
            }
            let content_length = reader.u64("content length")?;
            if content_length == 0 {
                return Err(SegmentError::InvalidManifest {
                    detail: "zero content length".to_owned(),
                });
            }
            let digest = reader.bytes(32, "content digest")?;
            let mut content_digest = [0u8; 32];
            content_digest.copy_from_slice(digest);
            let time_bounds = match reader.u8("time bounds present")? {
                0 => None,
                1 => {
                    const TIME_BOUNDS_LEN: usize = 39;
                    let bytes = reader.bytes(TIME_BOUNDS_LEN, "time bounds")?;
                    Some(TimeBounds::decode(bytes)?)
                }
                value => {
                    return Err(SegmentError::Corrupt {
                        context: "manifest time bounds",
                        detail: format!("invalid {value}"),
                    });
                }
            };
            let required_features = decode_features(&mut reader, limits)?;
            crate::segment::format::ensure_features_supported(&required_features)?;
            let optional_features = decode_features(&mut reader, limits)?;
            let reference = ManifestSegmentRef {
                segment_id,
                object_key,
                content_algorithm,
                content_length,
                content_digest,
                time_bounds,
                required_features,
                optional_features,
            };
            retained_bytes = retained_bytes
                .checked_add(segment_ref_variable_charge(&reference)?)
                .ok_or(SegmentError::InvalidManifest {
                    detail: "retained byte overflow".to_owned(),
                })?;
            limits.check_decoded_bytes(retained_bytes)?;
            segments.push(reference);
        }
        let required_features = decode_features(&mut reader, limits)?;
        crate::segment::format::ensure_features_supported(&required_features)?;
        let optional_features = decode_features(&mut reader, limits)?;
        let manifest_feature_bytes = (required_features.len() as u64)
            .checked_add(optional_features.len() as u64)
            .and_then(|count| count.checked_mul(std::mem::size_of::<(u16, u16)>() as u64))
            .ok_or(SegmentError::InvalidManifest {
                detail: "retained byte overflow".to_owned(),
            })?;
        retained_bytes = retained_bytes.checked_add(manifest_feature_bytes).ok_or(
            SegmentError::InvalidManifest {
                detail: "retained byte overflow".to_owned(),
            },
        )?;
        limits.check_decoded_bytes(retained_bytes)?;
        reader.expect_end("manifest")?;
        Ok(Self {
            schema,
            segments,
            required_features,
            optional_features,
        })
    }

    /// Conservative retained-byte charge of a decoded manifest.
    ///
    /// This is the same cumulative charge `decode` enforces against
    /// [`SegmentLimits::max_section_decode_bytes`]. It counts the `segments`
    /// vector backing, each owned segment-id/object-key string, each per-segment
    /// feature vector, the duplicate-key index, and the manifest-level feature
    /// vectors. It is a conservative upper bound, not exact allocator telemetry.
    pub fn retained_bytes(&self) -> SegmentResult<u64> {
        let mut total = (self.segments.len() as u64)
            .checked_mul(std::mem::size_of::<ManifestSegmentRef>() as u64)
            .ok_or(SegmentError::InvalidManifest {
                detail: "retained byte overflow".to_owned(),
            })?;
        for reference in &self.segments {
            total = total
                .checked_add(segment_ref_variable_charge(reference)?)
                .ok_or(SegmentError::InvalidManifest {
                    detail: "retained byte overflow".to_owned(),
                })?;
        }
        total = total
            .checked_add(
                (self.required_features.len() as u64)
                    .checked_add(self.optional_features.len() as u64)
                    .and_then(|count| count.checked_mul(std::mem::size_of::<(u16, u16)>() as u64))
                    .ok_or(SegmentError::InvalidManifest {
                        detail: "retained byte overflow".to_owned(),
                    })?,
            )
            .ok_or(SegmentError::InvalidManifest {
                detail: "retained byte overflow".to_owned(),
            })?;
        Ok(total)
    }
}

/// Conservative overhead charged for the duplicate-object-key index entry.
const DUPLICATE_INDEX_BYTES: u64 = std::mem::size_of::<String>() as u64 + 32;

/// Conservative variable-part retained charge for one segment reference.
///
/// Excludes `size_of::<ManifestSegmentRef>()` (charged via the vector backing).
fn segment_ref_variable_charge(reference: &ManifestSegmentRef) -> SegmentResult<u64> {
    let feature_bytes = (reference.required_features.len() as u64)
        .checked_add(reference.optional_features.len() as u64)
        .and_then(|count| count.checked_mul(std::mem::size_of::<(u16, u16)>() as u64))
        .ok_or(SegmentError::InvalidManifest {
            detail: "retained byte overflow".to_owned(),
        })?;
    (reference.segment_id.len() as u64)
        .checked_add((reference.object_key.len() as u64).checked_mul(2).ok_or(
            SegmentError::InvalidManifest {
                detail: "retained byte overflow".to_owned(),
            },
        )?)
        .and_then(|value| value.checked_add(feature_bytes))
        .and_then(|value| value.checked_add(DUPLICATE_INDEX_BYTES))
        .ok_or(SegmentError::InvalidManifest {
            detail: "retained byte overflow".to_owned(),
        })
}

fn encode_features(writer: &mut ByteWriter, features: &[(u16, u16)]) -> SegmentResult<()> {
    writer.u32(
        u32::try_from(features.len()).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: features.len() as u64,
        })?,
    );
    for (id, version) in features {
        writer.u16(*id);
        writer.u16(*version);
    }
    Ok(())
}

fn decode_features(
    reader: &mut ByteReader<'_>,
    limits: &SegmentLimits,
) -> SegmentResult<Vec<(u16, u16)>> {
    let count = reader.u32("feature count")?;
    if count as usize > limits.max_features() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_features() as u64,
            requested: u64::from(count),
        });
    }
    // Each feature is `id:u16` + `version:u16`.
    super::format::count_min_bytes(
        "manifest features",
        u64::from(count),
        4,
        reader.remaining() as u64,
    )?;
    limits.check_alloc::<(u16, u16)>(u64::from(count))?;
    let mut features = Vec::with_capacity(count as usize);
    let mut previous: Option<(u16, u16)> = None;
    for _ in 0..count {
        let id = reader.u16("feature id")?;
        let version = reader.u16("feature version")?;
        if let Some(previous) = previous {
            if (id, version) <= previous {
                return Err(SegmentError::InvalidManifest {
                    detail: "feature sets must be strictly ascending and duplicate-free".to_owned(),
                });
            }
        }
        previous = Some((id, version));
        features.push((id, version));
    }
    Ok(features)
}

fn decode_string(reader: &mut ByteReader<'_>, context: &'static str) -> SegmentResult<String> {
    let bytes = reader.len_prefixed_u16(context)?;
    std::str::from_utf8(bytes)
        .map(str::to_owned)
        .map_err(|_| SegmentError::InvalidUtf8 { context })
}
