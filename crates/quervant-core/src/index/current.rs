//! Strict `CURRENT` v1 generation-pointer codec (PR 6).
//!
//! `index/CURRENT` is the sole durable generation selector. Its bytes are
//! exactly five LF-terminated ASCII lines, at most 512 bytes, with no BOM,
//! trailing bytes, carriage returns or extra whitespace:
//!
//! ```text
//! QUERVANT-CURRENT 1
//! generation=0000000000000001
//! manifest=index/manifests/g-0000000000000001.manifest
//! length=<canonical decimal u64>
//! sha256=<64 lowercase hexadecimal digits>
//! ```
//!
//! The `length`/`sha256` fields describe the referenced **manifest bytes**, not
//! `CURRENT` itself. Persisted `CURRENT` is never trusted; every malformed
//! shape maps to [`IndexError::InvalidCurrent`].

use quervant_objectstore::ContentDigest;

use crate::storage::StorageKey;

use super::error::{IndexError, IndexResult};

/// The durable generation-selector key, relative to the index root.
pub const CURRENT_KEY: &str = "index/CURRENT";

/// The exclusive cooperating-writer marker key.
pub const WRITER_LOCK_KEY: &str = "index/WRITER_LOCK";

/// The maximum accepted encoded `CURRENT` length in bytes.
pub const CURRENT_MAX_BYTES: usize = 512;

/// The supported `CURRENT` version.
pub const CURRENT_VERSION: u16 = 1;

const MAGIC: &[u8] = b"QUERVANT-CURRENT 1\n";
const NUL: &[u8] = b"\n";

/// A validated durable generation pointer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CurrentPointer {
    generation: u64,
    manifest_key: StorageKey,
    manifest_length: u64,
    manifest_digest: ContentDigest,
}

impl CurrentPointer {
    /// Construct a pointer for `generation` describing the given manifest bytes.
    pub fn new(
        generation: u64,
        manifest_length: u64,
        manifest_digest: ContentDigest,
    ) -> IndexResult<Self> {
        if generation == 0 {
            return Err(IndexError::InvalidCurrent {
                detail: "generation must be >= 1".to_owned(),
            });
        }
        if manifest_length == 0 {
            return Err(IndexError::InvalidCurrent {
                detail: "manifest length must be nonzero".to_owned(),
            });
        }
        if manifest_digest.algorithm() != quervant_objectstore::DigestAlgorithm::Sha256V1 {
            return Err(IndexError::InvalidCurrent {
                detail: "manifest digest must be sha256-v1".to_owned(),
            });
        }
        let manifest_key = StorageKey::parse(manifest_key_for(generation))?;
        let pointer = Self {
            generation,
            manifest_key,
            manifest_length,
            manifest_digest,
        };
        // Fail closed if the canonical encoding would exceed the bound.
        pointer.encode()?;
        Ok(pointer)
    }

    /// The durable generation.
    #[must_use]
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    /// Storage key of the referenced manifest.
    #[must_use]
    pub const fn manifest_key(&self) -> &StorageKey {
        &self.manifest_key
    }

    /// Exact encoded manifest length.
    #[must_use]
    pub const fn manifest_length(&self) -> u64 {
        self.manifest_length
    }

    /// Manifest content digest.
    #[must_use]
    pub const fn manifest_digest(&self) -> ContentDigest {
        self.manifest_digest
    }

    /// Encode the canonical five-line representation.
    ///
    /// Returns [`IndexError::InvalidCurrent`] if the result exceeds
    /// [`CURRENT_MAX_BYTES`].
    pub fn encode(&self) -> IndexResult<Vec<u8>> {
        let mut out = Vec::with_capacity(160);
        out.extend_from_slice(MAGIC);
        out.extend_from_slice(format!("generation={:016x}\n", self.generation).as_bytes());
        out.extend_from_slice(format!("manifest={}\n", self.manifest_key.as_str()).as_bytes());
        out.extend_from_slice(format!("length={}\n", self.manifest_length).as_bytes());
        out.extend_from_slice(format!("sha256={}\n", self.manifest_digest.to_hex()).as_bytes());
        if out.len() > CURRENT_MAX_BYTES {
            return Err(IndexError::InvalidCurrent {
                detail: format!("encoded CURRENT exceeds {CURRENT_MAX_BYTES} bytes"),
            });
        }
        Ok(out)
    }

