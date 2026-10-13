//! Canonical schema identity and analyzer bindings (F03).

use crate::analysis::registry::SchemaAnalyzerBindings;
use crate::contract::document::Cardinality;
use crate::contract::schema::{FieldOptions, Schema};
use crate::contract::value::FieldType;

use super::decode_budget::DecodeBudget;
use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;

/// A persisted analyzer/normalizer binding: id, version and canonical fingerprint.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FieldBinding {
    /// Analyzer id.
    pub id: String,
    /// Analyzer semantic version.
    pub version: String,
    /// Canonical 32-byte fingerprint.
    pub fingerprint: [u8; 32],
}

impl FieldBinding {
    fn encode(&self, writer: &mut ByteWriter) -> SegmentResult<()> {
        writer.len_prefixed_u16(self.id.as_bytes())?;
        writer.len_prefixed_u16(self.version.as_bytes())?;
        writer.bytes(&self.fingerprint);
        Ok(())
    }

    fn decode_budgeted(
        reader: &mut ByteReader<'_>,
        budget: &mut DecodeBudget<'_>,
    ) -> SegmentResult<Self> {
        let id_bytes = reader.len_prefixed_u16("analyzer id")?;
        let id_ref = std::str::from_utf8(id_bytes).map_err(|_| SegmentError::InvalidUtf8 {
            context: "analyzer id",
        })?;
        let version_bytes = reader.len_prefixed_u16("analyzer version")?;
        let version_ref =
            std::str::from_utf8(version_bytes).map_err(|_| SegmentError::InvalidUtf8 {
                context: "analyzer version",
            })?;
        budget.reserve_string(id_ref.len() as u64)?;
        budget.reserve_string(version_ref.len() as u64)?;
        let fingerprint = reader.bytes(32, "analyzer fingerprint")?;
        let mut array = [0u8; 32];
        array.copy_from_slice(fingerprint);
        Ok(Self {
            id: id_ref.to_owned(),
            version: version_ref.to_owned(),
            fingerprint: array,
        })
    }
}

/// A canonically identified schema field.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecField {
    /// Dense field id.
    pub id: u32,
    /// Field name.
    pub name: String,
    /// Field type.
    pub field_type: FieldType,
    /// Cardinality.
    pub cardinality: Cardinality,
    /// Capability flags.
    pub options: FieldOptions,
    /// Index-time analyzer binding (Text only).
    pub analyzer: Option<FieldBinding>,
    /// Normalizer binding (Keyword only).
    pub normalizer: Option<FieldBinding>,
}

impl CodecField {
    /// Whether this field is indexed.
    #[must_use]
    pub const fn is_indexed(&self) -> bool {
        self.options.indexed
    }

    /// Whether this field is columnar.
    #[must_use]
    pub const fn is_columnar(&self) -> bool {
        self.options.columnar
    }

    /// Whether this field is stored.
    #[must_use]
    pub const fn is_stored(&self) -> bool {
        self.options.stored
    }
}

/// The canonical codec schema.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecSchema {
    fields: Vec<CodecField>,
    primary_timestamp: Option<u32>,
}

