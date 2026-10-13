//! Conservative temporal and geospatial segment bounds (F08).
//!
//! Bounds are pruning metadata only: metadata that cannot prove a predicate
//! unsatisfiable must disable pruning. Absent/unknown presence never excludes
//! matches.

use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};

/// Presence not tracked.
pub const PRESENCE_UNKNOWN: u8 = 0;
/// No live document has an applicable value.
pub const PRESENCE_NONE: u8 = 1;
/// Some but not all live documents have an applicable value.
pub const PRESENCE_SOME: u8 = 2;
/// Every live document has at least one applicable value.
pub const PRESENCE_ALL: u8 = 3;

/// Compute the presence tag from counts.
#[must_use]
pub const fn presence_of(live_count: u64, present_count: u64) -> u8 {
    if present_count == 0 {
        PRESENCE_NONE
    } else if present_count >= live_count {
        PRESENCE_ALL
    } else {
        PRESENCE_SOME
    }
}

/// Temporal bounds for the primary timestamp field.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TimeBounds {
    /// Primary timestamp field id.
    pub field_id: u32,
    /// Whether bounds are known (`true`) or unprunable (`false`).
    pub known: bool,
    /// Presence tag.
    pub presence: u8,
    /// Live document count.
    pub live_count: u64,
    /// Documents with an applicable timestamp.
    pub present_count: u64,
    /// Minimum timestamp in microseconds (valid when `known`).
    pub min_micros: i64,
    /// Maximum timestamp in microseconds (valid when `known`).
    pub max_micros: i64,
    /// Whether the timestamp layout is physically ordered.
    pub ordered: bool,
}

impl TimeBounds {
    /// An unprunable (unknown) bound.
    #[must_use]
    pub const fn unknown(field_id: u32, live_count: u64) -> Self {
        Self {
            field_id,
            known: false,
            presence: PRESENCE_UNKNOWN,
            live_count,
            present_count: 0,
            min_micros: 0,
            max_micros: 0,
            ordered: false,
        }
    }

    /// Whether a positive half-open `[start, end)` time range can be pruned.
    ///
    /// Missing/null values never satisfy a positive range predicate, so pruning
    /// is safe under `PRESENCE_SOME`.
    #[must_use]
    pub fn prunes_positive_range(&self, start: i64, end: i64) -> bool {
        if !self.known || self.presence == PRESENCE_UNKNOWN {
            return false;
        }
        if self.present_count == 0 {
            return true;
        }
        self.max_micros < start || self.min_micros >= end
    }

    /// Whether a negated half-open range can be pruned.
    ///
    /// A missing value may satisfy `NOT range`, so this requires every live
    /// document to have a value and all values to be inside the range.
    #[must_use]
    pub fn prunes_negated_range(&self, start: i64, end: i64) -> bool {
        if !self.known || self.presence != PRESENCE_ALL {
            return false;
        }
        self.min_micros >= start && self.max_micros < end
    }

    /// Whether `IS NULL`/`MISSING` can be pruned (every live doc has a value).
    #[must_use]
    pub fn prunes_value_less(&self) -> bool {
        self.known && self.presence == PRESENCE_ALL
    }

    /// Whether `EXISTS(value)`/`IS NOT NULL` can be pruned (no values present).
    #[must_use]
    pub fn prunes_exists(&self) -> bool {
        self.known && self.present_count == 0
    }

    /// Encode the TIME_BOUNDS section body for one bound.
    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        let mut writer = ByteWriter::new();
        writer.u32(self.field_id);
        writer.u8(u8::from(self.known));
        writer.u8(self.presence);
        writer.u64(self.live_count);
        writer.u64(self.present_count);
        writer.i64(self.min_micros);
        writer.i64(self.max_micros);
        writer.u8(u8::from(self.ordered));
        writer.into_vec()
    }

    /// Decode a TIME_BOUNDS section body.
    pub fn decode(bytes: &[u8]) -> SegmentResult<Self> {
        let mut reader = ByteReader::new(bytes);
        let field_id = reader.u32("time field id")?;
        let known = match reader.u8("time known")? {
            0 => false,
            1 => true,
            value => {
                return Err(SegmentError::Corrupt {
                    context: "time known",
                    detail: format!("invalid {value}"),
                });
            }
        };
        let presence = reader.u8("time presence")?;
        if presence > PRESENCE_ALL {
            return Err(SegmentError::Corrupt {
                context: "time presence",
                detail: format!("invalid {presence}"),
            });
        }
        let live_count = reader.u64("time live count")?;
        let present_count = reader.u64("time present count")?;
        let min_micros = reader.i64("time min")?;
        let max_micros = reader.i64("time max")?;
        let ordered = match reader.u8("time ordered")? {
            0 => false,
            1 => true,
            value => {
                return Err(SegmentError::Corrupt {
                    context: "time ordered",
                    detail: format!("invalid {value}"),
                });
            }
        };
        reader.expect_end("time bounds")?;
        if present_count > live_count {
            return Err(SegmentError::Corrupt {
                context: "time bounds",
                detail: "present count exceeds live count".to_owned(),
            });
        }
        if presence != PRESENCE_UNKNOWN && presence != presence_of(live_count, present_count) {
            return Err(SegmentError::Corrupt {
                context: "time bounds",
                detail: "presence disagrees with counts".to_owned(),
            });
        }
        if known && present_count > 0 && min_micros > max_micros {
            return Err(SegmentError::Corrupt {
                context: "time bounds",
                detail: "min exceeds max".to_owned(),
            });
        }
        Ok(Self {
            field_id,
            known,
            presence,
            live_count,
            present_count,
            min_micros,
            max_micros,
            ordered,
        })
    }
}