    /// Strictly parse and validate encoded `CURRENT` bytes.
    pub fn parse(bytes: &[u8]) -> IndexResult<Self> {
        if bytes.len() > CURRENT_MAX_BYTES {
            return Err(invalid(format!(
                "encoded length {} exceeds {CURRENT_MAX_BYTES}",
                bytes.len()
            )));
        }
        if !bytes.is_ascii() {
            return Err(invalid("contains non-ASCII bytes".to_owned()));
        }
        if bytes.contains(&b'\r') {
            return Err(invalid("contains carriage return".to_owned()));
        }
        if !bytes.ends_with(NUL) {
            return Err(invalid("missing final line feed".to_owned()));
        }
        let body = &bytes[..bytes.len() - 1];
        let lines: Vec<&[u8]> = body.split(|byte| *byte == b'\n').collect();
        if lines.len() != 5 {
            return Err(invalid(format!("expected 5 lines, found {}", lines.len())));
        }
        if lines[0] != b"QUERVANT-CURRENT 1" {
            return Err(invalid("unsupported header/version".to_owned()));
        }
        let generation = parse_generation(lines[1])?;
        let manifest_key = parse_manifest(lines[2], generation)?;
        let manifest_length = parse_length(lines[3])?;
        let manifest_digest = parse_digest(lines[4])?;
        Ok(Self {
            generation,
            manifest_key,
            manifest_length,
            manifest_digest,
        })
    }
}

/// The canonical generation-manifest key for `generation`.
#[must_use]
pub fn manifest_key_for(generation: u64) -> String {
    format!("index/manifests/g-{generation:016x}.manifest")
}

/// The canonical content-addressed segment key for a lowercase hex digest.
#[must_use]
pub fn segment_key_for_hex(hex: &str) -> String {
    format!("index/segments/{hex}.seg")
}

fn invalid(detail: String) -> IndexError {
    IndexError::InvalidCurrent { detail }
}

fn parse_generation(line: &[u8]) -> IndexResult<u64> {
    let rest = strip_field(line, b"generation=")?;
    if rest.len() != 16 {
        return Err(invalid(
            "generation must be exactly 16 hex digits".to_owned(),
        ));
    }
    if !rest.iter().all(u8::is_ascii_hexdigit) {
        return Err(invalid(
            "generation is not lowercase hexadecimal".to_owned(),
        ));
    }
    let text = std::str::from_utf8(rest).map_err(|_| invalid("generation not UTF-8".to_owned()))?;
    if text.bytes().any(|byte| byte.is_ascii_uppercase()) {
        return Err(invalid(
            "generation must be lowercase hexadecimal".to_owned(),
        ));
    }
    let generation = u64::from_str_radix(text, 16)
        .map_err(|_| invalid("generation is not a valid u64".to_owned()))?;
    if generation == 0 {
        return Err(invalid("generation must be >= 1".to_owned()));
    }
    Ok(generation)
}

fn parse_manifest(line: &[u8], generation: u64) -> IndexResult<StorageKey> {
    let rest = strip_field(line, b"manifest=")?;
    let text =
        std::str::from_utf8(rest).map_err(|_| invalid("manifest key not UTF-8".to_owned()))?;
    let key = StorageKey::parse(text)
        .map_err(|error| invalid(format!("manifest is not a valid storage key: {error}")))?;
    let expected = manifest_key_for(generation);
    if key.as_str() != expected {
        return Err(invalid(format!(
            "manifest key does not match generation (expected {expected})"
        )));
    }
    Ok(key)
}

fn parse_length(line: &[u8]) -> IndexResult<u64> {
    let rest = strip_field(line, b"length=")?;
    if rest.is_empty() || !rest.iter().all(u8::is_ascii_digit) {
        return Err(invalid("length is not canonical decimal".to_owned()));
    }
    let text = std::str::from_utf8(rest).map_err(|_| invalid("length not UTF-8".to_owned()))?;
    if text.len() > 1 && text.starts_with('0') {
        return Err(invalid("length has a leading zero".to_owned()));
    }
    let length: u64 = text
        .parse()
        .map_err(|_| invalid("length is not a valid u64".to_owned()))?;
    if length == 0 {
        return Err(invalid("manifest length must be nonzero".to_owned()));
    }
    Ok(length)
}

fn parse_digest(line: &[u8]) -> IndexResult<ContentDigest> {
    let rest = strip_field(line, b"sha256=")?;
    if rest.len() != 64 {
        return Err(invalid("digest must be exactly 64 hex digits".to_owned()));
    }
    let text = std::str::from_utf8(rest).map_err(|_| invalid("digest not UTF-8".to_owned()))?;
    let mut out = [0u8; 32];
    for (index, chunk) in text.as_bytes().chunks_exact(2).enumerate() {
        let high = hex_value(chunk[0])?;
        let low = hex_value(chunk[1])?;
        out[index] = (high << 4) | low;
    }
    Ok(ContentDigest::from_sha256_v1_bytes(out))
}

fn hex_value(byte: u8) -> IndexResult<u8> {
    match byte {
        b'0'..=b'9' => Ok(byte - b'0'),
        b'a'..=b'f' => Ok(byte - b'a' + 10),
        _ => Err(invalid("digest is not lowercase hexadecimal".to_owned())),
    }
}

