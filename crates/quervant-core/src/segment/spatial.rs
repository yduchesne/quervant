//! Immutable field-local 2D KD tree (`SPATIAL_POINTS`, feature `0x000A`) for
//! exact GeoPoint retrieval (PR 12).
//!
//! One tree is built per indexed GeoPoint field over **every** point occurrence.
//! Points alternate splitting longitude (even depth) / latitude (odd depth) by a
//! median split, are serialized preorder, and each node stores the exact extrema
//! of its subtree. The reader validates the complete structure at segment open
//! and fails closed on any malformed, digest-valid section.

use std::collections::BTreeSet;

use crate::contract::value::{FieldType, GeoPoint};

use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;
use super::metadata::{MetadataMeter, accumulate, capacity_bytes};
use super::schema::CodecSchema;

/// On-disk version of the `SPATIAL_POINTS` section body.
pub const SPATIAL_POINTS_VERSION: u16 = 1;
/// Fixed byte width of one encoded node.
pub const SPATIAL_NODE_BYTES: usize = 77;
/// Sentinel used on disk for an absent child index.
pub const ABSENT_INDEX: u32 = u32::MAX;
/// Per-field header width: `field_id(4) + point_count(8) + root_index(8)`.
const SPATIAL_FIELD_HEADER_BYTES: usize = 20;

/// One indexed GeoPoint occurrence.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SpatialPoint {
    /// Physical document id.
    pub doc_id: u64,
    /// Zero-based ordinal among this document's points for the field.
    pub ordinal: u32,
    /// Exact longitude.
    pub lon: f64,
    /// Exact latitude.
    pub lat: f64,
}

/// One serialized KD-tree node.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SpatialNode {
    /// Physical document id.
    pub doc_id: u64,
    /// Zero-based multivalue ordinal.
    pub ordinal: u32,
    /// Exact point longitude.
    pub lon: f64,
    /// Exact point latitude.
    pub lat: f64,
    /// Exact subtree minimum longitude.
    pub min_lon: f64,
    /// Exact subtree minimum latitude.
    pub min_lat: f64,
    /// Exact subtree maximum longitude.
    pub max_lon: f64,
    /// Exact subtree maximum latitude.
    pub max_lat: f64,
    /// Left child index, or [`ABSENT_INDEX`].
    pub left: u32,
    /// Right child index, or [`ABSENT_INDEX`].
    pub right: u32,
    /// Split axis: `0` longitude, `1` latitude.
    pub axis: u8,
}

impl SpatialNode {
    fn placeholder() -> Self {
        Self {
            doc_id: 0,
            ordinal: 0,
            lon: 0.0,
            lat: 0.0,
            min_lon: 0.0,
            min_lat: 0.0,
            max_lon: 0.0,
            max_lat: 0.0,
            left: ABSENT_INDEX,
            right: ABSENT_INDEX,
            axis: 0,
        }
    }
}

/// One field's immutable KD tree.
#[derive(Debug, Clone, PartialEq)]
pub struct SpatialField {
    /// Field id.
    pub field_id: u32,
    /// Root node index, or `None` for a zero-point field.
    pub root: Option<u32>,
    /// Nodes in deterministic preorder.
    pub nodes: Vec<SpatialNode>,
}

impl SpatialField {
    /// Number of points (nodes) in this field.
    #[must_use]
    pub fn point_count(&self) -> usize {
        self.nodes.len()
    }
}

/// The decoded, validated spatial index for one segment.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct SpatialIndex {
    fields: Vec<SpatialField>,
}

impl SpatialIndex {
    /// Look up one field's tree.
    #[must_use]
    pub fn field(&self, field_id: u32) -> Option<&SpatialField> {
        self.fields
            .binary_search_by_key(&field_id, |field| field.field_id)
            .ok()
            .map(|index| &self.fields[index])
    }

    /// All field trees in ascending field-id order.
    #[must_use]
    pub fn fields(&self) -> &[SpatialField] {
        &self.fields
    }

