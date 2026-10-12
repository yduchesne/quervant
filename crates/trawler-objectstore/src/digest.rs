//! Versioned content digests for immutable object identity.
//!
//! PR 3 decision S10 fixes content identity as `(length, SHA-256)` versioned as
//! [`DigestAlgorithm::Sha256V1`]. SHA-256 is provided by the audited RustCrypto
//! [`sha2`] crate; this repository does not implement cryptographic primitives
//! itself (see `AGENTS.md`).

use std::fmt;

use sha2::{Digest, Sha256};

/// A digest algorithm version.
///
/// New algorithms are added as new variants; existing variants never change
/// meaning.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub enum DigestAlgorithm {
    /// SHA-256, version 1 (FIPS 180-4), via RustCrypto `sha2`.
    Sha256V1,
}

impl DigestAlgorithm {
    /// The number of digest bytes this algorithm produces.
    #[must_use]
    pub const fn digest_len(self) -> usize {
        match self {
            Self::Sha256V1 => 32,
        }
    }

    /// The lowercase hex identifier used in cache keys.
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::Sha256V1 => "sha256-v1",
        }
    }
}

/// An immutable content digest within a known [`DigestAlgorithm`].
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct ContentDigest {
    algorithm: DigestAlgorithm,
    bytes: [u8; 32],
}

impl ContentDigest {
    /// Number of raw bytes in a `sha256-v1` digest.
    pub const SHA256_V1_BYTES: usize = 32;

    /// Compute a `sha256-v1` digest of `data`.
    #[must_use]
    pub fn sha256_v1(data: &[u8]) -> Self {
        let digest = Sha256::digest(data);
        let mut bytes = [0u8; Self::SHA256_V1_BYTES];
        bytes.copy_from_slice(&digest);
        Self {
            algorithm: DigestAlgorithm::Sha256V1,
            bytes,
        }
    }

    /// Construct a digest from previously computed raw bytes.
    ///
    /// Used by fixtures and by adapters that receive a provider digest.
    #[must_use]
    pub fn from_sha256_v1_bytes(bytes: [u8; Self::SHA256_V1_BYTES]) -> Self {
        Self {
            algorithm: DigestAlgorithm::Sha256V1,
            bytes,
        }
    }

    /// The algorithm that produced this digest.
    #[must_use]
    pub const fn algorithm(self) -> DigestAlgorithm {
        self.algorithm
    }

    /// The raw digest bytes.
    #[must_use]
    pub const fn as_bytes(&self) -> &[u8; 32] {
        &self.bytes
    }

    /// Lowercase hexadecimal representation.
    #[must_use]
    pub fn to_hex(&self) -> String {
        const HEX: &[u8; 16] = b"0123456789abcdef";
        let mut out = String::with_capacity(self.bytes.len() * 2);
        for byte in self.bytes {
            out.push(HEX[(byte >> 4) as usize] as char);
            out.push(HEX[(byte & 0x0f) as usize] as char);
        }
        out
    }
}

impl fmt::Debug for ContentDigest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "ContentDigest({}, {})",
            self.algorithm.id(),
            self.to_hex()
        )
    }
}

impl fmt::Display for ContentDigest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.to_hex())
    }
}

/// The immutable identity of an object's bytes: exact length plus digest.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ContentDescriptor {
    /// Exact byte length.
    pub length: u64,
    /// Content digest.
    pub digest: ContentDigest,
}

impl ContentDescriptor {
    /// Construct a descriptor from an explicit length and digest.
    #[must_use]
    pub const fn new(length: u64, digest: ContentDigest) -> Self {
        Self { length, digest }
    }

    /// Compute the descriptor of the supplied bytes.
    #[must_use]
    pub fn of(bytes: &[u8]) -> Self {
        Self {
            length: bytes.len() as u64,
            digest: ContentDigest::sha256_v1(bytes),
        }
    }

    /// Verify that `bytes` exactly match this descriptor.
    #[must_use]
    pub fn matches(&self, bytes: &[u8]) -> bool {
        self.length == bytes.len() as u64 && self.digest == ContentDigest::sha256_v1(bytes)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(data: &[u8]) -> String {
        ContentDigest::sha256_v1(data).to_hex()
    }

    #[test]
    fn sha256_nist_vectors() {
        assert_eq!(
            hex(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(
            hex(b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
        );
    }

    #[test]
    fn sha256_large_deterministic_payload() {
        // Published NIST FIPS 180-4 vector: one million 'a' bytes.
        let data = vec![b'a'; 1_000_000];
        assert_eq!(
            hex(&data),
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"
        );
    }

    #[test]
    fn sha256_multiblock_padding_boundaries() {
        // 55, 56, 63, 64, 65 bytes exercise the padding length edge cases.
        for len in [55usize, 56, 63, 64, 65, 119, 120] {
            let data = vec![b'a'; len];
            let digest = ContentDigest::sha256_v1(&data);
            assert_eq!(digest.algorithm(), DigestAlgorithm::Sha256V1);
            assert_eq!(digest.as_bytes().len(), 32);
        }
    }

    #[test]
    fn known_cache_key_identity_is_stable() {
        // The hex digest is part of the cache key; changing it would orphan
        // published entries.
        let digest = ContentDigest::sha256_v1(b"abc");
        assert_eq!(
            digest.to_hex(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(
            digest.as_bytes(),
            &[
                0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea, 0x41, 0x41, 0x40, 0xde, 0x5d, 0xae,
                0x22, 0x23, 0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c, 0xb4, 0x10, 0xff, 0x61,
                0xf2, 0x00, 0x15, 0xad,
            ]
        );
    }

    #[test]
    fn descriptor_matches_bytes() {
        let bytes = b"payload";
        let descriptor = ContentDescriptor::of(bytes);
        assert_eq!(descriptor.length, 7);
        assert!(descriptor.matches(bytes));
        assert!(!descriptor.matches(b"other"));
        assert!(!descriptor.matches(b"payload!"));
        assert_eq!(descriptor.digest.to_hex().len(), 64);
        assert_eq!(descriptor.digest.algorithm().id(), "sha256-v1");
        assert_eq!(descriptor.digest.algorithm().digest_len(), 32);
    }

    #[test]
    fn from_bytes_round_trips() {
        let digest = ContentDigest::sha256_v1(b"round trip");
        let reconstructed = ContentDigest::from_sha256_v1_bytes(*digest.as_bytes());
        assert_eq!(digest, reconstructed);
    }

    #[test]
    fn digest_debug_and_display() {
        let digest = ContentDigest::sha256_v1(b"abc");
        assert!(format!("{digest:?}").contains("sha256-v1"));
        assert_eq!(format!("{digest}"), digest.to_hex());
    }
}