impl CodecSchema {
    /// Build the canonical schema from a validated contract schema and resolved bindings.
    ///
    /// Field ids are assigned by ascending UTF-8 byte order of the field name, so
    /// identical schemas encode identically regardless of declaration order.
    pub fn from_contract(
        schema: &Schema,
        bindings: &SchemaAnalyzerBindings,
    ) -> SegmentResult<Self> {
        let mut fields: Vec<CodecField> = Vec::new();
        for (id, definition) in schema.fields().enumerate() {
            let id = u32::try_from(id).map_err(|_| SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: (id + 1) as u64,
            })?;
            let binding = bindings
                .get(&definition.name)
                .and_then(|field| field.index.clone());
            let (analyzer, normalizer) = match definition.field_type {
                FieldType::Text => (binding, None),
                FieldType::Keyword => (None, binding),
                _ => (None, None),
            };
            fields.push(CodecField {
                id,
                name: definition.name.clone(),
                field_type: definition.field_type,
                cardinality: definition.cardinality,
                options: definition.options,
                analyzer: analyzer.map(to_field_binding),
                normalizer: normalizer.map(to_field_binding),
            });
        }
        let primary_timestamp = schema
            .primary_timestamp()
            .map(|name| {
                fields
                    .iter()
                    .find(|field| field.name == name)
                    .map(|field| field.id)
                    .ok_or_else(|| SegmentError::Corrupt {
                        context: "schema",
                        detail: "missing primary timestamp field".to_owned(),
                    })
            })
            .transpose()?;
        let schema = Self {
            fields,
            primary_timestamp,
        };
        schema.validate()?;
        Ok(schema)
    }

    /// Fields in ascending id order.
    #[must_use]
    pub fn fields(&self) -> &[CodecField] {
        &self.fields
    }

    /// Number of fields.
    #[must_use]
    pub fn field_count(&self) -> usize {
        self.fields.len()
    }

    /// Primary timestamp field id.
    #[must_use]
    pub const fn primary_timestamp(&self) -> Option<u32> {
        self.primary_timestamp
    }

    /// Look up a field by id.
    #[must_use]
    pub fn field(&self, id: u32) -> Option<&CodecField> {
        self.fields.get(id as usize).filter(|field| field.id == id)
    }

    /// Look up a field id by name.
    #[must_use]
    pub fn field_id(&self, name: &str) -> Option<u32> {
        self.fields
            .iter()
            .find(|field| field.name == name)
            .map(|field| field.id)
    }

    fn validate(&self) -> SegmentResult<()> {
        for (index, field) in self.fields.iter().enumerate() {
            if field.id as usize != index {
                return Err(SegmentError::Corrupt {
                    context: "schema",
                    detail: "field ids are not dense".to_owned(),
                });
            }
            if field.options.is_useless() {
                return Err(SegmentError::Corrupt {
                    context: "schema",
                    detail: "useless field options".to_owned(),
                });
            }
            if field.analyzer.is_some() && field.field_type != FieldType::Text {
                return Err(SegmentError::Corrupt {
                    context: "schema",
                    detail: "analyzer on non-text field".to_owned(),
                });
            }
            if field.normalizer.is_some() && field.field_type != FieldType::Keyword {
                return Err(SegmentError::Corrupt {
                    context: "schema",
                    detail: "normalizer on non-keyword field".to_owned(),
                });
            }
            if field.options.columnar
                && matches!(field.field_type, FieldType::Text | FieldType::Json)
            {
                return Err(SegmentError::Corrupt {
                    context: "schema",
                    detail: "columnar on text/json field".to_owned(),
                });
            }
        }
        for (index, field) in self.fields.iter().enumerate() {
            if self.fields[index + 1..]
                .iter()
                .any(|other| other.name == field.name)
            {
                return Err(SegmentError::DuplicateField {
                    name: field.name.clone(),
                });
            }
        }
        if let Some(primary) = self.primary_timestamp {
            let field = self
                .field(primary)
                .ok_or(SegmentError::UnknownFieldId { field_id: primary })?;
            if field.field_type != FieldType::Timestamp
                || field.cardinality != Cardinality::Single
                || !field.options.indexed
            {
                return Err(SegmentError::Corrupt {
                    context: "schema",
                    detail: "invalid primary timestamp".to_owned(),
                });
            }
        }
        Ok(())
    }

    /// Encode the schema section body.
    pub fn encode(&self) -> SegmentResult<Vec<u8>> {
        let mut writer = ByteWriter::new();
        writer.u16(1); // descriptor_version
        writer.u32(
            u32::try_from(self.fields.len()).map_err(|_| SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: self.fields.len() as u64,
            })?,
        );
        for field in &self.fields {
            writer.u32(field.id);
            writer.len_prefixed_u16(field.name.as_bytes())?;
            writer.u8(field_type_tag(field.field_type));
            writer.u8(match field.cardinality {
                Cardinality::Single => 0,
                Cardinality::Multi => 1,
            });
            let mut flags = 0u8;
            if field.options.indexed {
                flags |= 0b001;
            }
            if field.options.stored {
                flags |= 0b010;
            }
            if field.options.columnar {
                flags |= 0b100;
            }
            writer.u8(flags);
            encode_optional_binding(&mut writer, field.analyzer.as_ref())?;
            encode_optional_binding(&mut writer, field.normalizer.as_ref())?;
            writer.u16(0); // reserved
        }
        match self.primary_timestamp {
            None => writer.u8(0),
            Some(id) => {
                writer.u8(1);
                writer.u32(id);
            }
        }
        Ok(writer.into_vec())
    }

    /// Decode and validate a schema section body.
    pub fn decode(bytes: &[u8], limits: &SegmentLimits) -> SegmentResult<Self> {
        let mut reader = ByteReader::new(bytes);
        let version = reader.u16("schema version")?;
        if version != 1 {
            return Err(SegmentError::Corrupt {
                context: "schema version",
                detail: format!("unsupported {version}"),
            });
        }
        let field_count = reader.u32("schema field count")?;
        let field_count_u64 = u64::from(field_count);
        limits.check_entries(field_count_u64)?;
        // Minimum field body: id(4)+name_len(2)+0-name+type(1)+cardinality(1)
        // +options(1)+analyzer(1)+normalizer(1)+reserved(2) = 13.
        super::format::count_min_bytes(
            "schema fields",
            field_count_u64,
            13,
            reader.remaining() as u64,
        )?;
        let mut budget = DecodeBudget::new(limits);
        budget.reserve_vec::<CodecField>(field_count_u64)?;
        let mut fields: Vec<CodecField> = Vec::new();
        fields
            .try_reserve_exact(usize::try_from(field_count).map_err(|_| {
                SegmentError::LimitExceeded {
                    limit: limits.max_single_allocation(),
                    requested: field_count_u64,
                }
            })?)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: field_count_u64,
            })?;
        for _ in 0..field_count {
            let id = reader.u32("field id")?;
            let name_bytes = reader.len_prefixed_u16("field name")?;
            let name_ref =
                std::str::from_utf8(name_bytes).map_err(|_| SegmentError::InvalidUtf8 {
                    context: "field name",
                })?;
            budget.reserve_string(name_ref.len() as u64)?;
            let name = name_ref.to_owned();
            let type_tag = reader.u8("field type tag")?;
            let field_type = field_type_from_tag(type_tag)?;
            let cardinality = match reader.u8("cardinality")? {
                0 => Cardinality::Single,
                1 => Cardinality::Multi,
                value => return Err(SegmentError::InvalidCardinality { value }),
            };
            let flags = reader.u8("field options")?;
            if flags & !0b111 != 0 {
                return Err(SegmentError::UnknownFlags {
                    context: "field options",
                    flags: u64::from(flags),
                });
            }
            let analyzer = decode_optional_binding_budgeted(&mut reader, &mut budget)?;
            let normalizer = decode_optional_binding_budgeted(&mut reader, &mut budget)?;
            let reserved = reader.u16("field reserved")?;
            if reserved != 0 {
                return Err(SegmentError::UnknownFlags {
                    context: "field reserved",
                    flags: u64::from(reserved),
                });
            }
            fields.push(CodecField {
                id,
                name,
                field_type,
                cardinality,
                options: FieldOptions::new(
                    flags & 0b001 != 0,
                    flags & 0b010 != 0,
                    flags & 0b100 != 0,
                ),
                analyzer,
                normalizer,
            });
        }
        let primary_timestamp = match reader.u8("primary timestamp present")? {
            0 => None,
            1 => Some(reader.u32("primary timestamp id")?),
            value => {
                return Err(SegmentError::Corrupt {
                    context: "primary timestamp",
                    detail: format!("invalid presence tag {value}"),
                });
            }
        };
        reader.expect_end("schema")?;
        let schema = Self {
            fields,
            primary_timestamp,
        };
        schema.validate()?;
        Ok(schema)
    }
}