    /// Whether there are no field trees.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.fields.is_empty()
    }

    /// Measured retained-metadata charge of the field and node vectors.
    pub(crate) fn metadata_charge(&self) -> SegmentResult<u64> {
        let mut total = capacity_bytes::<SpatialField>(self.fields.capacity())?;
        for field in &self.fields {
            total = accumulate(
                total,
                capacity_bytes::<SpatialNode>(field.nodes.capacity())?,
            )?;
        }
        Ok(total)
    }

    /// Decode and fully validate a `SPATIAL_POINTS` section body.
    ///
    /// `doc_count` is the owning segment's physical document count and is used
    /// to reject out-of-range physical ids.
    pub fn decode(
        bytes: &[u8],
        schema: &CodecSchema,
        doc_count: u64,
        limits: &SegmentLimits,
    ) -> SegmentResult<Self> {
        Self::decode_metered(bytes, schema, doc_count, limits, &mut None)
    }

    /// Decode and fully validate a `SPATIAL_POINTS` section body, charging every
    /// retained node vector before it is allocated.
    pub(crate) fn decode_metered(
        bytes: &[u8],
        schema: &CodecSchema,
        doc_count: u64,
        limits: &SegmentLimits,
        meter: &mut Option<&mut MetadataMeter>,
    ) -> SegmentResult<Self> {
        let mut reader = ByteReader::new(bytes);
        let version = reader.u16("spatial version")?;
        if version != SPATIAL_POINTS_VERSION {
            return Err(spatial_corrupt("unsupported spatial version"));
        }
        let field_count = reader.u32("spatial field count")?;
        let field_count_u64 = u64::from(field_count);
        limits.check_entries(field_count_u64)?;
        limits.check_alloc::<SpatialField>(field_count_u64)?;
        super::format::count_min_bytes(
            "spatial fields",
            field_count_u64,
            SPATIAL_FIELD_HEADER_BYTES as u64,
            reader.remaining() as u64,
        )?;
        let capacity = usize::try_from(field_count).map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: field_count_u64,
        })?;
        if let Some(meter) = meter.as_deref_mut() {
            meter.charge_vec::<SpatialField>(field_count_u64)?;
        }
        let mut fields: Vec<SpatialField> = Vec::new();
        fields
            .try_reserve_exact(capacity)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: field_count_u64,
            })?;

        let mut previous_field: Option<u32> = None;
        let mut total_decoded: u64 = 0;
        for _ in 0..field_count {
            let field_id = reader.u32("spatial field id")?;
            if let Some(previous) = previous_field {
                if field_id <= previous {
                    return Err(spatial_corrupt("field ids are not strictly increasing"));
                }
            }
            previous_field = Some(field_id);
            let field = schema
                .field(field_id)
                .ok_or(SegmentError::UnknownFieldId { field_id })?;
            if field.field_type != FieldType::GeoPoint {
                return Err(spatial_corrupt("spatial field is not a GeoPoint"));
            }
            if !field.is_indexed() {
                return Err(spatial_corrupt("spatial field is not indexed"));
            }
            let point_count = reader.u64("spatial point count")?;
            let root_raw = reader.u64("spatial root index")?;
            limits.check_entries(point_count)?;
            limits.check_alloc::<SpatialNode>(point_count)?;
            let node_bytes = point_count
                .checked_mul(SPATIAL_NODE_BYTES as u64)
                .ok_or_else(|| spatial_corrupt("spatial node byte count overflow"))?;
            limits.check_decoded_bytes(node_bytes)?;
            total_decoded = total_decoded
                .checked_add(node_bytes)
                .ok_or_else(|| spatial_corrupt("spatial decoded byte count overflow"))?;
            limits.check_decoded_bytes(total_decoded)?;
            super::format::count_min_bytes(
                "spatial nodes",
                point_count,
                SPATIAL_NODE_BYTES as u64,
                reader.remaining() as u64,
            )?;
            let node_capacity =
                usize::try_from(point_count).map_err(|_| SegmentError::LimitExceeded {
                    limit: limits.max_single_allocation(),
                    requested: point_count,
                })?;
            if let Some(meter) = meter.as_deref_mut() {
                meter.charge_vec::<SpatialNode>(point_count)?;
            }
            let mut nodes: Vec<SpatialNode> = Vec::new();
            nodes
                .try_reserve_exact(node_capacity)
                .map_err(|_| SegmentError::LimitExceeded {
                    limit: limits.max_single_allocation(),
                    requested: point_count,
                })?;
            for _ in 0..point_count {
                let doc_id = reader.u64("spatial doc id")?;
                let ordinal = reader.u32("spatial ordinal")?;
                let lon = reader.f64("spatial lon")?;
                let lat = reader.f64("spatial lat")?;
                let min_lon = reader.f64("spatial min lon")?;
                let min_lat = reader.f64("spatial min lat")?;
                let max_lon = reader.f64("spatial max lon")?;
                let max_lat = reader.f64("spatial max lat")?;
                let left = wire_index(reader.u64("spatial left")?)?;
                let right = wire_index(reader.u64("spatial right")?)?;
                let axis = reader.u8("spatial split axis")?;
                if axis > 1 {
                    return Err(spatial_corrupt("invalid spatial split axis"));
                }
                nodes.push(SpatialNode {
                    doc_id,
                    ordinal,
                    lon,
                    lat,
                    min_lon,
                    min_lat,
                    max_lon,
                    max_lat,
                    left,
                    right,
                    axis,
                });
            }
            let root = match root_raw {
                value if value == u64::MAX => None,
                0 => Some(0),
                _ => return Err(spatial_corrupt("spatial root index must be 0 or MAX")),
            };
            validate_field(&nodes, root, doc_count)?;
            fields.push(SpatialField {
                field_id,
                root,
                nodes,
            });
        }

        // Every indexed GeoPoint schema field must have an entry: a feature-bearing
        // section is authoritative and must not silently lose a field.
        for field in schema.fields() {
            if field.field_type == FieldType::GeoPoint
                && field.is_indexed()
                && fields
                    .binary_search_by_key(&field.id, |entry| entry.field_id)
                    .is_err()
            {
                return Err(spatial_corrupt(
                    "indexed GeoPoint field missing from spatial section",
                ));
            }
        }
        reader.expect_end("spatial points")?;
        Ok(Self { fields })
    }
}