fn strip_field<'a>(line: &'a [u8], prefix: &[u8]) -> IndexResult<&'a [u8]> {
    line.strip_prefix(prefix).ok_or_else(|| {
        invalid(format!(
            "unexpected/duplicate field (expected {})",
            String::from_utf8_lossy(prefix)
        ))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> CurrentPointer {
        CurrentPointer::new(1, 5, ContentDigest::sha256_v1(b"abc")).unwrap()
    }

    #[test]
    fn round_trips_canonical_bytes() {
        let pointer = sample();
        let bytes = pointer.encode().unwrap();
        assert_eq!(
            bytes,
            b"QUERVANT-CURRENT 1\n\
              generation=0000000000000001\n\
              manifest=index/manifests/g-0000000000000001.manifest\n\
              length=5\n\
              sha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n"
        );
        assert!(bytes.len() <= CURRENT_MAX_BYTES);
        assert_eq!(CurrentPointer::parse(&bytes).unwrap(), pointer);
    }

    #[test]
    fn generation_boundaries_round_trip() {
        let max = CurrentPointer::new(u64::MAX, 1, ContentDigest::sha256_v1(b"x")).unwrap();
        let bytes = max.encode().unwrap();
        assert!(bytes.windows(16).any(|w| w == b"ffffffffffffffff"));
        assert_eq!(
            CurrentPointer::parse(&bytes).unwrap().generation(),
            u64::MAX
        );
        assert!(CurrentPointer::new(0, 1, ContentDigest::sha256_v1(b"x")).is_err());
    }

    #[test]
    fn rejects_malformed_current() {
        let good = sample().encode().unwrap();
        let cases: Vec<Vec<u8>> = vec![
            Vec::new(),
            b"QUERVANT-CURRENT 2\ngeneration=0000000000000001\nmanifest=index/manifests/g-0000000000000001.manifest\nlength=5\nsha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n".to_vec(),
            b"QUERVANT-CURRENT 1\ngeneration=0000000000000001\nmanifest=index/manifests/g-0000000000000001.manifest\nlength=5\nsha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad".to_vec(),
            b"QUERVANT-CURRENT 1\ngeneration=0000000000000001\nmanifest=index/manifests/g-0000000000000001.manifest\nlength=5\nsha256=BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD\n".to_vec(),
            b"QUERVANT-CURRENT 1\ngeneration=0000000000000000\nmanifest=index/manifests/g-0000000000000000.manifest\nlength=5\nsha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n".to_vec(),
            b"QUERVANT-CURRENT 1\ngeneration=0000000000000001\nmanifest=index/manifests/g-0000000000000002.manifest\nlength=5\nsha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n".to_vec(),
            b"QUERVANT-CURRENT 1\ngeneration=0000000000000001\nmanifest=index/manifests/g-0000000000000001.manifest\nlength=05\nsha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n".to_vec(),
            b"QUERVANT-CURRENT 1\ngeneration=0000000000000001\nmanifest=index/manifests/g-0000000000000001.manifest\nlength=5\nsha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015a\n".to_vec(),
            b"QUERVANT-CURRENT 1\ngeneration=0000000000000001\nmanifest=index/manifests/g-0000000000000001.manifest\nlength=5\nsha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\nextra=1\n".to_vec(),
            b"QUERVANT-CURRENT 1\ngeneration=0000000000000001\ngeneration=0000000000000001\nlength=5\nsha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n".to_vec(),
            b"QUERVANT-CURRENT 1\r\ngeneration=0000000000000001\nmanifest=index/manifests/g-0000000000000001.manifest\nlength=5\nsha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n".to_vec(),
            b"QUERVANT-CURRENT 1\ngeneration=0000000000000001\nmanifest=index/manifests/g-0000000000000001.manifest\nlength=5\nsha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\ntrailing".to_vec(),
        ];
        for case in cases {
            assert!(
                matches!(
                    CurrentPointer::parse(&case),
                    Err(IndexError::InvalidCurrent { .. })
                ),
                "expected rejection for {:?}",
                String::from_utf8_lossy(&case)
            );
        }
        // A single non-ASCII byte is rejected.
        let mut non_ascii = good.clone();
        non_ascii[0] = 0xff;
        assert!(CurrentPointer::parse(&non_ascii).is_err());
        // Oversized input is rejected.
        let oversized = vec![b'a'; CURRENT_MAX_BYTES + 1];
        assert!(CurrentPointer::parse(&oversized).is_err());
    }

    #[test]
    fn rejects_noncanonical_manifest_keys() {
        let line: &[u8] = b"manifest=index/manifests/other.manifest\n";
        let cases: [&[u8]; 2] = [line, b"manifest=../escape\n"];
        for manifest in cases {
            let bytes: Vec<u8> = [
                b"QUERVANT-CURRENT 1\n".as_slice(),
                b"generation=0000000000000001\n".as_slice(),
                manifest,
                b"length=5\n".as_slice(),
                b"sha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n"
                    .as_slice(),
            ]
            .concat();
            assert!(CurrentPointer::parse(&bytes).is_err());
        }
    }

    #[test]
    fn canonical_key_helpers() {
        assert_eq!(
            manifest_key_for(1),
            "index/manifests/g-0000000000000001.manifest"
        );
        assert_eq!(segment_key_for_hex("abc"), "index/segments/abc.seg");
    }
}