/// Geographic envelope for one GeoPoint field.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GeoBounds {
    /// GeoPoint field id.
    pub field_id: u32,
    /// Whether the envelope is known.
    pub known: bool,
    /// Presence tag.
    pub presence: u8,
    /// Live document count.
    pub live_count: u64,
    /// Documents with at least one point.
    pub present_count: u64,
    /// Western longitude.
    pub west: f64,
    /// Southern latitude.
    pub south: f64,
    /// Eastern longitude.
    pub east: f64,
    /// Northern latitude.
    pub north: f64,
    /// Whether the envelope crosses the antimeridian.
    pub crosses_antimeridian: bool,
}

impl GeoBounds {
    /// An unprunable (unknown) envelope.
    #[must_use]
    pub const fn unknown(field_id: u32, live_count: u64) -> Self {
        Self {
            field_id,
            known: false,
            presence: PRESENCE_UNKNOWN,
            live_count,
            present_count: 0,
            west: 0.0,
            south: 0.0,
            east: 0.0,
            north: 0.0,
            crosses_antimeridian: false,
        }
    }

    /// Whether a positive bounding box can be pruned.
    ///
    /// Conservative: a missing point never satisfies a positive predicate, and
    /// disjoint intervals/parallels prove no point can fall in the box.
    #[must_use]
    pub fn prunes_positive_box(&self, west: f64, south: f64, east: f64, north: f64) -> bool {
        if !self.known || self.presence == PRESENCE_UNKNOWN {
            return false;
        }
        if self.present_count == 0 {
            return true;
        }
        if self.north < south || self.south > north {
            return true;
        }
        // Longitude intervals: a crossing box is the union of two intervals.
        !lon_intersects(
            self.west,
            self.east,
            self.crosses_antimeridian,
            west,
            east,
            west > east,
        )
    }

    /// Encode the GEO_BOUNDS entry (without the section count prefix).
    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        let mut writer = ByteWriter::new();
        writer.u32(self.field_id);
        writer.u8(u8::from(self.known));
        writer.u8(self.presence);
        writer.u64(self.live_count);
        writer.u64(self.present_count);
        writer.f64(self.west);
        writer.f64(self.south);
        writer.f64(self.east);
        writer.f64(self.north);
        writer.u8(u8::from(self.crosses_antimeridian));
        writer.into_vec()
    }

    /// Decode a GEO_BOUNDS entry.
    pub fn decode(bytes: &[u8]) -> SegmentResult<Self> {
        let mut reader = ByteReader::new(bytes);
        let field_id = reader.u32("geo field id")?;
        let known = match reader.u8("geo known")? {
            0 => false,
            1 => true,
            value => {
                return Err(SegmentError::Corrupt {
                    context: "geo known",
                    detail: format!("invalid {value}"),
                });
            }
        };
        let presence = reader.u8("geo presence")?;
        if presence > PRESENCE_ALL {
            return Err(SegmentError::Corrupt {
                context: "geo presence",
                detail: format!("invalid {presence}"),
            });
        }
        let live_count = reader.u64("geo live count")?;
        let present_count = reader.u64("geo present count")?;
        let west = reader.f64("geo west")?;
        let south = reader.f64("geo south")?;
        let east = reader.f64("geo east")?;
        let north = reader.f64("geo north")?;
        let crosses_antimeridian = match reader.u8("geo antimeridian")? {
            0 => false,
            1 => true,
            value => {
                return Err(SegmentError::Corrupt {
                    context: "geo antimeridian",
                    detail: format!("invalid {value}"),
                });
            }
        };
        reader.expect_end("geo bounds")?;
        if present_count > live_count {
            return Err(SegmentError::Corrupt {
                context: "geo bounds",
                detail: "present count exceeds live count".to_owned(),
            });
        }
        if presence != PRESENCE_UNKNOWN && presence != presence_of(live_count, present_count) {
            return Err(SegmentError::Corrupt {
                context: "geo bounds",
                detail: "presence disagrees with counts".to_owned(),
            });
        }
        Ok(Self {
            field_id,
            known,
            presence,
            live_count,
            present_count,
            west,
            south,
            east,
            north,
            crosses_antimeridian,
        })
    }
}

fn lon_intersects(
    a_west: f64,
    a_east: f64,
    a_cross: bool,
    b_west: f64,
    b_east: f64,
    b_cross: bool,
) -> bool {
    let a = intervals(a_west, a_east, a_cross);
    let b = intervals(b_west, b_east, b_cross);
    for (a_lo, a_hi) in a.iter().copied() {
        for (b_lo, b_hi) in b.iter().copied() {
            if a_lo <= b_hi && b_lo <= a_hi {
                return true;
            }
        }
    }
    false
}

fn intervals(west: f64, east: f64, cross: bool) -> Vec<(f64, f64)> {
    if cross {
        vec![(west, 180.0), (-180.0, east)]
    } else {
        vec![(west, east)]
    }
}