fn wire_index(raw: u64) -> SegmentResult<u32> {
    if raw == u64::MAX {
        return Ok(ABSENT_INDEX);
    }
    u32::try_from(raw).map_err(|_| spatial_corrupt("spatial child index out of range"))
}

fn spatial_corrupt(detail: &'static str) -> SegmentError {
    SegmentError::Corrupt {
        context: "spatial points",
        detail: detail.to_owned(),
    }
}

fn validate_coordinate(lon: f64, lat: f64) -> SegmentResult<()> {
    GeoPoint::new(lon, lat).map_err(|_| SegmentError::InvalidGeo {
        detail: "spatial coordinate out of range",
    })?;
    Ok(())
}

fn validate_field(nodes: &[SpatialNode], root: Option<u32>, doc_count: u64) -> SegmentResult<()> {
    if nodes.is_empty() {
        if root.is_some() {
            return Err(spatial_corrupt("empty spatial field has a root"));
        }
        return Ok(());
    }
    if root != Some(0) {
        return Err(spatial_corrupt("non-empty spatial field root is not zero"));
    }
    let count = nodes.len();
    let mut seen: BTreeSet<(u64, u32)> = BTreeSet::new();
    for node in nodes {
        if node.doc_id >= doc_count {
            return Err(spatial_corrupt("spatial doc id out of physical range"));
        }
        validate_coordinate(node.lon, node.lat)?;
        validate_coordinate(node.min_lon, node.min_lat)?;
        validate_coordinate(node.max_lon, node.max_lat)?;
        if !seen.insert((node.doc_id, node.ordinal)) {
            return Err(spatial_corrupt("duplicate spatial (doc_id, ordinal)"));
        }
    }

    // Reachability, cycles, axis and child ordering.
    let mut visited = vec![false; count];
    let mut stack: Vec<(u32, u32)> = vec![(0, 0)];
    while let Some((index, depth)) = stack.pop() {
        let slot = &mut visited[index as usize];
        if *slot {
            return Err(spatial_corrupt("spatial node reached twice"));
        }
        *slot = true;
        let node = nodes[index as usize];
        if node.axis != (depth % 2) as u8 {
            return Err(spatial_corrupt("spatial split axis does not alternate"));
        }
        for child in [node.left, node.right] {
            if child != ABSENT_INDEX {
                if child as usize >= count {
                    return Err(spatial_corrupt("spatial child index out of range"));
                }
                if child <= index {
                    return Err(spatial_corrupt("spatial child is not after its parent"));
                }
                stack.push((child, depth.saturating_add(1)));
            }
        }
    }
    if visited.iter().any(|visited| !visited) {
        return Err(spatial_corrupt("spatial node is unreachable"));
    }

    // Bottom-up exact envelope and contiguous-preorder validation. Children
    // always have a greater index than their parent, so a reverse scan sees
    // every child before its parent.
    let mut recomputed: Vec<(f64, f64, f64, f64)> = vec![(0.0, 0.0, 0.0, 0.0); count];
    let mut subtree_size: Vec<u64> = vec![0; count];
    for index in (0..count).rev() {
        let node = nodes[index];
        let left_size = if node.left != ABSENT_INDEX {
            if u64::from(node.left) != index as u64 + 1 {
                return Err(spatial_corrupt("spatial left child is not contiguous"));
            }
            subtree_size[node.left as usize]
        } else {
            0
        };
        let right_size = if node.right != ABSENT_INDEX {
            if u64::from(node.right) != index as u64 + 1 + left_size {
                return Err(spatial_corrupt("spatial right child is not contiguous"));
            }
            subtree_size[node.right as usize]
        } else {
            0
        };
        subtree_size[index] = 1 + left_size + right_size;

        let mut min_lon = node.lon;
        let mut min_lat = node.lat;
        let mut max_lon = node.lon;
        let mut max_lat = node.lat;
        if node.left != ABSENT_INDEX {
            let (a, b, c, d) = recomputed[node.left as usize];
            min_lon = min_lon.min(a);
            min_lat = min_lat.min(b);
            max_lon = max_lon.max(c);
            max_lat = max_lat.max(d);
        }
        if node.right != ABSENT_INDEX {
            let (a, b, c, d) = recomputed[node.right as usize];
            min_lon = min_lon.min(a);
            min_lat = min_lat.min(b);
            max_lon = max_lon.max(c);
            max_lat = max_lat.max(d);
        }
        if (min_lon, min_lat, max_lon, max_lat)
            != (node.min_lon, node.min_lat, node.max_lon, node.max_lat)
        {
            return Err(spatial_corrupt("spatial subtree envelope mismatch"));
        }
        recomputed[index] = (min_lon, min_lat, max_lon, max_lat);
    }

    // Split-order invariant on the split axis.
    let node_axis = |node: &SpatialNode| if node.axis == 0 { node.lon } else { node.lat };
    for (index, node) in nodes.iter().enumerate() {
        if node.left != ABSENT_INDEX {
            let (_, _, left_max_lon, left_max_lat) = recomputed[node.left as usize];
            let left_max_axis = if node.axis == 0 {
                left_max_lon
            } else {
                left_max_lat
            };
            if left_max_axis > node_axis(node) {
                return Err(spatial_corrupt("left subtree exceeds the split value"));
            }
        }
        if node.right != ABSENT_INDEX {
            let (right_min_lon, right_min_lat, _, _) = recomputed[node.right as usize];
            let right_min_axis = if node.axis == 0 {
                right_min_lon
            } else {
                right_min_lat
            };
            if right_min_axis < node_axis(node) {
                return Err(spatial_corrupt("right subtree is below the split value"));
            }
        }
        let _ = index;
    }
    Ok(())
}