fn to_field_binding(binding: crate::analysis::AnalyzerBinding) -> FieldBinding {
    FieldBinding {
        id: binding.id,
        version: binding.version,
        fingerprint: *binding.fingerprint.as_bytes(),
    }
}

fn encode_optional_binding(
    writer: &mut ByteWriter,
    binding: Option<&FieldBinding>,
) -> SegmentResult<()> {
    match binding {
        None => writer.u8(0),
        Some(binding) => {
            writer.u8(1);
            binding.encode(writer)?;
        }
    }
    Ok(())
}

fn decode_optional_binding_budgeted(
    reader: &mut ByteReader<'_>,
    budget: &mut DecodeBudget<'_>,
) -> SegmentResult<Option<FieldBinding>> {
    match reader.u8("binding present")? {
        0 => Ok(None),
        1 => Ok(Some(FieldBinding::decode_budgeted(reader, budget)?)),
        value => Err(SegmentError::Corrupt {
            context: "binding presence",
            detail: format!("invalid tag {value}"),
        }),
    }
}

/// Map a field type to its on-disk tag.
#[must_use]
pub const fn field_type_tag(field_type: FieldType) -> u8 {
    match field_type {
        FieldType::Text => 1,
        FieldType::Keyword => 2,
        FieldType::Bool => 3,
        FieldType::I64 => 4,
        FieldType::U64 => 5,
        FieldType::F64 => 6,
        FieldType::Timestamp => 7,
        FieldType::Json => 8,
        FieldType::GeoPoint => 9,
        FieldType::IpAddress => 10,
        FieldType::IpNetwork => 11,
    }
}

/// Map an on-disk tag to a field type.
pub fn field_type_from_tag(tag: u8) -> SegmentResult<FieldType> {
    Ok(match tag {
        1 => FieldType::Text,
        2 => FieldType::Keyword,
        3 => FieldType::Bool,
        4 => FieldType::I64,
        5 => FieldType::U64,
        6 => FieldType::F64,
        7 => FieldType::Timestamp,
        8 => FieldType::Json,
        9 => FieldType::GeoPoint,
        10 => FieldType::IpAddress,
        11 => FieldType::IpNetwork,
        _ => return Err(SegmentError::InvalidFieldTypeTag { tag }),
    })
}