/// One field's points to encode.
#[derive(Debug, Clone, PartialEq)]
pub struct SpatialFieldInput {
    /// Field id.
    pub field_id: u32,
    /// Every point occurrence in physical doc order.
    pub points: Vec<SpatialPoint>,
}

/// Build and encode the deterministic `SPATIAL_POINTS` body.
///
/// Field inputs are sorted by field id. Signed zeros are normalized.
pub fn encode_spatial(
    fields: &mut [SpatialFieldInput],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    fields.sort_by_key(|field| field.field_id);
    for pair in fields.windows(2) {
        if pair[0].field_id == pair[1].field_id {
            return Err(spatial_corrupt("duplicate spatial field id"));
        }
    }
    limits.check_entries(fields.len() as u64)?;

    let mut writer = ByteWriter::new();
    writer.u16(SPATIAL_POINTS_VERSION);
    writer.u32(
        u32::try_from(fields.len()).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: fields.len() as u64,
        })?,
    );
    for field in fields.iter_mut() {
        let nodes = build_tree(&mut field.points, limits)?;
        limits.check_entries(nodes.len() as u64)?;
        limits.check_decoded_bytes(
            (nodes.len() as u64)
                .checked_mul(SPATIAL_NODE_BYTES as u64)
                .ok_or_else(|| spatial_corrupt("spatial node byte count overflow"))?,
        )?;
        writer.u32(field.field_id);
        writer.u64(nodes.len() as u64);
        writer.u64(if nodes.is_empty() { u64::MAX } else { 0 });
        for node in &nodes {
            writer.u64(node.doc_id);
            writer.u32(node.ordinal);
            writer.f64(node.lon);
            writer.f64(node.lat);
            writer.f64(node.min_lon);
            writer.f64(node.min_lat);
            writer.f64(node.max_lon);
            writer.f64(node.max_lat);
            writer.u64(if node.left == ABSENT_INDEX {
                u64::MAX
            } else {
                u64::from(node.left)
            });
            writer.u64(if node.right == ABSENT_INDEX {
                u64::MAX
            } else {
                u64::from(node.right)
            });
            writer.u8(node.axis);
        }
    }
    Ok(writer.into_vec())
}

fn build_tree(
    points: &mut [SpatialPoint],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<SpatialNode>> {
    for point in points.iter_mut() {
        point.lon = normalize(point.lon);
        point.lat = normalize(point.lat);
    }
    let mut nodes: Vec<SpatialNode> = Vec::new();
    nodes
        .try_reserve_exact(points.len())
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: points.len() as u64,
        })?;
    let _ = build_recursive(points, 0, &mut nodes)?;
    Ok(nodes)
}

fn build_recursive(
    points: &mut [SpatialPoint],
    depth: usize,
    nodes: &mut Vec<SpatialNode>,
) -> SegmentResult<Option<u32>> {
    if points.is_empty() {
        return Ok(None);
    }
    let axis = (depth % 2) as u8;
    points.sort_by(|a, b| compare_points(a, b, axis));
    let mid = points.len() / 2;
    let self_index = u32::try_from(nodes.len()).map_err(|_| SegmentError::LimitExceeded {
        limit: u64::from(u32::MAX),
        requested: nodes.len() as u64,
    })?;
    nodes.push(SpatialNode::placeholder());
    let (left_slice, rest) = points.split_at_mut(mid);
    let point = rest[0];
    let right_slice = &mut rest[1..];
    let left = build_recursive(left_slice, depth + 1, nodes)?;
    let right = build_recursive(right_slice, depth + 1, nodes)?;

    let mut envelope = (point.lon, point.lat, point.lon, point.lat);
    if let Some(left) = left {
        envelope = combine(envelope, envelope_of(&nodes[left as usize]));
    }
    if let Some(right) = right {
        envelope = combine(envelope, envelope_of(&nodes[right as usize]));
    }
    nodes[self_index as usize] = SpatialNode {
        doc_id: point.doc_id,
        ordinal: point.ordinal,
        lon: point.lon,
        lat: point.lat,
        min_lon: envelope.0,
        min_lat: envelope.1,
        max_lon: envelope.2,
        max_lat: envelope.3,
        left: left.unwrap_or(ABSENT_INDEX),
        right: right.unwrap_or(ABSENT_INDEX),
        axis,
    };
    Ok(Some(self_index))
}

fn combine(a: (f64, f64, f64, f64), b: (f64, f64, f64, f64)) -> (f64, f64, f64, f64) {
    (a.0.min(b.0), a.1.min(b.1), a.2.max(b.2), a.3.max(b.3))
}

fn envelope_of(node: &SpatialNode) -> (f64, f64, f64, f64) {
    (node.min_lon, node.min_lat, node.max_lon, node.max_lat)
}

fn normalize(value: f64) -> f64 {
    if value == 0.0 { 0.0 } else { value }
}

fn compare_points(a: &SpatialPoint, b: &SpatialPoint, axis: u8) -> std::cmp::Ordering {
    let (a_axis, a_other) = if axis == 0 {
        (a.lon, a.lat)
    } else {
        (a.lat, a.lon)
    };
    let (b_axis, b_other) = if axis == 0 {
        (b.lon, b.lat)
    } else {
        (b.lat, b.lon)
    };
    a_axis
        .total_cmp(&b_axis)
        .then_with(|| a_other.total_cmp(&b_other))
        .then_with(|| a.doc_id.cmp(&b.doc_id))
        .then_with(|| a.ordinal.cmp(&b.ordinal))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::segment::schema::CodecSchema;

    fn schema() -> CodecSchema {
        let schema = Schema::new(
            vec![FieldDefinition::new(
                "loc",
                FieldType::GeoPoint,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            )],
            None,
        )
        .unwrap();
        let bindings = crate::analysis::SchemaAnalyzerBindings::resolve(
            &schema,
            &crate::analysis::AnalyzerRegistry::builtin(),
        )
        .unwrap();
        CodecSchema::from_contract(&schema, &bindings).unwrap()
    }

    fn points() -> Vec<SpatialPoint> {
        vec![
            SpatialPoint {
                doc_id: 0,
                ordinal: 0,
                lon: -122.4,
                lat: 37.8,
            },
            SpatialPoint {
                doc_id: 1,
                ordinal: 0,
                lon: 0.0,
                lat: 0.0,
            },
            SpatialPoint {
                doc_id: 2,
                ordinal: 0,
                lon: 179.0,
                lat: -33.0,
            },
            SpatialPoint {
                doc_id: 3,
                ordinal: 0,
                lon: -179.0,
                lat: 33.0,
            },
        ]
    }

    #[test]
    fn round_trip_and_determinism() {
        let mut fields = vec![SpatialFieldInput {
            field_id: 0,
            points: points(),
        }];
        let first = encode_spatial(&mut fields, &SegmentLimits::default()).unwrap();
        let mut fields_again = vec![SpatialFieldInput {
            field_id: 0,
            points: points().into_iter().rev().collect(),
        }];
        let second = encode_spatial(&mut fields_again, &SegmentLimits::default()).unwrap();
        assert_eq!(first, second);
        let index = SpatialIndex::decode(&first, &schema(), 4, &SegmentLimits::default()).unwrap();
        let tree = index.field(0).unwrap();
        assert_eq!(tree.point_count(), 4);
        assert_eq!(tree.root, Some(0));
        assert!(index.field(1).is_none());
    }

    #[test]
    fn zero_points_round_trip() {
        let mut fields = vec![SpatialFieldInput {
            field_id: 0,
            points: Vec::new(),
        }];
        let bytes = encode_spatial(&mut fields, &SegmentLimits::default()).unwrap();
        let index = SpatialIndex::decode(&bytes, &schema(), 0, &SegmentLimits::default()).unwrap();
        let tree = index.field(0).unwrap();
        assert!(tree.nodes.is_empty());
        assert_eq!(tree.root, None);
    }

    #[test]
    fn malformed_node_is_rejected() {
        let mut fields = vec![SpatialFieldInput {
            field_id: 0,
            points: points(),
        }];
        let bytes = encode_spatial(&mut fields, &SegmentLimits::default()).unwrap();
        // Corrupt a coordinate to an out-of-range latitude (e.g. node 0 lat).
        let mut tampered = bytes.clone();
        let header = 6 + SPATIAL_FIELD_HEADER_BYTES;
        let lat_offset = header + 8 + 4 + 8; // doc_id, ordinal, lon
        tampered[lat_offset..lat_offset + 8].copy_from_slice(&100.0f64.to_le_bytes());
        assert!(SpatialIndex::decode(&tampered, &schema(), 4, &SegmentLimits::default()).is_err());
    }

    fn hex(bytes: &[u8]) -> String {
        use std::fmt::Write;
        let mut out = String::with_capacity(bytes.len() * 2);
        for byte in bytes {
            let _ = write!(out, "{byte:02x}");
        }
        out
    }

    #[test]
    fn golden_single_node_bytes() {
        let mut fields = vec![SpatialFieldInput {
            field_id: 0,
            points: vec![SpatialPoint {
                doc_id: 0,
                ordinal: 0,
                lon: 1.0,
                lat: 2.0,
            }],
        }];
        let bytes = encode_spatial(&mut fields, &SegmentLimits::default()).unwrap();
        assert_eq!(
            hex(&bytes),
            "0100010000000000000001000000000000000000000000000000000000000000000000000000000000000000f03f0000000000000040000000000000f03f0000000000000040000000000000f03f0000000000000040ffffffffffffffffffffffffffffffff00"
        );
    }

    #[test]
    fn golden_three_node_tree_bytes() {
        let mut fields = vec![SpatialFieldInput {
            field_id: 0,
            points: vec![
                SpatialPoint {
                    doc_id: 0,
                    ordinal: 0,
                    lon: 1.0,
                    lat: 2.0,
                },
                SpatialPoint {
                    doc_id: 1,
                    ordinal: 0,
                    lon: -1.0,
                    lat: -2.0,
                },
                SpatialPoint {
                    doc_id: 2,
                    ordinal: 0,
                    lon: 3.0,
                    lat: 4.0,
                },
            ],
        }];
        let bytes = encode_spatial(&mut fields, &SegmentLimits::default()).unwrap();
        assert_eq!(
            hex(&bytes),
            "0100010000000000000003000000000000000000000000000000000000000000000000000000000000000000f03f0000000000000040000000000000f0bf00000000000000c0000000000000084000000000000010400100000000000000020000000000000000010000000000000000000000000000000000f0bf00000000000000c0000000000000f0bf00000000000000c0000000000000f0bf00000000000000c0ffffffffffffffffffffffffffffffff01020000000000000000000000000000000000084000000000000010400000000000000840000000000000104000000000000008400000000000001040ffffffffffffffffffffffffffffffff01"
        );
    }

    #[test]
    fn encode_rejects_over_limit() {
        let points = (0..10)
            .map(|index| SpatialPoint {
                doc_id: index,
                ordinal: 0,
                lon: index as f64,
                lat: 0.0,
            })
            .collect();
        let mut fields = vec![SpatialFieldInput {
            field_id: 0,
            points,
        }];
        assert!(
            encode_spatial(
                &mut fields,
                &SegmentLimits::default().with_max_decoded_entries(1),
            )
            .is_err()
        );
        let mut fields = vec![SpatialFieldInput {
            field_id: 0,
            points: vec![SpatialPoint {
                doc_id: 0,
                ordinal: 0,
                lon: 1.0,
                lat: 2.0,
            }],
        }];
        assert!(
            encode_spatial(
                &mut fields,
                &SegmentLimits::default().with_max_section_decode_bytes(10),
            )
            .is_err()
        );
    }
}
